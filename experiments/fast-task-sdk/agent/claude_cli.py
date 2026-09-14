"""Claude CLI backend — `claude -p` as a subprocess.

Kept alongside the SDK backend so the two can be compared head to head on the same
task: same prologue, same prompt, same repo, different transport. It is also the
fallback when `claude-agent-sdk` is not installed.

Its telemetry is thinner than the SDK's: the CLI's JSON envelope carries cost and
turns but the shape is not contractual, so anything missing is left None rather
than guessed at.
"""

import json
import shutil
import subprocess
import time

from .base import AgentBackend, AgentResult, extract_last_json_block

TOOL_MAP = {
    "read_file": "Read",
    "list_files": "Glob",
    "search": "Grep",
    "write_file": "Write",
    "edit_file": "Edit",
    "run_command": "Bash",
}

AUTONOMY_MAP = {
    "read-only": "plan",
    "edit": "acceptEdits",
    "full": "bypassPermissions",
}

DEFAULT_MODEL = "claude-opus-5"


class ClaudeCLIBackend(AgentBackend):
    name = "claude-cli"

    def available(self):
        if shutil.which("claude") is None:
            return False, "the `claude` CLI is not on PATH"
        return True, ""

    def run(self, request):
        usable, reason = self.available()
        if not usable:
            return AgentResult(ok=False, error=reason, backend=self.name)

        unsupported = []
        model = request.model or DEFAULT_MODEL
        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--model", model,
            "--permission-mode", AUTONOMY_MAP.get(request.autonomy, "acceptEdits"),
            # Skills and MCP servers are noise for a single prepared prompt.
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--add-dir", request.cwd,
        ]
        if request.allowed_tools is not None:
            mapped = [TOOL_MAP[t] for t in request.allowed_tools if t in TOOL_MAP]
            unsupported += ["tool:%s" % t for t in request.allowed_tools
                            if t not in TOOL_MAP]
            if mapped:
                cmd += ["--allowed-tools"] + mapped
        if request.max_turns is not None:
            cmd += ["--max-turns", str(request.max_turns)]
        if request.system_prompt:
            cmd += ["--append-system-prompt", request.system_prompt]
        if request.max_budget_usd is not None:
            # No CLI equivalent — the caller must not assume it was enforced.
            unsupported.append("max_budget_usd")
        if not request.load_project_context:
            unsupported.append("load_project_context=False")

        started = time.time()
        try:
            proc = subprocess.run(cmd + [request.prompt], cwd=request.cwd,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            return AgentResult(ok=False, backend=self.name, model=model,
                               error="could not run claude: %s" % e,
                               duration_s=time.time() - started)

        raw = proc.stdout.decode("utf-8", "replace")
        result = AgentResult(backend=self.name, model=model,
                             unsupported=unsupported,
                             duration_s=time.time() - started)
        if proc.returncode != 0:
            result.ok = False
            result.error = (proc.stderr.decode("utf-8", "replace").strip()
                            or "claude exited %d" % proc.returncode)
            result.text = raw
            return result

        text = raw
        envelope = None
        try:
            envelope = json.loads(raw)
        except ValueError:
            pass
        if isinstance(envelope, dict):
            if isinstance(envelope.get("result"), str):
                text = envelope["result"]
            result.cost_usd = envelope.get("total_cost_usd")
            result.turns = envelope.get("num_turns")
            usage = envelope.get("usage")
            if isinstance(usage, dict):
                result.input_tokens = usage.get("input_tokens")
                result.output_tokens = usage.get("output_tokens")
                result.cached_tokens = usage.get("cache_read_input_tokens")

        result.text = text
        result.structured = extract_last_json_block(text)
        return result
