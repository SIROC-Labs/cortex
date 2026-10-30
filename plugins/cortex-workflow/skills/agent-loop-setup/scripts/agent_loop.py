#!/usr/bin/env python3
#
# agent_loop.py — cache lifecycle and pure decisions for the agent-loop skills.
#
# One cache per provider at ~/.cortex/agent-loop/<provider>.json maps the six
# column ROLES of the agent board to concrete column refs, records the board, its
# rotation pattern, the column names (used to re-resolve refs after a rotation)
# and the repos root. This script never opens a network connection: the skills
# fetch through the task-manager seam and hand the results in on --from-json.
#
#   agent_loop.py key <provider>
#   agent_loop.py read <key>
#   agent_loop.py write <key> --from-json <path|->
#   agent_loop.py rotate <key> --from-json <path|->      # list_boards() result
#   agent_loop.py order [--user <ref>] --from-json <path|->   # {"tasks":[...],"priority_order":[...]}
#   agent_loop.py gate --from-json <path|->              # {"blockers":[...],"board":…,"columns":…,"column_names":…}
#   agent_loop.py marker --from-json <path|->            # get_comments() result
#   agent_loop.py candidates --user <ref> --for build|orphan|review --from-json <path|->
#                                                        # {"tasks":[...],"milestones":[...],"priority_order":[...]}
#   agent_loop.py aggregate --from-json <path|->         # {"subtasks":[{completed,assignee,marker}]}
#   agent_loop.py cards --from-json <path|->             # {"description":…,"row":{ref,title,repo,state,pr}}
#   agent_loop.py last-run <key> start [--kind build|review]
#   agent_loop.py last-run <key> write <outcome> [--kind build|review] [--task <ref>] [--detail <text>]
#
# Exit codes: 0 ok · 2 no match (rotate found no board for the pattern) · 4 cache
# missing or invalid (run agent-loop-setup) · 1 argument/parse error.

import datetime
import json
import os
import re
import sys

PROG = "agent_loop.py"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cortex", "agent-loop")
ROLES = ("queue", "in_progress", "blocked", "in_review", "ready", "done")
DEFAULT_COLUMN_NAMES = {
    "queue": "Queue",
    "in_progress": "In Progress",
    "blocked": "Blocked",
    "in_review": "In Review",
    "ready": "Ready",
    "done": "Done",
}
# Roles a blocker may sit in for the dependency gate to pass. A card in in_review has
# an open PR whose work is not yet on its base branch, so it does not satisfy a dependent.
SATISFIED_ROLES = ("ready", "done")
# One last-run record per kind of tick: the build tick and the review tick run independently.
RUN_KINDS = ("build", "review")
# The 🤖 comment first lines that name a step, longest prefix first, and the step
# each names. A 🤖 comment matching none of them names no step and is skipped.
MARKERS = (
    ("🤖 [AGENT] rework started", "started"),
    ("🤖 [AGENT] started", "started"),
    ("🤖 [AGENT] previous run was interrupted", "started"),
    ("🤖 [AGENT] Ready for review", "ready_for_review"),
    ("🤖 [AGENT] Needs clarification", "needs_clarification"),
    ("🤖 [AGENT] Blocked", "blocked"),
    ("🤖 [REVIEW] started", "review_started"),
    ("🤖 [REVIEW] Merged", "merged"),
    ("🤖 [REVIEW] Changes requested", "changes_requested"),
    ("🤖 [REVIEW] Blocked", "blocked"),
)
# Which milestone work items each kind of selection may take, by latest marker.
ORPHAN_MARKERS = (None, "started")
REVIEW_MARKERS = ("ready_for_review", "review_started")
CARDS_HEADER = ("Ref", "Title", "Repo", "State", "PR")


def err(msg):
    sys.stderr.write(msg + "\n")


def die(code, msg=None):
    if msg is not None:
        err(msg)
    sys.exit(code)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_path(key):
    return os.path.join(CACHE_DIR, key + ".json")


def last_run_path(key, kind="build"):
    suffix = ".last-run.json" if kind == "build" else "." + kind + ".last-run.json"
    return os.path.join(CACHE_DIR, key + suffix)


def _flag_value(args, flag):
    for i, a in enumerate(args):
        if a == flag:
            if i + 1 >= len(args):
                die(1, "%s: %s requires a value" % (PROG, flag))
            return args[i + 1]
    return None


