# goal_view.py — what a running goal is doing, read from Claude Code's transcripts.
#
# Read-only. A goal's calls all run in its worktree, so Claude Code writes them to
# one project folder: the newest session there is the call going on now, and its
# sub-agents sit beside it, each with a meta file that says what it was asked to do
# and whether it finished.

import datetime
import glob
import json
import os
import re
import subprocess
import time

TAIL_BYTES = 400 * 1024
LINE_BYTES = 64 * 1024
# A sub-agent whose meta file does not say it finished, and whose transcript has not
# moved for this long, is taken as gone rather than running.
STALE = 15 * 60
# A goal in one of these is in a call; in any other, nothing of it runs, and a
# sub-agent that never finished was cut off.
ACTIVE = ("working", "checking")
# A sub-agent running longer than this was given too much: it shows as a warning.
LONG = 8 * 60


def claude_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def project_dir(worktree, base=None):
    """Claude Code's folder for sessions run in `worktree`: its path with every
    character other than a letter or digit turned into "-"."""
    name = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(worktree))
    path = os.path.join(base or claude_dir(), "projects", name)
    return path if os.path.isdir(path) else None


def _when(text):
    try:
        return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _read_tail(path, size=TAIL_BYTES):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            data = f.read()
    except (IOError, OSError):
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if end > size else lines


def _first_line(path):
    try:
        with open(path, "rb") as f:
            return f.readline(LINE_BYTES).decode("utf-8", "replace")
    except (IOError, OSError):
        return ""


def describe_tool(name, args):
    """A tool call in a few words: what it touched."""
    args = args or {}
    if name == "Agent" or name == "Task":
        return "started a sub-agent: %s" % (args.get("description") or "?")
    for key in ("file_path", "path", "notebook_path"):
        if args.get(key):
            return "%s %s" % (name, args[key])
    if args.get("command"):
        return "%s: %s" % (name, " ".join(str(args["command"]).split())[:120])
    if args.get("pattern"):
        return "%s %s" % (name, args["pattern"])
    if args.get("description"):
        return "%s: %s" % (name, args["description"])
    return name


def activity(lines):
    """From transcript lines: {action, said, at, model, agents_started}: the
    latest tool call, the latest thing the agent said, and when it last moved."""
    out = {"action": None, "said": None, "at": None, "model": None, "agents_started": 0}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = _when(row.get("timestamp"))
        if at:
            out["at"] = at
        message = row.get("message") or {}
        if row.get("type") != "assistant" or not isinstance(message.get("content"), list):
            continue
        if message.get("model"):
            out["model"] = message["model"]
        for block in message["content"]:
            if block.get("type") == "tool_use":
                out["action"] = describe_tool(block.get("name"), block.get("input"))
                if block.get("name") in ("Agent", "Task"):
                    out["agents_started"] += 1
            elif block.get("type") == "text" and (block.get("text") or "").strip():
                out["said"] = " ".join(block["text"].split())
    return out


def active(goal):
    return goal.get("status") in ACTIVE and goal.get("alive", True)


def subagents(session_path, now=None, in_call=True):
    """The call's sub-agents, running first, then the newest: [{description,
    running, cut, started, at, action, model}]. With `in_call` false, the call is not
    running, so none is: one that never finished is `cut` off."""
    now = now or time.time()
    out = []
    folder = os.path.join(session_path[:-len(".jsonl")], "subagents")
    for path in glob.glob(os.path.join(folder, "agent-*.jsonl")):
        try:
            with open(path[:-len(".jsonl")] + ".meta.json") as f:
                meta = json.load(f)
        except (IOError, OSError, ValueError):
            meta = {}
        try:
            first = json.loads(_first_line(path))
        except ValueError:
            first = {}
        live = activity(_read_tail(path, 64 * 1024))
        moved = live["at"] or os.path.getmtime(path)
        unfinished = meta.get("finished") is not True
        out.append({"description": meta.get("description") or "sub-agent",
                    "running": in_call and unfinished and now - moved < STALE,
                    "cut": unfinished and not (in_call and now - moved < STALE),
                    "started": _when(first.get("timestamp")) or moved, "at": moved,
                    "action": live["action"], "model": live["model"]})
    return sorted(out, key=lambda a: (not a["running"], -a["at"]))


