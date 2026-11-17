#!/usr/bin/env python3
#
# queue.py — start goals from the command line, as the TUI does.
#
#   cond queue add ["<prompt>"] [-f FILE]... [--into BRANCH]   # a goal on the prompt
#   cond queue undo <goal>...                                    # discard each goal, PR and branch
#   cond queue list
#
# The prompt is what to build: text, Asana ticket links, or both. Without it, or
# with -, it is read from stdin. Without --into, the PR goes into the TUI's Queue
# into branch, else main.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Run as a script, this directory comes first on the path, and this file would
# stand in for the standard library's `queue`.
if sys.path and os.path.abspath(sys.path[0] or ".") == HERE:
    sys.path.pop(0)

import argparse  # noqa: E402

BIN = os.path.dirname(HERE)
for tool in ("tui", "serve", "goal", "lib"):
    sys.path.insert(0, os.path.join(BIN, tool))
import control as dm  # noqa: E402
import core as st  # noqa: E402
import goal as gl  # noqa: E402


def into(main_root, branch):
    return branch or dm.read_control(main_root).get("base")


def add(main_root, prompt, files=(), branch=None):
    """Start a goal on the prompt and the files given with it."""
    base = into(main_root, branch)
    goal_id = gl.create(main_root, prompt, [os.path.abspath(f) for f in files], base=base,
                        **gl.settings_from(dm.read_control(main_root)))
    gl.launch(main_root, goal_id)
    return ["started the goal %s on %s" % (goal_id, base or "main")]


def undo(main_root, ids):
    """Undo each goal, all of it."""
    known = {g["id"] for g in gl.list_goals(main_root) if not g.get("parent")}
    out = []
    for gid in ids:
        if gid not in known:
            out.append("%s: no goal to undo" % gid)
            continue
        out.append("%s: undone — %s" % (gid, "; ".join(gl.undo(main_root, gid))))
    return out


def main(argv):
    parser = argparse.ArgumentParser(prog="cond queue", description=(
        "Start goals from a prompt, as the TUI does."))
    parser.add_argument("--repo", default=os.getcwd(), help="target repository (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="start a goal on a prompt")
    p.add_argument("prompt", nargs="?", default="-",
                   help="what to build: text, Asana ticket links, or both; - (the default) "
                        "reads it from stdin")
    p.add_argument("-f", "--file", action="append", default=[], dest="files",
                   help="a file to give with the prompt, such as an image; repeat for more")
    p.add_argument("--into", help="the branch the PR goes into (default: the TUI's Queue into, "
                                  "else main)")
    p = sub.add_parser("undo", help="discard each goal: its PR, branch and worktree")
    p.add_argument("goals", nargs="+", help="goal ids, as `cond queue list` shows them")
    sub.add_parser("list", help="print the goals")
    args = parser.parse_args(argv)
    try:
        main_root = st.main_repo_root(os.path.abspath(args.repo))
        if args.cmd == "list":
            import actions
            import tui
            print("\n".join(tui.status_lines(actions.goals(main_root))))
            return 0
        if args.cmd == "add":
            prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
            lines = add(main_root, prompt, args.files, args.into)
        else:
            lines = undo(main_root, args.goals)
    except st.Failure as e:
        sys.stderr.write("queue: %s\n" % e)
        return 1
    sys.stdout.write("".join("%s\n" % line for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