def _load_from_json(args, flag):
    src = _flag_value(args, flag)
    if src is None:
        die(1, "%s: %s <path|-> is required" % (PROG, flag))
    try:
        text = sys.stdin.read() if src == "-" else open(src, "r", encoding="utf-8").read()
        return json.loads(text)
    except Exception as e:
        die(1, "%s: %s: cannot read JSON from '%s' (%s)" % (PROG, flag, src, e))


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(json.dumps(obj, indent=2) + "\n")


def _read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


# --- cache -------------------------------------------------------------------

# Every role maps to a distinct, non-empty column ref, and the board carries a ref.
def validate_cache(obj):
    problems = []
    if not isinstance(obj, dict):
        return ["cache is not an object"]
    board = obj.get("board")
    if not isinstance(board, dict) or not board.get("ref"):
        problems.append("board.ref is missing")
    columns = obj.get("columns")
    if not isinstance(columns, dict):
        problems.append("columns is missing")
        columns = {}
    for role in ROLES:
        if not columns.get(role):
            problems.append("columns.%s is missing" % role)
    refs = [columns.get(r) for r in ROLES if columns.get(r)]
    if len(set(refs)) != len(refs):
        problems.append("columns must map the six roles to distinct columns")
    names = obj.get("column_names")
    if not isinstance(names, dict) or any(not names.get(r) for r in ROLES):
        problems.append("column_names must name all six roles")
    rotation = obj.get("rotation")
    if rotation is not None:
        pat = rotation.get("pattern") if isinstance(rotation, dict) else None
        try:
            re.compile(pat or "")
        except re.error:
            problems.append("rotation.pattern is not a valid regex")
        if not pat:
            problems.append("rotation.pattern is missing")
    if not obj.get("repos_root"):
        problems.append("repos_root is missing")
    return problems


def read_cache(key):
    obj = _read_json(cache_path(key))
    if obj is None:
        die(4, "%s: no agent-loop cache for '%s' at %s — run agent-loop-setup" % (PROG, key, cache_path(key)))
    problems = validate_cache(obj)
    if problems:
        die(4, "%s: agent-loop cache for '%s' is invalid (%s) — run agent-loop-setup" % (PROG, key, "; ".join(problems)))
    return obj


def cmd_key(args):
    if not args or not re.fullmatch(r"[a-z0-9_-]+", args[0]):
        die(1, "usage: %s key <provider>" % PROG)
    sys.stdout.write(args[0] + "\n")


def cmd_read(args):
    if not args:
        die(1, "usage: %s read <key>" % PROG)
    sys.stdout.write(json.dumps(read_cache(args[0]), indent=2) + "\n")


def cmd_write(args):
    if not args:
        die(1, "usage: %s write <key> --from-json <path|->" % PROG)
    key = args[0]
    obj = _load_from_json(args[1:], "--from-json")
    problems = validate_cache(obj)
    if problems:
        die(1, "%s: refusing to write an invalid cache: %s" % (PROG, "; ".join(problems)))
    obj["resolved_at"] = now_iso()
    _write_json(cache_path(key), obj)
    sys.stdout.write(json.dumps(obj, indent=2) + "\n")


# --- rotation ----------------------------------------------------------------

# The pattern's numeric capture groups, as a tuple of ints, or None when the name
# does not match. Groups are compared numerically so 26/10 beats 26/9.
def numeric_groups(pattern, name):
    m = pattern.search(name or "")
    if not m:
        return None
    groups = []
    for g in m.groups():
        try:
            groups.append(int(g))
        except (TypeError, ValueError):
            groups.append(0)
    return tuple(groups)


def cmd_rotate(args):
    if not args:
        die(1, "usage: %s rotate <key> --from-json <path|->" % PROG)
    key = args[0]
    cache = read_cache(key)
    boards = _load_from_json(args[1:], "--from-json")
    if isinstance(boards, dict) and isinstance(boards.get("data"), list):
        boards = boards["data"]
    if not isinstance(boards, list):
        die(1, "%s: rotate: --from-json must be the list_boards() array" % PROG)
    current = cache["board"]
    rotation = cache.get("rotation")
    if not rotation:
        sys.stdout.write(json.dumps({"rotate": False, "board": current, "previous": current}) + "\n")
        return
    pattern = re.compile(rotation["pattern"])
    matches = []
    for b in boards:
        if not isinstance(b, dict) or b.get("archived") is True:
            continue
        groups = numeric_groups(pattern, b.get("name"))
        if groups is not None:
            matches.append((groups, {"ref": b.get("ref"), "name": b.get("name")}))
    if not matches:
        die(2, "%s: rotate: no board matches pattern %r" % (PROG, rotation["pattern"]))
    matches.sort(key=lambda t: t[0])
    newest = matches[-1][1]
    rotate = newest["ref"] != current.get("ref")
    sys.stdout.write(json.dumps({"rotate": rotate, "board": newest, "previous": current}, indent=2) + "\n")


