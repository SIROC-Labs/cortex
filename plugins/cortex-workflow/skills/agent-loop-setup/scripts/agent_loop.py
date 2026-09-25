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
#   agent_loop.py order --from-json <path|->             # {"tasks":[...],"priority_order":[...]}
#   agent_loop.py gate --from-json <path|->              # {"blockers":[...],"board":…,"columns":…,"column_names":…}
#   agent_loop.py last-run <key> start
#   agent_loop.py last-run <key> write <outcome> [--task <ref>] [--detail <text>]
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
# Roles a blocker may sit in for the dependency gate to pass.
SATISFIED_ROLES = ("in_review", "ready", "done")


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


def last_run_path(key):
    return os.path.join(CACHE_DIR, key + ".last-run.json")


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
    tasks.sort(key=lambda t: (rank(t), t.get("index", 0)))
    sys.stdout.write(json.dumps(tasks, indent=2) + "\n")


# --- dependency gate ---------------------------------------------------------

# A blocker is satisfied when it is completed, or sits in the agent board's
# in_review/ready/done column (by ref), or sits on another board in a column whose
# name equals the agent board's in_review/ready/done name. Anything else blocks: fail closed.
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


# --- last run ----------------------------------------------------------------

def cmd_last_run(args):
    if len(args) < 2:
        die(1, "usage: %s last-run <key> start | write <outcome> [--task <ref>] [--detail <text>]" % PROG)
    key, verb = args[0], args[1]
    path = last_run_path(key)
    if verb == "start":
        _write_json(path, {"started": now_iso(), "ended": None, "outcome": "running", "task": None, "detail": None})
        return
    if verb != "write" or len(args) < 3:
        die(1, "usage: %s last-run <key> start | write <outcome> [--task <ref>] [--detail <text>]" % PROG)
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