def current_session(worktree, leave_out=()):
    """The transcript of the call going on now in a goal's worktree, or None. The
    sessions in `leave_out`, the tasks the runner runs, are shown on their own."""
    folder = project_dir(worktree)
    if not folder:
        return None
    sessions = [p for p in glob.glob(os.path.join(folder, "*.jsonl"))
                if os.path.basename(p)[:-len(".jsonl")] not in leave_out]
    return max(sessions, key=os.path.getmtime) if sessions else None


def session_path(session):
    """A session's transcript, wherever it ran, or None."""
    found = glob.glob(os.path.join(claude_dir(), "projects", "*", "%s.jsonl" % session)) if session else []
    return found[0] if found else None


def tasks_now(goal, now=None):
    """The tasks the runner runs for the lead, from the goal's `tasks.json`: each
    with its live activity while it runs. None when there are none to show."""
    if not goal.get("log"):
        return None
    try:
        with open(os.path.join(os.path.dirname(goal["log"]), "tasks.json")) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return None
    if data.get("round") != goal.get("round"):
        return None
    out = []
    for t in data.get("tasks") or []:
        t = dict(t)
        path = session_path(t.get("session")) if t.get("status") == "running" else None
        t["live"] = activity(_read_tail(path, 64 * 1024)) if path else None
        out.append(t)
    return out


def _etime(text):
    """`ps` elapsed time, [[dd-]hh:]mm:ss, in seconds."""
    days, _, rest = text.strip().rpartition("-")
    parts = [int(p) for p in rest.split(":") if p.isdigit()]
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds + (int(days) * 86400 if days.isdigit() else 0)


