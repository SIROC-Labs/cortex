#!/usr/bin/env python3
#
# hook.py — Claude Code hooks for a goal's calls.
#
#   hook.py bash            # refuses a push, a CI run, or a change to the PR
#   hook.py agent <model>   # a sub-agent started without a model gets <model>
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


def blocked(command):
    return any(p.search(command or "") for p in BLOCKED)


def main(argv):
    try:
        call = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = call.get("tool_input") or {}
    if argv[:1] == ["bash"] and blocked(tool_input.get("command")):
        sys.stderr.write(REFUSED + "\n")
        return 2
    if argv[:1] == ["agent"] and len(argv) > 1 and not tool_input.get("model"):
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "updatedInput": dict(tool_input, model=argv[1])}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
