"""Claude CLI backend — `claude -p` as a subprocess.

Kept alongside the SDK backend so the two can be compared head to head on the same
task: same prologue, same prompt, same repo, different transport. It is also the
fallback when `claude-agent-sdk` is not installed.

The CLI's JSON envelope reports the turn count, but its shape is not contractual,
so anything missing is left None rather than guessed at.
"""

import json
import shlex
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


# The envelope's `subtype`, in the seam's vocabulary. Anything not listed is left
# unknown rather than guessed at.
STOP_REASONS = {
    "success": "complete",
    "error_max_turns": "max_turns",
}


def _envelope_error(envelope):
    errors = envelope.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(e) for e in errors)
    return envelope.get("subtype") or "the provider reported an error"


def parse_envelope(raw):
    """Unwrap `claude --output-format json`. Returns (text, telemetry).

    The assistant's text sits under "result"; the structured block the caller
    asked for is fenced inside that text. Output that is not an envelope is
    returned as-is, which is what a non-JSON or truncated run produces. The
    envelope's shape is not contractual, so a missing field is left absent
    rather than guessed at.

    Telemetry carries `ok`/`error` when the envelope reports a failure, because
    it reports ones the exit code does not. The turn ceiling is the exception:
    the envelope calls it an error, but it is a checkpoint — partial work with a
    session to continue from — so it comes back as `stop_reason` with `ok` left
    alone, and the caller decides whether to resume.
    """
    try:
        envelope = json.loads(raw)
    except ValueError:
        return raw, {}
    if not isinstance(envelope, dict):
        return raw, {}

    text = envelope["result"] if isinstance(envelope.get("result"), str) else raw
    stop_reason = STOP_REASONS.get(envelope.get("subtype"))
    if stop_reason is None and envelope.get("terminal_reason") == "max_turns":
        stop_reason = "max_turns"

    telemetry = {
        "turns": envelope.get("num_turns"),
        "stop_reason": stop_reason,
        # The handle `--resume` takes. Present on a finished run too, which is
        # what makes a follow-up call possible at all.
        "resume_token": envelope.get("session_id"),
    }
    if envelope.get("is_error") and stop_reason != "max_turns":
        telemetry["ok"] = False
        telemetry["error"] = _envelope_error(envelope)
    return text, telemetry


def build_command(request):
    """The provider's command line for one request. Returns (cmd, unsupported).

    Separate from `run` so the flag mapping can be read and tested without a
    subprocess — it is the whole of what this backend translates.
    """
    # `extra["argv"]` hands the command to the operator wholesale — the escape
    # hatch for a run that stalls on a permission mode or a flag this backend
    # does not derive. Anything it supersedes is reported rather than assumed.
    override = (request.extra or {}).get("argv")
    if override:
        cmd = shlex.split(override) if isinstance(override, str) else list(override)
        cmd += ["--add-dir", request.cwd]
        unsupported = ["%s (superseded by extra[argv])" % field
                       for field, value in (("model", request.model),
                                            ("autonomy", request.autonomy),
                                            ("allowed_tools", request.allowed_tools),
                                            ("max_turns", request.max_turns),
                                            ("resume", request.resume))
                       if value is not None]
        return cmd, unsupported

    unsupported = []
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", request.model or DEFAULT_MODEL,
        "--permission-mode", AUTONOMY_MAP.get(request.autonomy, "acceptEdits"),
        # Skills and MCP servers are noise for a single prepared prompt.
        "--disable-slash-commands",
        "--strict-mcp-config",
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
    # Sessions are left on disk deliberately: a call stopped by the ceiling is
    # continued with `--resume`, which needs the session that produced it.
    if request.resume:
        cmd += ["--resume", request.resume]
    return cmd, unsupported


class ClaudeCLIBackend(AgentBackend):
    name = "claude-cli"

    def available(self):
        if shutil.which("claude") is None:
            return False, "the `claude` CLI is not on PATH"
        return True, ""

    def resume_command(self, token, cwd):
        return "cd %s && claude --resume %s" % (shlex.quote(cwd), shlex.quote(token))

    def run(self, request):
        usable, reason = self.available()
        if not usable:
            return AgentResult(ok=False, error=reason, backend=self.name)

        model = request.model or DEFAULT_MODEL
        cmd, unsupported = build_command(request)
        if request.system_prompt:
            cmd += ["--append-system-prompt", request.system_prompt]
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
        text, telemetry = parse_envelope(raw)
        result = AgentResult(backend=self.name, model=model,
                             unsupported=unsupported,
                             duration_s=time.time() - started)
        for field, value in telemetry.items():
            setattr(result, field, value)
        result.text = text
        result.structured = extract_last_json_block(text)

        # The envelope is parsed before the exit code is judged, because the two
        # disagree: a run stopped by the ceiling exits non-zero and is not a
        # failure. Only an exit the envelope left unexplained falls through to
        # stderr, which is the only place such a run says anything at all.
        if proc.returncode != 0 and result.ok and result.stop_reason is None:
            result.ok = False
            result.error = (proc.stderr.decode("utf-8", "replace").strip()
                            or "claude exited %d" % proc.returncode)
            result.text = raw
        return result