def claude_processes():
    """{session: seconds running} of every `claude -p` call alive on this machine."""
    try:
        out = subprocess.run(["ps", "-axww", "-o", "etime=,command="], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        if " -p " not in line or "claude" not in line:
            continue
        m = re.search(r"--(?:session-id|resume)\s+([0-9a-f-]{36})", line)
        if m:
            found[m.group(1)] = _etime(line.split(None, 1)[0])
    return found


def call_role(goal, session, tasks):
    """What a call of the goal is, in a word or two."""
    if session == goal.get("session"):
        return "Lead"
    for t in tasks or []:
        if t.get("session") == session:
            return ("Explorer: " if t.get("kind") == "explore" else "Coder: ") + t.get("name", "")
    doing = (goal.get("doing") or "").lower()
    for word, role in (("ci", "CI fixer"), ("review", "Reviewer"), ("check", "Checker")):
        if re.search(r"\b%s" % word, doing):
            return role
    return "Call"


def running_agents(goal, now=None, processes=None):
    """Every agent of the goal that is running now: each call alive, then the
    sub-agents working inside it. [{role, model, seconds, action, at, depth}]."""
    now = now or time.time()
    processes = claude_processes() if processes is None else processes
    tasks = tasks_now(goal, now) or []
    mine = {goal.get("session")} | {t.get("session") for t in tasks}
    folder = project_dir(goal["worktree"]) if goal.get("worktree") else None
    out = []
    for session, seconds in sorted(processes.items(), key=lambda kv: -kv[1]):
        path = session_path(session)
        if not path or not (session in mine or (folder and os.path.dirname(path) == folder)):
            continue
        live = activity(_read_tail(path, 64 * 1024))
        out.append({"role": call_role(goal, session, tasks), "model": live["model"],
                    "seconds": seconds, "action": live["action"], "at": live["at"], "depth": 0})
        for a in subagents(path, now, True):
            if a["running"]:
                out.append({"role": "Sub-agent: " + a["description"], "model": a["model"],
                            "seconds": now - a["started"], "action": a["action"], "at": a["at"],
                            "depth": 1})
    return out


def snapshot(goal, now=None, processes=None):
    """Everything the live view shows for a goal, or None when no call has run.
    The lead's own session comes first; else the latest call in its worktree."""
    worktree = goal.get("worktree")
    tasks = tasks_now(goal, now)
    path = current_session(worktree, {t.get("session") for t in tasks or []}) if worktree else None
    if tasks and any(t.get("status") in ("running", "waiting") for t in tasks):
        path = session_path(goal.get("session")) or path
    if not path:
        return None
    now = now or time.time()
    session = os.path.basename(path)[:-len(".jsonl")]
    agents = subagents(path, now, active(goal))
    return {"session": session, "role": "lead" if session == goal.get("session") else "call",
            "main": activity(_read_tail(path)), "agents": agents,
            "running": sum(1 for a in agents if a["running"]), "now": now, "tasks": tasks,
            "live": running_agents(goal, now, processes)}


def running_count(goal, now=None, processes=None):
    """How many agents of the goal are running now: its calls alive, and the
    sub-agents inside them."""
    return len(running_agents(goal, now, processes))


def _old_running_count(goal, now=None):
    """How many of the current call's sub-agents are running: cheap enough for every
    refresh, as it reads only their meta files and modification times."""
    path = current_session(goal["worktree"]) if goal.get("worktree") else None
    if not path or not active(goal):
        return 0
    now = now or time.time()
    count = 0
    for meta in glob.glob(os.path.join(path[:-len(".jsonl")], "subagents", "agent-*.meta.json")):
        try:
            with open(meta) as f:
                finished = json.load(f).get("finished") is True
        except (IOError, OSError, ValueError):
            continue
        transcript = meta[:-len(".meta.json")] + ".jsonl"
        if not finished and os.path.exists(transcript) and now - os.path.getmtime(transcript) < STALE:
            count += 1
    return count


def ago(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "%ds ago" % seconds
    if seconds < 3600:
        return "%dm ago" % (seconds // 60)
    return "%dh %02dm ago" % (seconds // 3600, seconds % 3600 // 60)


def span(seconds):
    seconds = max(0, int(seconds))
    return "%dm" % (seconds // 60) if seconds < 3600 else "%dh %02dm" % (seconds // 3600, seconds % 3600 // 60)


def short_model(model):
    for name in ("fable", "opus", "sonnet", "haiku"):
        if name in (model or ""):
            return name
    return model or ""


_HEADING = re.compile(r"^(#+)\s*(.*)$")
_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*\[( |x|X)\]\s*(.*)$")
STAGES = ("analysis", "review", "approval", "building", "syncing", "CI", "checking", "done")


def read_journal(path):
    try:
        with open(path, errors="replace") as f:
            return [l.rstrip() for l in f.readlines()]
    except (IOError, OSError):
        return []


def plan(lines, word="plan", anywhere=True):
    """The lead's checklist: the `- [ ]` / `- [x]` items under a heading that says
    `word`, or with `anywhere`, every item in the journal when no heading does.
    {done, total, next, items: [(done, text)]}, or None when there is no checklist."""
    section, level = None, None
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if m and word in m.group(2).lower():
            section, level = [], len(m.group(1))
            for rest in lines[i + 1:]:
                n = _HEADING.match(rest)
                if n and len(n.group(1)) <= level:
                    break
                section.append(rest)
            break
    if section is None and not anywhere:
        return None
    items = [(m.group(1) != " ", m.group(2).strip())
             for m in (_ITEM.match(l) for l in (section if section is not None else lines)) if m]
    if not items:
        return None
    done = sum(1 for d, _ in items if d)
    return {"done": done, "total": len(items), "items": items,
            "next": next((t for d, t in items if not d), None)}


def stage(goal):
    """Where a goal is in its flow, one of STAGES, from its status and what it says
    it is doing."""
    status, doing = goal.get("status"), (goal.get("doing") or "").lower()
    if status in ("done", "review"):
        return "done"
    if (goal.get("awaiting") or {}).get("kind") == "plan":
        return "approval"
    if goal.get("phase") == "planning":
        return "review" if "review" in doing else "analysis"
    if status == "checking":
        if "sync" in doing:
            return "syncing"
        if "ci" in doing.split() or "ci," in doing or "ci:" in doing:
            return "CI"
        return "checking"
    return "building"


def stage_line(goal):
    current = stage(goal)
    return " ▸ ".join("[%s]" % s if s == current else s for s in STAGES)


def bar(done, total, width=20):
    filled = int(round(width * done / total)) if total else 0
    return "█" * filled + "·" * (width - filled)


def journal_tail(path, n=12):
    try:
        with open(path, errors="replace") as f:
            lines = [l.rstrip() for l in f.readlines()]
    except (IOError, OSError):
        return []
    return [l for l in lines if l.strip()][-n:]


def lines_for(goal, snap, journal, width):
    """The live view, as (text, style) lines. `journal` is the journal's lines."""
    out = []
    doing = goal.get("doing") or goal.get("status") or ""
    rounds = "round %s" % goal["round"] if goal.get("round") else ""
    out.append((doing if not rounds or rounds in doing else "%s · %s" % (doing, rounds), "bold"))
    out.append(("Stage: " + stage_line(goal), "ok"))
    steps = plan(journal)
    criteria = plan(journal, "acceptance criteria", anywhere=False)
    if criteria:
        out.append(("Met:   %s %d of %d acceptance criteria" % (
            bar(criteria["done"], criteria["total"]), criteria["done"], criteria["total"]), "ok"))
    if steps:
        out.append(("Plan:  %s %d of %d steps done%s" % (
            bar(steps["done"], steps["total"]), steps["done"], steps["total"],
            " · next: %s" % steps["next"][:width - 60] if steps["next"] else ""), "ok"))
    if goal.get("cost"):
        out.append(("≈ $%.2f so far at API prices · u for the breakdown" % goal["cost"], "dim"))
    out.append(("", "normal"))
    live = (snap or {}).get("live") or []
    now = (snap or {}).get("now") or time.time()
    tasks = (snap or {}).get("tasks") or []
    out.append(("Running now", "bold"))
    if not live:
        out.append(("  nothing — %s" % doing, "dim"))
    if live and not any(r["role"] == "Lead" for r in live) and tasks:
        out.append(("  · Lead             not running: the runner calls it again when these end", "dim"))
    for r in live[:40]:
        indent = "  " + "   " * r["depth"]
        out.append(("%s● %-*s %-7s %6s" % (indent, 46 - len(indent), r["role"][:46 - len(indent)],
                                           short_model(r["model"]), span(r["seconds"])),
                    "warn" if r["seconds"] > LONG and r["depth"] else "ok"))
        if r["action"]:
            out.append(("%s    %s · %s" % (indent, r["action"][:width - 24],
                                          ago(now - r["at"]) if r["at"] else "?"), "dim"))
    finished = [t for t in tasks if t.get("status") not in ("running", "waiting")]
    if finished:
        out += [("", "normal"), ("Finished this round", "bold")]
        for t in finished:
            role = ("Explorer: " if t.get("kind") == "explore" else "Coder: ") + t["name"]
            took = (t.get("ended") or now) - (t.get("started") or now)
            result = t.get("merge") or t.get("status")
            out.append(("  %s %-44s %-7s %6s  %s" % (
                "✓" if t.get("status") == "done" else "✗", role[:44], short_model(t.get("model")),
                span(took), result[:max(10, width - 70)]),
                "warn" if t.get("status") != "done" or "not merged" in (t.get("merge") or "") else "dim"))
    if steps:
        out += [("", "normal"), ("Plan", "bold")]
        out += [("  %s %s" % ("✓" if d else "·", t[:width - 6]), "dim" if d else "normal")
                for d, t in steps["items"]]
    if criteria and criteria["done"] < criteria["total"]:
        unmet = [t for d, t in criteria["items"] if not d]
        out += [("", "normal"), ("Acceptance criteria not met yet", "bold")]
        out += [("  · %s" % t[:width - 6], "normal") for t in unmet[:30]]
        if len(unmet) > 30:
            out.append(("  … and %d more" % (len(unmet) - 30), "dim"))
    tail = [l for l in journal if l.strip()][-8:]
    if tail:
        out += [("", "normal"), ("Journal (latest lines)", "bold")]
        out += [("  " + l[:width - 4], "normal") for l in tail]
    return out