# --- ordering ----------------------------------------------------------------

def cmd_order(args):
    payload = _load_from_json(args, "--from-json")
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        die(1, "%s: order: --from-json must be {\"tasks\": [...], \"priority_order\": [...]}" % PROG)
    order = [str(p).lower() for p in payload.get("priority_order") or []]
    unset_rank = len(order)

    def rank(task):
        p = task.get("priority")
        if p is None or str(p).strip() == "":
            return unset_rank
        try:
            return order.index(str(p).lower())
        except ValueError:
            return unset_rank

    tasks = [t for t in payload["tasks"] if isinstance(t, dict)]
    user = _flag_value(args, "--user")
    if user is not None:
        tasks = [t for t in tasks if claimable_by(t, user)]
    tasks.sort(key=lambda t: (rank(t), t.get("index", 0)))
    sys.stdout.write(json.dumps(tasks, indent=2) + "\n")


# A card is claimable when it is unassigned or assigned to this user; a card assigned
# to anyone else belongs to their run and is never touched.
def claimable_by(task, user):
    assignee = task.get("assignee")
    if assignee is None or assignee == "":
        return True
    ref = assignee.get("ref") if isinstance(assignee, dict) else assignee
    return str(ref) == str(user)


# --- dependency gate ---------------------------------------------------------

# A blocker is satisfied when it is completed, or sits in the agent board's
# ready/done column (by ref), or sits on another board in a column whose name equals
# the agent board's ready/done name. Anything else blocks: fail closed.
def blocker_reason(blocker, board_ref, columns, column_names):
    if blocker.get("completed") is True:
        return None
    satisfied_refs = {columns.get(r) for r in SATISFIED_ROLES}
    satisfied_names = {str(column_names.get(r)).lower() for r in SATISFIED_ROLES}
    memberships = [m for m in (blocker.get("memberships") or []) if isinstance(m, dict)]
    if not memberships:
        return "on no board and not completed"
    seen = []
    for m in memberships:
        b = m.get("board") if isinstance(m.get("board"), dict) else {}
        c = m.get("column") if isinstance(m.get("column"), dict) else {}
        if b.get("ref") == board_ref and c.get("ref") in satisfied_refs:
            return None
        if b.get("ref") != board_ref and str(c.get("name")).lower() in satisfied_names:
            return None
        seen.append("%s / %s" % (b.get("name") or b.get("ref"), c.get("name") or c.get("ref")))
    return "in " + "; ".join(seen)


def cmd_gate(args):
    payload = _load_from_json(args, "--from-json")
    if not isinstance(payload, dict) or not isinstance(payload.get("blockers"), list):
        die(1, "%s: gate: --from-json must carry blockers, board, columns and column_names" % PROG)
    board_ref = payload.get("board")
    columns = payload.get("columns") or {}
    column_names = payload.get("column_names") or {}
    blocking = []
    for b in payload["blockers"]:
        if not isinstance(b, dict):
            continue
        reason = blocker_reason(b, board_ref, columns, column_names)
        if reason is not None:
            blocking.append({"ref": b.get("ref"), "name": b.get("name"), "reason": reason})
    sys.stdout.write(json.dumps({"pass": not blocking, "blocking": blocking}, indent=2) + "\n")


# --- milestone work items ----------------------------------------------------
# A milestone's work items are its subtasks; their state is read in place: open and
# unassigned = waiting, open and assigned = held, completed = merged into the
# milestone branch, and the latest 🤖 marker names the step of a held one.

# Pure: the step the latest step-naming 🤖 comment names, or None. Comments are
# taken in created_at order when they carry it, else in the order given.
def latest_marker(comments):
    items = [c for c in comments or [] if isinstance(c, dict)]
    if all(c.get("created_at") for c in items):
        items.sort(key=lambda c: c.get("created_at"))
    step = None
    for c in items:
        first = (c.get("text") or "").strip().split("\n", 1)[0].strip()
        for prefix, name in MARKERS:
            if first.startswith(prefix):
                step = name
                break
    return step


def cmd_marker(args):
    comments = _load_from_json(args, "--from-json")
    if isinstance(comments, dict) and isinstance(comments.get("data"), list):
        comments = comments["data"]
    if not isinstance(comments, list):
        die(1, "%s: marker: --from-json must be the get_comments() array" % PROG)
    sys.stdout.write(json.dumps({"marker": latest_marker(comments)}) + "\n")


