#!/usr/bin/env python3
#
# hook.py — Claude Code hooks for a goal's calls.
#
#   hook.py bash            # refuses a push, a CI run, or a change to the PR
#   hook.py agent <model>   # a sub-agent started without a model gets <model>
#   hook.py fence <text>... # refuses any tool call that names one of the texts
#
# Each reads the tool call as JSON on stdin. Exit 2 refuses the call, and what is
# on stderr reaches the model.

import json
import re
import sys

BLOCKED = (
    re.compile(r"\bgit\b(?:\s+-[cC]\s+\S+)*\s+push\b"),
    re.compile(r"\bgh\s+pr\s+(?:ready|merge|create|close|reopen)\b"),
    re.compile(r"\bgh\s+workflow\s+run\b"),
    re.compile(r"\bgh\s+run\s+(?:rerun|cancel)\b"),
)
REFUSED = ("Refused: only the runner pushes the branch, once the lead reports done. Every "
           "push starts CI, and CI costs money. Agents do not push, start or re-run CI, "
           "or change the pull request. Commit your work and carry on.")


FENCED = ("Refused: this goal is fenced off from that path or command. Build from the "
          "ask and its references, and from this repository.")
CORTEX = re.compile(r"(?:^|[;&|(`\s])cortex(?:\s|$)")


def blocked(command):
    return any(p.search(command or "") for p in BLOCKED)


def fenced(tool_input, texts):
    """Whether a tool call names a fenced text, anywhere in its input. `cortex`
    alone fences off running the cortex command."""
    flat = json.dumps(tool_input)
    if "cortex" in texts and CORTEX.search(str(tool_input.get("command") or "")):
        return True
    return any(t in flat for t in texts if t != "cortex")


def main(argv):
    try:
        call = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = call.get("tool_input") or {}
    if argv[:1] == ["bash"] and blocked(tool_input.get("command")):
        sys.stderr.write(REFUSED + "\n")
        return 2
    if argv[:1] == ["fence"] and fenced(tool_input, argv[1:]):
        sys.stderr.write(FENCED + "\n")
        return 2
    if argv[:1] == ["agent"] and len(argv) > 1 and not tool_input.get("model"):
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "updatedInput": dict(tool_input, model=argv[1])}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
