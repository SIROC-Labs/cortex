#!/usr/bin/env python3
#
# queue.py — queue Asana tasks, milestones and goals from the command line, as the TUI does.
#
# Any agent or script on this machine can use it: it changes the same control
# file the TUI changes, and this repo's daemon picks the change up the same way.
#
#   cortex queue add <task>... [--into BRANCH] [--checkpoint]   # a milestone queues its open subtasks
#   cortex queue remove <task>...
#   cortex queue goal <task> [--into BRANCH]                     # run the ticket as a goal
#   cortex queue list
#
# <task> is an Asana task URL or gid. Without --into, work goes into the TUI's
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
for tool in ("tui", "goal"):
    sys.path.insert(0, os.path.join(BIN, tool))
import daemon as dm  # noqa: E402
import goal as gl  # noqa: E402
from daemon import st  # noqa: E402

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


def queue_items(task, board, subtasks=()):
    """What queueing a task adds: the task itself, or a milestone's open subtasks."""
    if task.get("kind") == "milestone":
        return [{"gid": t["ref"], "board": board, "name": t.get("name")}
                for t in subtasks if not t.get("completed")]
    if task.get("completed"):
        return []
    return [{"gid": task["ref"], "board": board, "name": task.get("name")}]


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


def daemon_note(main_root):
    notes = []
    if not dm.daemon_info(main_root)[1]:
        notes.append("this repo's daemon is not running — nothing starts until it is "
                     "(open the TUI, or `cortex tui` and press s on the Daemons tab)")
    if not dm.read_control(main_root).get("sprint"):
        notes.append("no sprint is picked — pick one in the TUI (Setup, tab 3) before tasks start")
    return notes


def add(main_root, refs, branch=None, checkpoint=False):
    base = into(main_root, branch)
    items, out = [], []
    for ref in refs:
        task, gid = fetch(main_root, ref)
        subtasks = (st.asana(["task", "subtasks", gid], cwd=main_root) or []
                    if task.get("kind") == "milestone" else [])
        found = queue_items(task, board_of(task, ref), subtasks)
        if not found:
            out.append("%s: nothing to queue — %s" % (label(task), "no open subtasks"
                       if task.get("kind") == "milestone" else "it is complete"))
        items += [dict(i, base=base) for i in found]

    def change(control):
        added = dm.queue_add(control, items)
        if checkpoint:
            for gid in added:
                dm.set_checkpoint(control, gid, True)
        return added

    with dm.control_file(main_root) as control:
        added = change(control)
    for item in items:
        out.append("%s %s" % ("queued" if item["gid"] in added else "already queued:",
                              item["name"]))
    if added:
        out.append("into %s" % (base or "the default branch"))
        out += daemon_note(main_root)
    return out


def remove(main_root, refs):
    gids = [str(st.asana(["ref", "parse", ref], cwd=main_root) or ref).strip() for ref in refs]
    with dm.control_file(main_root) as control:
        queued = {q["gid"]: q.get("name") for q in control["queue"]}
        dm.queue_remove(control, gids, keep_checkpoints=True)
    return ["unqueued %s" % queued[g] if g in queued else "not queued: %s" % g for g in gids] + (
        ["a run already going is left to finish — x on the TUI's Runs tab stops it"]
        if any(g in queued for g in gids) else [])


def goal(main_root, ref, branch=None):
    task, gid = fetch(main_root, ref)
    existing = gl.find_goal(main_root, gid)
    if existing:
        return ["%s is already the goal %s" % (label(task), existing["id"])]
    base = into(main_root, branch)
    goal_id = gl.create(main_root, gid, st.task_key(task), task.get("name"),
                        url=gl.task_url(gid, board_of(task, ref)), base=base)
    gl.launch(main_root, goal_id)
    return ["started the goal %s on %s — it is on the TUI's Runs tab"
            % (goal_id, base or "the default branch")]


def main(argv):
    parser = argparse.ArgumentParser(prog="cortex queue", description=(
        "Queue Asana tasks, milestones and goals for this repo's daemon, as the TUI does. "
        "A task is its Asana URL or gid."))
    parser.add_argument("--repo", default=os.getcwd(), help="target repository (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="queue tasks; a milestone queues its open subtasks")
    p.add_argument("tasks", nargs="+")
    p.add_argument("--into", help="the branch the work goes into (default: the TUI's Queue into)")
    p.add_argument("--checkpoint", action="store_true",
                   help="hold the work that follows until these are merged")
    p = sub.add_parser("remove", help="take tasks off the queue")
    p.add_argument("tasks", nargs="+")
    p = sub.add_parser("goal", help="run a task or milestone as a goal, by itself, into one PR")
    p.add_argument("task")
    p.add_argument("--into", help="the branch the PR goes into (default: the TUI's Queue into)")
    sub.add_parser("list", help="print the goals, the queue and the daemon")
    args = parser.parse_args(argv)
    try:
        main_root = st.main_repo_root(os.path.abspath(args.repo))
        if args.cmd == "list":
            import tui
            tui.print_status(main_root)
            return 0
        lines = {"add": lambda: add(main_root, args.tasks, args.into, args.checkpoint),
                 "remove": lambda: remove(main_root, args.tasks),
                 "goal": lambda: goal(main_root, args.task, args.into)}[args.cmd]()
    except st.Failure as e:
        sys.stderr.write("queue: %s\n" % e)
        return 1
    sys.stdout.write("".join("%s\n" % line for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