def _held(st):
    return st.get("completed") is not True and bool(st.get("assignee"))


# Pure: one work item {completed, assignee, marker} -> its Cards-table state.
def subtask_state(st):
    if st.get("completed") is True:
        return "merged"
    if not _held(st):
        return "waiting"
    return {
        "ready_for_review": "in review",
        "review_started": "in review",
        "merged": "in review",
        "needs_clarification": "needs clarification",
        "blocked": "blocked",
    }.get(st.get("marker"), "in progress")


# Pure: the role of the column a milestone belongs in. blocked while a held work
# item's latest marker is Needs clarification or Blocked; ready once every one is
# complete; queue while none is held (an empty milestone included); in_progress
# otherwise. A milestone never belongs in in_review.
def milestone_role(subtasks):
    items = [s for s in subtasks or [] if isinstance(s, dict)]
    if any(subtask_state(s) in ("needs clarification", "blocked") for s in items):
        return "blocked"
    if items and all(s.get("completed") is True for s in items):
        return "ready"
    if not any(_held(s) for s in items):
        return "queue"
    return "in_progress"


def cmd_aggregate(args):
    payload = _load_from_json(args, "--from-json")
    if not isinstance(payload, dict) or not isinstance(payload.get("subtasks"), list):
        die(1, "%s: aggregate: --from-json must be {\"subtasks\": [...]}" % PROG)
    sys.stdout.write(json.dumps({"role": milestone_role(payload["subtasks"])}) + "\n")


def _priority_rank(order):
    order = [str(p).lower() for p in order or []]

    def rank(item):
        p = item.get("priority")
        if p is None or str(p).strip() == "":
            return len(order)
        try:
            return order.index(str(p).lower())
        except ValueError:
            return len(order)
    return rank


# Whether a work item is open to this kind of selection by `user`.
def _selectable(st, user, kind):
    if st.get("completed") is True:
        return False
    if kind == "build":
        return not st.get("assignee")
    if kind == "orphan":
        return bool(st.get("assignee")) and claimable_by(st, user) and st.get("marker") in ORPHAN_MARKERS
    return claimable_by(st, user) and st.get("marker") in REVIEW_MARKERS


# Pure: the selection order across single tasks and milestones.
#   tasks      : single top-level cards of one column, {ref,name,index,priority,assignee}
#   milestones : Milestone-type cards, {ref,name,role,index,priority,executor,
#                subtasks:[{ref,name,created_at,completed,assignee,marker}]}
# A milestone takes part only with Executor Agent. Milestones whose role is
# in_progress come first, by priority then native order, so started milestones
# finish before new ones open. Then the column the single tasks come from: single
# tasks and role-queue milestones together, by priority then native position. A
# milestone expands in place to its selectable work items, oldest first — list
# order carries no meaning, and authoring creates them in dependency order.
# `kind`: build takes open unassigned work items; orphan takes open ones held by
# `user` whose latest marker is none or started; review takes open ones unassigned
# or held by `user` whose latest marker is Ready for review or a review start.
# Single tasks are filtered by ownership only, as `order --user` does. Each
# candidate is {ref, name, milestone: {ref,name}|null}.
def milestone_candidates(payload, user, kind):
    rank = _priority_rank(payload.get("priority_order"))

    def expand(ms):
        items = [st for st in ms.get("subtasks") or [] if isinstance(st, dict)]
        items = sorted(enumerate(items), key=lambda p: (p[1].get("created_at") or "", p[0]))
        return [{"ref": st.get("ref"), "name": st.get("name"),
                 "milestone": {"ref": ms.get("ref"), "name": ms.get("name")}}
                for _, st in items if _selectable(st, user, kind)]

    milestones = [m for m in payload.get("milestones") or []
                  if isinstance(m, dict) and str(m.get("executor") or "").lower() == "agent"]
    started = sorted((m for m in milestones if m.get("role") == "in_progress"),
                     key=lambda m: (rank(m), m.get("index", 0)))
    column = [dict(t, _single=True) for t in payload.get("tasks") or []
              if isinstance(t, dict) and claimable_by(t, user)]
    column += [m for m in milestones if m.get("role") == "queue"]
    column.sort(key=lambda t: (rank(t), t.get("index", 0)))
    out = []
    for m in started:
        out.extend(expand(m))
    for item in column:
        if item.get("_single"):
            out.append({"ref": item.get("ref"), "name": item.get("name"), "milestone": None})
        else:
            out.extend(expand(item))
    return out


