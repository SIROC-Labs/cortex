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
    duration_s: Optional[float] = None
    # Fields of the request this backend could not honour.
    unsupported: List[str] = field(default_factory=list)
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
        return " · ".join(bits)


class AgentBackend(ABC):
    """A provider. Construct cheaply; do the work in `run`."""

    name = "unnamed"

    @abstractmethod
    def run(self, request):
        """Execute the request. Must return an AgentResult even on failure —
        signal problems with ok=False and a populated `error`, never by raising."""

    def available(self):
        """(usable, reason). Reason explains how to fix it when usable is False."""
        return True, ""


# --- shared helpers ---------------------------------------------------------
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
