#!/usr/bin/env python3
#
# queue.py — start goals on Asana tickets from the command line, as the TUI does.
#
#   cond queue add <ticket>... [--into BRANCH]   # a goal on each ticket; a milestone is one goal
#   cond queue undo <ticket>...                  # discard each ticket's goal, PR and branch
#   cond queue list
#
# <ticket> is an Asana task URL or gid. Without --into, the PR goes into the TUI's
# Queue into branch.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Run as a script, this directory comes first on the path, and this file would
# stand in for the standard library's `queue`.
if sys.path and os.path.abspath(sys.path[0] or ".") == HERE:
    sys.path.pop(0)

import argparse  # noqa: E402
import re  # noqa: E402

BIN = os.path.dirname(HERE)
for tool in ("tui", "goal", "lib"):
    sys.path.insert(0, os.path.join(BIN, tool))
import control as dm  # noqa: E402
import core as st  # noqa: E402
import goal as gl  # noqa: E402

_URL_PROJECT = re.compile(r"/project/(\d+)/|app\.asana\.com/0/(\d+)/\d+")


# --- pure helpers (unit-tested) ----------------------------------------------

def board_of(task, url=None):
    """The board a task is queued from: the project in its URL, else its first
    project."""
    m = _URL_PROJECT.search(url or "")
    if m and (m.group(1) or m.group(2)) != "0":
        return m.group(1) or m.group(2)
    return next((b.get("project_gid") for b in task.get("board") or [] if b.get("project_gid")),
                None)


def label(task):
    return " ".join(x for x in (task.get("task_id"), task.get("name")) if x)


# --- commands -----------------------------------------------------------------

def fetch(main_root, ref):
    gid = st.asana(["ref", "parse", ref], cwd=main_root)
    if not gid:
        raise st.Failure("%r is not an Asana task" % ref)
    gid = str(gid).strip()
    return st.asana(["task", "get", gid], cwd=main_root), gid


def into(main_root, branch):
    return branch or dm.read_control(main_root).get("base")


def add(main_root, refs, branch=None):
    """Start a goal for each ticket. A ticket that is already a goal starts nothing."""
    base, out = into(main_root, branch), []
    for ref in refs:
        task, gid = fetch(main_root, ref)
        existing = gl.find_goal(main_root, gid)
        if existing:
            out.append("%s is already the goal %s" % (label(task), existing["id"]))
            continue
        goal_id = gl.create(main_root, gid, st.task_key(task), task.get("name"),
                            url=gl.task_url(gid, board_of(task, ref)), base=base,
                            **gl.settings_from(dm.read_control(main_root)))
        gl.launch(main_root, goal_id)
        out.append("started the goal %s on %s" % (goal_id, base or "the default branch"))
    return out


def undo(main_root, refs):
    """Undo each ticket's goal, all of it."""
    out = []
    for ref in refs:
        gid = str(st.asana(["ref", "parse", ref], cwd=main_root) or ref).strip()
        existing = gl.find_goal(main_root, gid)
        if not existing:
            out.append("%s: no goal to undo" % gid)
            continue
        out.append("%s: undone — %s" % (existing["id"], "; ".join(gl.undo(main_root, existing["id"]))))
    return out


def main(argv):
    parser = argparse.ArgumentParser(prog="cond queue", description=(
        "Start goals on Asana tickets, as the TUI does. A ticket is its Asana URL or gid."))
    parser.add_argument("--repo", default=os.getcwd(), help="target repository (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="start a goal on each ticket; a milestone is one goal")
    p.add_argument("tasks", nargs="+")
    p.add_argument("--into", help="the branch the PR goes into (default: the TUI's Queue into)")
    p = sub.add_parser("undo", help="discard each ticket's goal: its PR, branch, worktree and "
                                    "the subtasks it made")
    p.add_argument("tasks", nargs="+")
    sub.add_parser("list", help="print the goals")
    args = parser.parse_args(argv)
    try:
        main_root = st.main_repo_root(os.path.abspath(args.repo))
        if args.cmd == "list":
            import tui
            tui.print_status(main_root)
            return 0
        lines = {"add": lambda: add(main_root, args.tasks, args.into),
                 "undo": lambda: undo(main_root, args.tasks)}[args.cmd]()
    except st.Failure as e:
        sys.stderr.write("queue: %s\n" % e)
        return 1
    sys.stdout.write("".join("%s\n" % line for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
