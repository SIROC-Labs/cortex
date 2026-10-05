"""The agent seam.

Everything the orchestrator knows about calling a language model lives in these
three types. No vendor name, no SDK import, no wire format appears here or in any
caller — a backend is the only place that knows which model is on the other end.

Adding a provider is one new module implementing `AgentBackend` plus one line in
`agent/__init__.py`. Nothing else changes.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentRequest:
    """One unit of work for a model. Provider-neutral by construction.

    A backend maps these onto whatever its provider calls them, and ignores what
    it cannot express — `unsupported` on the result says what was dropped, so a
    caller is never silently given less than it asked for.
    """

    prompt: str
    cwd: str
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    # Tool names are given in the neutral vocabulary below; a backend translates.
    allowed_tools: Optional[List[str]] = None
    max_turns: Optional[int] = None
    # "read-only" | "edit" | "full" — intent, not a provider's permission enum.
    autonomy: str = "edit"
    # Load the project's own conventions (CLAUDE.md, AGENTS.md and the like).
    load_project_context: bool = True
    # Continue an earlier call rather than start one: an opaque token from that
    # call's `AgentResult.resume_token`. A backend that cannot continue says so
    # in `unsupported` rather than silently starting over.
    resume: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """What came back. `structured` is the contract the orchestrator actually uses;
    everything else is telemetry or diagnosis."""

    text: str = ""
    structured: Optional[Dict[str, Any]] = None
    ok: bool = True
    error: Optional[str] = None

    backend: str = ""
    model: Optional[str] = None
    turns: Optional[int] = None
    # Why the model stopped: "complete", "max_turns", or None when the provider
    # did not say. Hitting a ceiling is not a failure — `ok` stays True and the
    # caller decides whether to continue — so the two are reported separately.
    stop_reason: Optional[str] = None
    # An opaque handle for continuing this call, when the provider offers one.
    resume_token: Optional[str] = None
    duration_s: Optional[float] = None
    # Fields of the request this backend could not honour.
    unsupported: List[str] = field(default_factory=list)
    # Tokens and cost the provider reported for the call, as {input, output,
    # cache_read, cache_write, cost_usd}; None when it reports none.
    usage: Optional[Dict[str, Any]] = None
    # Tools the provider's harness refused mid-run. In an unattended run these
    # separate "did the work" from "quietly did less"; a backend that cannot
    # report them leaves the list empty, which is not proof none occurred.
    denied_tools: List[str] = field(default_factory=list)

    def summary(self):
        """One line for the console. What a backend could not report is omitted
        rather than faked."""
        bits = [self.backend]
        if self.model:
            bits.append(self.model)
        if self.turns is not None:
            bits.append("%d turn%s" % (self.turns, "" if self.turns == 1 else "s"))
        if self.duration_s is not None:
            bits.append("%.1fs" % self.duration_s)
        if self.usage:
            bits.append(usage_summary(self.usage))
        return " · ".join(bits)


class AgentBackend(ABC):
    """A provider. Construct cheaply; do the work in `run`."""

    name = "unnamed"

    def resume_command(self, token, cwd):
        """A shell command a human can run to continue this session by hand, or
        None. Unattended work sometimes needs a person to take the conversation
        over; a backend whose provider has no interactive form says so by leaving
        this alone rather than printing a command that does not work."""
        return None

    @abstractmethod
    def run(self, request):
        """Execute the request. Must return an AgentResult even on failure —
        signal problems with ok=False and a populated `error`, never by raising."""

    def available(self):
        """(usable, reason). Reason explains how to fix it when usable is False."""
        return True, ""


# --- shared helpers ---------------------------------------------------------

USAGE_KEYS = ("input", "output", "cache_read", "cache_write")


def usage_from(tokens, cost=None):
    """The neutral usage record from a provider's token counts (the Anthropic
    names: input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens). None when there is nothing in it."""
    if not isinstance(tokens, dict):
        return None
    names = {"input": "input_tokens", "output": "output_tokens",
             "cache_read": "cache_read_input_tokens", "cache_write": "cache_creation_input_tokens"}
    out = {k: int(tokens.get(v) or 0) for k, v in names.items()}
    if cost is not None:
        out["cost_usd"] = float(cost)
    return out if any(out.values()) else None


def tokens_text(n):
    """A token count the way a person reads it: 940, 12.4k, 1.24M."""
    if n < 1000:
        return "%d" % n
    if n < 1000000:
        return "%.1fk" % (n / 1000.0)
    return "%.2fM" % (n / 1000000.0)


def usage_summary(usage):
    """One phrase for a usage record: all the tokens a call or a task went
    through, and what they would cost at list price."""
    total = sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
    text = "%s tokens" % tokens_text(total)
    if usage.get("cost_usd"):
        text += " · ≈$%.2f" % usage["cost_usd"]
    return text
#
# Result parsing is identical whatever produced the text, so it lives here rather
# than being re-implemented per backend.

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def extract_last_json_block(text):
    """Last fenced JSON object in the text, parsed. None if there isn't one."""
    if not isinstance(text, str):
        return None
    for body in reversed(_FENCE_RE.findall(text)):
        try:
            parsed = json.loads(body)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# Neutral tool vocabulary. A backend maps these onto its provider's names and
# reports anything it cannot offer via AgentResult.unsupported.
TOOLS_READ_ONLY = ["read_file", "list_files", "search"]
TOOLS_EDIT = TOOLS_READ_ONLY + ["write_file", "edit_file"]
TOOLS_FULL = TOOLS_EDIT + ["run_command"]


def tools_for(autonomy):
    return {
        "read-only": TOOLS_READ_ONLY,
        "edit": TOOLS_EDIT,
        "full": TOOLS_FULL,
    }.get(autonomy, TOOLS_EDIT)
