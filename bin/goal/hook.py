#!/usr/bin/env python3
#
# hook.py — Claude Code hooks for a goal's calls.
#
#   hook.py bash [lead]     # refuses a push, a CI run, or a change to the PR; for
#                           # the lead, also a sleep: sub-agents' reports come by themselves
#   hook.py agent <model>   # a sub-agent started without a model gets <model>
#   hook.py fence <text>... # refuses any tool call that names one of the texts
#   hook.py task            # refuses a coding task a whole-project check or an install
#   hook.py readonly <dir>  # refuses any change to the code in <dir>: an explorer
#   hook.py discuss         # refuses a goal's discussion any change outside the temp
#                           # folders: it writes and runs scratch files there only
#   hook.py delegate <dir>  # refuses the lead, not its sub-agents, a change to the
#                           # code in <dir>, or reading it: in the build, sub-agents
#                           # write it and explorers read it
#
# Each reads the tool call as JSON on stdin. Exit 2 refuses the call, and what is
# on stderr reaches the model.

import json
import os
import re
import sys
import tempfile

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
DELEGATE = ("Refused: in the build you coordinate, and sub-agents write the code. Start a "
            "sub-agent with the Agent tool and a brief for this change: what to change, where, "
            "and how to test it. You can still run git, commit, and edit your journal and the "
            "technical plan.")
EXPLORE = ("Refused: in the build, explorers read the code for you. Every file you read stays "
           "in your context and is paid for again on every later turn. Start an Explore "
           "sub-agent with one narrow question, such as where something is handled or what "
           "a function returns, and ask for a short answer: the files, the lines and the "
           "facts. You can read your journal, the technical plan and Markdown documents, "
           "and run git.")
READONLY = ("Refused: you answer a question about the code, and change nothing. Read what "
            "you need, then answer.")
CHECKS = ("Refused: in the build you do not run tests, type checks, linters or builds. Tests "
          "guide the coding tasks while they code: each runs the tests of its own change. The "
          "checker and CI check the rest. To know whether a task's work is right, read its "
          "report, or hand over a reviewer task.")
# Commands that test, type-check, lint or build: the runner and CI do those in the build.
CHECKERS = re.compile(r"(?:^|[;&|(`]\s*|\s)(?:vitest|jest|pytest|tsc|eslint|ruff|mypy|playwright|"
                      r"npm\s+(?:run|test|exec)|npx|yarn|pnpm|make|uv\s+run|cargo\s+test|go\s+test)\b")
TASK_CHECKS = ("Refused: a coding task runs no check of the whole project, and installs "
               "nothing, whatever its brief says. Run the linter and the tests of the files you "
               "changed, by their paths. When a tool is missing, say so in your notes. The "
               "runner runs CI's static checks for the whole project after you.")
# What a coding task may not run: whole-project checks, installs, whole suites.
WHOLE = re.compile(
    r"(?:^|[;&|(`]\s*|\s)(?:tsc\b(?![^;&|]*\.tsx?\b)|npm\s+(?:ci|install|i)\b|"
    r"npm\s+(?:run\s+)?(?:typecheck|verify[\w:-]*|ci-verify|build|test|lint)\b|"
    r"npx\s+(?:--no-install\s+)?vitest\s+run\s*(?:$|[;&|])|"
    r"make\s+(?!-)[\w-]+|\S*setup-worktree\S*|uv\s+sync\b|pnpm\s+install|yarn\s+install)")
READS = ("Read", "Grep", "Glob")
# Shell commands that read code: the lead asks an explorer instead. git is not one, and
# a filter after a pipe reads only the output before it.
READERS = re.compile(r"(?:^|[;&(`]\s*)(?:cat|head|tail|less|more|grep|rg|ag|sed|awk|find|tree|wc)\b")
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# Shell commands that change files: a redirect into a file, in-place edits, patches.
WRITES = (
    re.compile(r"(?<![0-9&<>])>{1,2}(?!&)\s*(?!/dev/null\b|/tmp/|&)[^\s|;&]"),
    re.compile(r"\b(?:sed|perl)\s+(?:-\w+\s+)*-\w*i"),
    re.compile(r"\btee\b"),
    re.compile(r"\b(?:git\s+apply|patch)\b"),
)
WAIT = ("Refused: do not wait for a sub-agent with sleep or a loop. Its report reaches you by "
        "itself, as a message, the moment it finishes. Start every sub-agent whose work does "
        "not depend on another now, and do other work meanwhile. When nothing is left to do "
        "until a report arrives, end your reply with one short line, such as \"I wait for "
        "the reports\". You continue when the next report arrives.")
SLEEP = re.compile(r"(?:^|[;&|(`\s])sleep\s")
CORTEX = re.compile(r"(?:^|[;&|(`\s])cortex(?:\s|$)")


DISCUSS = ("Refused: in a discussion you change nothing in the repository, the goal's files "
           "or Asana. You may write and run scratch files in a temp folder: %s.")
# Shell commands that change files or the repository, beyond WRITES.
CHANGES = re.compile(r"(?:^|[;&|(`]\s*)(?:rm|mv|cp|mkdir|touch|ln|rmdir|chmod|install|npm|npx|pnpm|yarn|uv|pip)\b|"
                     r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|checkout|switch|stash|reset|merge|rebase|"
                     r"cherry-pick|revert|push|pull|am|apply|clean|rm|mv|add|restore|tag|branch|worktree|"
                     r"fetch|init|clone)\b")


