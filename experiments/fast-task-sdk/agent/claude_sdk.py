"""Claude Agent SDK backend.

The only module in this experiment that imports an Anthropic package, and the only
one that names Claude. It authenticates the same way Claude Code does, so an
existing subscription login works with no API key.

Install: pip install claude-agent-sdk
"""

import asyncio
import time

from .base import AgentBackend, AgentResult, extract_last_json_block

# Neutral tool name -> Claude Code tool name. Names the SDK has no equivalent for
# are reported as unsupported rather than silently dropped.
TOOL_MAP = {
    "read_file": "Read",
    "list_files": "Glob",
    "search": "Grep",
    "write_file": "Write",
    "edit_file": "Edit",
    "run_command": "Bash",
}

# Neutral autonomy -> the SDK's PermissionMode.
#   acceptEdits       auto-approves file edits; other tools follow settings
#   bypassPermissions skips checks entirely
AUTONOMY_MAP = {
    "read-only": "plan",
    "edit": "acceptEdits",
    "full": "bypassPermissions",
}

DEFAULT_MODEL = "claude-opus-5"


def _usage(usage, key):
    """Read a token count whether `usage` is a dict or an object."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(key)
    return getattr(usage, key, None)


def _denial_name(denial):
    """A denial's tool name, whatever shape the SDK hands back."""
    if isinstance(denial, dict):
        return denial.get("tool_name") or denial.get("name") or str(denial)
    return getattr(denial, "tool_name", None) or str(denial)


class ClaudeSDKBackend(AgentBackend):
    name = "claude-sdk"

    def available(self):
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return False, ("claude-agent-sdk is not installed — "
                           "pip install claude-agent-sdk")
        return True, ""

    def run(self, request):
        usable, reason = self.available()
        if not usable:
            return AgentResult(ok=False, error=reason, backend=self.name)
        started = time.time()
        try:
            result = asyncio.run(self._run(request))
        except Exception as e:  # the seam's contract: report, never raise
            return AgentResult(ok=False, backend=self.name,
                               error="%s: %s" % (type(e).__name__, e),
                               duration_s=time.time() - started)
        result.duration_s = time.time() - started
        return result

    async def _run(self, request):
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query,
        )

        unsupported = []
        allowed = None
        if request.allowed_tools is not None:
            allowed = [TOOL_MAP[t] for t in request.allowed_tools if t in TOOL_MAP]
            unsupported += ["tool:%s" % t for t in request.allowed_tools
                            if t not in TOOL_MAP]

        options_kwargs = {
            "cwd": request.cwd,
            "model": request.model or DEFAULT_MODEL,
            "permission_mode": AUTONOMY_MAP.get(request.autonomy, "acceptEdits"),
            # "project" loads the repo's CLAUDE.md without dragging in user-level
            # settings; an empty list loads nothing at all.
            "setting_sources": ["project"] if request.load_project_context else [],
        }
        if allowed:
            options_kwargs["allowed_tools"] = allowed
        if request.system_prompt:
            options_kwargs["system_prompt"] = request.system_prompt
        if request.max_turns is not None:
            options_kwargs["max_turns"] = request.max_turns
        if request.max_budget_usd is not None:
            options_kwargs["max_budget_usd"] = request.max_budget_usd

        options = ClaudeAgentOptions(**options_kwargs)

        chunks = []
        result = AgentResult(backend=self.name, model=options_kwargs["model"],
                             unsupported=unsupported)

        async for message in query(prompt=request.prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                result.turns = message.num_turns
                result.cost_usd = message.total_cost_usd
                # `usage` is a plain dict on this SDK (0.2.x) despite the docs
                # describing a MessageUsage dataclass — read it both ways so a
                # future shape change doesn't silently blank the telemetry.
                result.input_tokens = _usage(message.usage, "input_tokens")
                result.output_tokens = _usage(message.usage, "output_tokens")
                result.cached_tokens = _usage(
                    message.usage, "cache_read_input_tokens")

                # Tools the harness refused. In an unattended run these are the
                # difference between "did the work" and "quietly did less".
                result.denied_tools = [
                    _denial_name(d) for d in (message.permission_denials or [])]

                if message.is_error or message.subtype == "failure":
                    result.ok = False
                    result.error = "agent run failed (%s)" % (
                        message.terminal_reason or "no reason given")
                # A run stopped by the turn or budget ceiling produced partial
                # work; say so rather than presenting it as a finished result.
                elif message.terminal_reason not in (None, "end_turn"):
                    result.ok = False
                    result.error = "agent stopped early: %s" % message.terminal_reason

        result.text = "".join(chunks)
        result.structured = extract_last_json_block(result.text)
        return result