def cmd_candidates(args):
    payload = _load_from_json(args, "--from-json")
    user = _flag_value(args, "--user")
    kind = _flag_value(args, "--for")
    if not isinstance(payload, dict) or user is None or kind not in ("build", "orphan", "review"):
        die(1, "usage: %s candidates --user <ref> --for build|orphan|review --from-json <path|->" % PROG)
    sys.stdout.write(json.dumps(milestone_candidates(payload, user, kind), indent=2) + "\n")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _row(values):
    return "| " + " | ".join(values) + " |"


# Pure: the milestone description with the `## Cards` table row for row["ref"]
# set. Keys the row omits keep their current value; an unknown ref appends a row;
# a description without the section gains one at the end.
def update_cards_table(description, row):
    lines = (description or "").split("\n")
    new = [str(row.get(k.lower()) or "") for k in CARDS_HEADER]
    try:
        head = next(i for i, l in enumerate(lines) if l.strip().lower() == "## cards")
    except StopIteration:
        body = (description or "").rstrip("\n")
        block = ["## Cards", _row(CARDS_HEADER), "|" + "---|" * len(CARDS_HEADER), _row(new)]
        return (body + "\n\n" if body else "") + "\n".join(block) + "\n"
    i = head + 1
    while i < len(lines) and not lines[i].strip().startswith("|"):
        if lines[i].strip().startswith("#"):
            break
        i += 1
    if i >= len(lines) or not lines[i].strip().startswith("|"):
        lines[head + 1:head + 1] = [_row(CARDS_HEADER), "|" + "---|" * len(CARDS_HEADER), _row(new)]
        return "\n".join(lines)
    end = i
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    for j in range(i + 2, end):
        cells = _cells(lines[j])
        if cells and cells[0] == str(row.get("ref")):
            cells += [""] * (len(CARDS_HEADER) - len(cells))
            merged = [new[k] if row.get(CARDS_HEADER[k].lower()) is not None else cells[k]
                      for k in range(len(CARDS_HEADER))]
            lines[j] = _row(merged)
            return "\n".join(lines)
    lines.insert(end, _row(new))
    return "\n".join(lines)


def cmd_cards(args):
    payload = _load_from_json(args, "--from-json")
    if not isinstance(payload, dict) or not isinstance(payload.get("row"), dict) or not payload["row"].get("ref"):
        die(1, "%s: cards: --from-json must be {\"description\": …, \"row\": {\"ref\": …}}" % PROG)
    sys.stdout.write(update_cards_table(payload.get("description"), payload["row"]))


# --- last run ----------------------------------------------------------------

def cmd_last_run(args):
    usage = "usage: %s last-run <key> start | write <outcome> [--kind build|review] [--task <ref>] [--detail <text>]" % PROG
    if len(args) < 2:
        die(1, usage)
    key, verb = args[0], args[1]
    kind = _flag_value(args[2:], "--kind") or "build"
    if kind not in RUN_KINDS:
        die(1, "%s: last-run: --kind must be one of %s" % (PROG, "|".join(RUN_KINDS)))
    path = last_run_path(key, kind)
    if verb == "start":
        _write_json(path, {"started": now_iso(), "ended": None, "outcome": "running", "task": None, "detail": None})
        return
    if verb != "write" or len(args) < 3 or args[2].startswith("--"):
        die(1, usage)
    prev = _read_json(path) or {}
    rec = {
        "started": prev.get("started") or now_iso(),
        "ended": now_iso(),
        "outcome": args[2],
        "task": _flag_value(args[3:], "--task"),
        "detail": _flag_value(args[3:], "--detail"),
    }
    _write_json(path, rec)
    sys.stdout.write(json.dumps(rec, indent=2) + "\n")


COMMANDS = {
    "key": cmd_key,
    "read": cmd_read,
    "write": cmd_write,
    "rotate": cmd_rotate,
    "order": cmd_order,
    "gate": cmd_gate,
    "marker": cmd_marker,
    "candidates": cmd_candidates,
    "aggregate": cmd_aggregate,
    "cards": cmd_cards,
    "last-run": cmd_last_run,
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stdout.write("usage: %s <%s> [args]\n" % (PROG, "|".join(COMMANDS)))
        sys.exit(0)
    handler = COMMANDS.get(argv[0])
    if handler is None:
        die(1, "%s: unknown command '%s'" % (PROG, argv[0]))
    handler(argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