def temp_roots():
    roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp")}
    if os.environ.get("TMPDIR"):
        roots.add(os.path.realpath(os.environ["TMPDIR"]))
    return sorted(roots)


def in_temp(path):
    return any(inside(path, r) for r in temp_roots())


def only_temp(command):
    """Whether every path a shell command names is in a temp folder."""
    paths = re.findall(r"(?<![\w.-])(/[^\s'\"|;&()<>]+)", command)
    words = [w for w in re.split(r"[\s|;&()<>]+", command) if w and not w.startswith("-")]
    relative = [w for w in words if not w.startswith(("/", "$", "~")) and (
        "/" in w or os.path.exists(w))]
    return bool(paths) and not relative and all(in_temp(p) for p in paths)


def discussed(call):
    """Whether a discussion's tool call changes something outside the temp folders."""
    tool, tool_input = call.get("tool_name"), call.get("tool_input") or {}
    if tool in EDITS:
        return not in_temp(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if tool == "Bash":
        raw = tool_input.get("command") or ""
        command = re.sub(r"'[^']*'|\"[^\"]*\"", "''", raw)
        if any(p.search(command) for p in WRITES[1:]) or CHANGES.search(command) or re.search(
                r"(?<![0-9&<>])>{1,2}(?!&)\s*(?!/dev/null\b)[^\s|;&]", command):
            return not only_temp(raw)
    return False


def blocked(command):
    return any(p.search(command or "") for p in BLOCKED)


def fenced(tool_input, texts):
    """Whether a tool call names a fenced text, anywhere in its input. `cortex`
    alone fences off running the cortex command."""
    flat = json.dumps(tool_input)
    if "cortex" in texts and CORTEX.search(str(tool_input.get("command") or "")):
        return True
    return any(t in flat for t in texts if t != "cortex")


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def outside(command, root):
    """Whether a shell command names files, all by absolute path outside `root`: its
    own saved tool output, the goal's state. A relative path is in the worktree."""
    paths = re.findall(r"(?<![\w.-])(/[^\s'\"|;&()<>]+)", command)
    words = [w for w in re.split(r"[\s|;&()]+", command) if w and not w.startswith("-")]
    relative = [w for w in words if not w.startswith(("/", "$", "~")) and (
        "/" in w or os.path.exists(os.path.join(root, w)))]
    return bool(paths) and not relative and not any(inside(p, root) for p in paths)


def delegated(call, root):
    """What the lead itself, not a sub-agent, may not do to the code under `root`:
    DELEGATE for a change, EXPLORE for a read of anything but Markdown, else None.
    A sub-agent's call carries its `agent_type`."""
    if call.get("agent_type"):
        return None
    tool, tool_input = call.get("tool_name"), call.get("tool_input") or {}
    if tool in EDITS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return DELEGATE if inside(path, root) else None
    if tool in READS:
        path = tool_input.get("file_path") or tool_input.get("path") or os.getcwd()
        if tool == "Read" and path.endswith(".md"):
            return None
        return EXPLORE if inside(path, root) else None
    if tool == "Bash":
        # What is quoted is text, such as a commit message, not a redirect.
        command = re.sub(r"'[^']*'|\"[^\"]*\"", "''", tool_input.get("command") or "")
        if any(p.search(command) for p in WRITES):
            return DELEGATE
        if CHECKERS.search(command):
            return CHECKS
        if READERS.search(command.strip()) and not re.search(r"\.md\b", tool_input.get("command") or "") \
                and not outside(tool_input.get("command") or "", root):
            return EXPLORE
    return None


def main(argv):
    try:
        call = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = call.get("tool_input") or {}
    if argv[:1] == ["bash"] and blocked(tool_input.get("command")):
        sys.stderr.write(REFUSED + "\n")
        return 2
    if argv[:1] == ["bash"] and len(argv) > 1 and argv[1] == "lead" and not call.get("agent_type") \
            and SLEEP.search(tool_input.get("command") or ""):
        sys.stderr.write(WAIT + "\n")
        return 2
    if argv[:1] == ["fence"] and fenced(tool_input, argv[1:]):
        sys.stderr.write(FENCED + "\n")
        return 2
    if argv[:1] == ["task"] and call.get("tool_name") == "Bash" and WHOLE.search(
            re.sub(r"'[^']*'|\"[^\"]*\"", "''", tool_input.get("command") or "")):
        sys.stderr.write(TASK_CHECKS + "\n")
        return 2
    if argv[:1] == ["discuss"] and discussed(call):
        sys.stderr.write(DISCUSS % ", ".join("`%s`" % r for r in temp_roots()) + "\n")
        return 2
    if argv[:1] == ["readonly"] and len(argv) > 1 and delegated(call, argv[1]) == DELEGATE:
        sys.stderr.write(READONLY + "\n")
        return 2
    refusal = delegated(call, argv[1]) if argv[:1] == ["delegate"] and len(argv) > 1 else None
    if refusal:
        sys.stderr.write(refusal + "\n")
        return 2
    if argv[:1] == ["agent"] and len(argv) > 1 and not tool_input.get("model"):
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "updatedInput": dict(tool_input, model=argv[1])}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
