#!/usr/bin/env python3
#
# actions.py — what the service does to goals, for REST, MCP and the clients alike:
# the repos it knows, each repo's goals, a goal in full, starting one from a prompt,
# answering it, approving its plan, stopping and carrying it on, and the settings.

import base64
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.dirname(HERE)
for tool in ("lib", "goal"):
    if os.path.join(BIN, tool) not in sys.path:
        sys.path.insert(0, os.path.join(BIN, tool))
import control as dm  # noqa: E402
import core as st  # noqa: E402
import goal as gl  # noqa: E402
import goal_view as gv  # noqa: E402
import repos as rp  # noqa: E402
from agent import opencode_cli as oc  # noqa: E402

GOAL_ID = re.compile(r"^goal-[A-Za-z0-9._+-]+$")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
GATES = gl.GATES
MAX_FILE_BYTES = 20 * 1024 * 1024
LOG_CHUNK = 256 * 1024
# What a goal's page may read of its state, besides its journal and log.
READABLE = ("inputs/", "attachments/", gl.TECHNICAL_FILE, gl.REPORT_FILE)


class Problem(Exception):
    """A request the service refuses, with the HTTP status that says why."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


home = rp.home


# --- repos -------------------------------------------------------------------

def repo_ids(paths):
    """[{id, path, name}]: each repo by the name of its folder, made unique."""
    out, seen = [], set()
    for path in paths:
        name = os.path.basename(path.rstrip(os.sep)) or "repo"
        rid, n = st.slugify(name, max_words=8), 1
        while rid in seen:
            n += 1
            rid = "%s-%d" % (st.slugify(name, max_words=8), n)
        seen.add(rid)
        out.append({"id": rid, "path": path, "name": name})
    return out


def repos():
    return repo_ids(rp.paths())


def add_repo(path):
    """Register a repo, by any folder in it. Returns it."""
    try:
        root = st.main_repo_root(os.path.abspath(os.path.expanduser(path)))
    except st.Failure:
        raise Problem(400, "%s is not in a git repository" % path)
    rp.add(root)
    return next(r for r in repos() if r["path"] == root)


def repo(rid):
    found = next((r for r in repos() if r["id"] == rid), None)
    if not found:
        raise Problem(404, "no repo %s" % rid)
    return found


# --- goals -------------------------------------------------------------------

def finished(g):
    """Whether a goal is over: merged, closed, marked done, a done part, or done
    with no PR to watch."""
    return g.get("status") == "done" and (bool(g.get("parent")) or not g.get("pr_url")
                                          or g.get("phase") in ("merged", "closed", gl.MARKED))


def describe(g):
    """(what a goal is doing, its tone, a short label), the same for every client.
    The tone is ok, warn, bad, info or empty."""
    status, awaiting = g.get("status"), g.get("awaiting") or {}
    if awaiting.get("asked_at") and not (status in ("stopped", "failed") and not g.get("alive")):
        kind = awaiting.get("kind")
        n = len(awaiting.get("questions") or [])
        text = ("the split waits on your review" if awaiting.get("split") else "the plan waits on your review") \
            if kind == "plan" else "stopped: " + (awaiting.get("headline") or "a problem") \
            if kind == "problem" else "has %s question%s for you" % (n or "a", "" if n == 1 else "s")
        return text, "warn", "waiting on you"
    if status in gl.LIVE and not g.get("alive"):
        return "stopped unexpectedly — carry it on", "bad", "stopped"
    doing = g.get("doing")
    if status == "working" and g.get("phase") == "planning":
        return doing or "analysing the ask", "ok", "analysing"
    if status in ("working", "checking", "setting-up", "parts"):
        return doing or status, "ok", "checking" if status == "checking" else "working"
    if status == "paused":
        return doing or "paused for the usage limit", "info", "paused"
    if status == "queued":
        return doing or "plan approved — waits to build", "info", "queued"
    if status == "review":
        if g.get("pr_error"):
            return "cannot read its PR: %s" % g["pr_error"][:100], "bad", "in review"
        return "ready to merge — watching the PR", "ok", "in review"
    if status == "done":
        phase = g.get("phase")
        if phase == "merged":
            return "merged", "", "merged"
        if phase == "closed":
            return "its PR was closed without a merge", "", "closed"
        if phase == gl.MARKED:
            return "marked done by you", "", "done"
        if g.get("parent"):
            return "merged into the goal's branch", "", "done"
        return "done — its PR is ready", "ok", "done"
    if status == "failed":
        return "failed: %s" % (g.get("reason") or "?").splitlines()[0][:120], "bad", "failed"
    if status == "stopped":
        return "stopped by you", "", "stopped"
    return status or "new", "", status or "new"


def summary(main_root, g, rates=None, processes=None):
    """A goal as a list shows it: its state without the ask, with its cost, how far
    its plan and criteria are, and how many agents run for it now."""
    out = {k: v for k, v in g.items() if k not in ("ask", "log", "revision_ask")}
    goal = gl.Goal(main_root, g["id"])
    out["agents_running"] = gv.running_count(g, processes=processes or {}) if g.get("alive") else 0
    out["cost"] = gl.write_report(goal, rates or {}, write=False)[1] or g.get("cost")
    journal = gv.read_journal(goal.journal)
    out["plan"] = gv.plan(journal)
    out["criteria"] = gv.plan(journal, "acceptance criteria", anywhere=False)
    out["finished"] = finished(g)
    out["waiting"] = bool((g.get("awaiting") or {}).get("asked_at"))
    out["title"] = gl.title_of(g)
    out["state"] = dict(zip(("text", "tone", "label"), describe(g)))
    return out


_PR_LOOKED = {}
PR_LOOK_EVERY = 300


def settle_finished_prs(main_root, listed, now=None):
    """A finished goal whose runner no longer watches its PR learns in the background
    when its PR was merged or closed."""
    import subprocess
    import threading
    now = now or time.time()
    for g in listed:
        if (g.get("status") != "done" or g.get("parent") or not g.get("pr_url") or g.get("alive")
                or g.get("phase") in ("merged", "closed", gl.MARKED)
                or now - _PR_LOOKED.get((main_root, g["id"]), 0) < PR_LOOK_EVERY):
            continue
        _PR_LOOKED[(main_root, g["id"])] = now

        def look(gid=g["id"], url=g["pr_url"]):
            try:
                out = subprocess.run(["gh", "pr", "view", url, "--json", "state", "--jq", ".state"],
                                     capture_output=True, text=True, timeout=30, cwd=main_root).stdout
            except (OSError, subprocess.SubprocessError):
                return
            phase = {"MERGED": "merged", "CLOSED": "closed"}.get(out.strip())
            if phase:
                gl.Goal(main_root, gid).update(phase=phase)
        threading.Thread(target=look, daemon=True).start()


def goals(main_root):
    """The repo's goals, newest first, each followed by its parts; a goal's cost and
    agents include its parts'."""
    listed = gl.list_goals(main_root)
    settle_finished_prs(main_root, listed)
    rates = gl.repo_rates(main_root) if listed else {}
    processes = gv.claude_processes() if any(g.get("alive") for g in listed) else {}
    out = [summary(main_root, g, rates, processes) for g in listed]
    titles = {g["id"]: g["title"] for g in out}
    for g in out:
        if g.get("parent"):
            g["parent_title"] = titles.get(g["parent"])
        parts = [p for p in out if p.get("parent") == g["id"]]
        if parts:
            g["cost"] = (g.get("cost") or 0) + sum(p.get("cost") or 0 for p in parts)
            g["agents_running"] += sum(p["agents_running"] for p in parts)
    return out


def all_goals():
    """Every registered repo's goals, each with its repo's id."""
    out = []
    for r in repos():
        out += [dict(g, repo=r["id"]) for g in goals(r["path"])]
    return out


def the_goal(main_root, gid):
    if not GOAL_ID.match(gid or ""):
        raise Problem(404, "no goal %s" % gid)
    goal = gl.Goal(main_root, gid)
    data = goal.read()
    if not data:
        raise Problem(404, "no goal %s" % gid)
    data.setdefault("id", gid)
    data["alive"] = bool(data.get("pid")) and st._pid_alive(data["pid"])
    return goal, data


def _text(path):
    try:
        with open(path) as f:
            return f.read()
    except (IOError, OSError, UnicodeDecodeError):
        return None


def _files(state_dir, sub):
    folder = os.path.join(state_dir, sub)
    if not os.path.isdir(folder):
        return []
    return sorted("%s/%s%s" % (sub, n, "/" if os.path.isdir(os.path.join(folder, n)) else "")
                  for n in os.listdir(folder))


NOW_ACTIONS = 8


def now(data, processes):
    """What the goal's running call is doing: what it last said, its last actions,
    and its sub-agents at work; None when no call runs."""
    try:
        snap = gv.snapshot(data, processes=processes)
    except Exception:  # noqa: BLE001 — a transcript being written is read again next time
        return None
    if not snap or not data.get("status") in gv.ACTIVE:
        return None
    path = gv.session_path(snap["session"])
    actions, said = gv.recent(gv._read_tail(path, 256 * 1024), NOW_ACTIONS) if path else ([], [])
    return {"role": snap["role"], "said": said[-1] if said else None, "actions": actions,
            "at": (snap.get("main") or {}).get("at"),
            "agents": [{"description": a.get("description"), "action": a.get("action"),
                        "model": a.get("model")} for a in snap.get("agents") or [] if a.get("running")]}


def detail(main_root, gid):
    """A goal in full, for its page: its state and summary, what waits on you, the
    journal, the technical plan, its tasks, its parts, the files it was given, and
    how long its log is."""
    goal, data = the_goal(main_root, gid)
    data["awaiting"] = goal.state.read("awaiting.json")
    rates = gl.repo_rates(main_root)
    out = summary(main_root, dict(data, log=goal.log), rates)
    out["ask"] = data.get("ask")
    out["journal"] = _text(goal.journal)
    out["technical_plan"] = _text(goal.state.path(gl.TECHNICAL_FILE))
    out["tasks"] = goal.state.read(gl.TASKS_FILE)
    priced = gl.write_report(goal, rates, write=False)[0]
    out["calls"] = priced
    out["usage_report"] = gl.usage_report(priced) if priced else None
    out["files"] = _files(goal.state.dir, gl.INPUTS_DIR) + _files(goal.state.dir, "attachments")
    out["parts"] = [summary(main_root, dict(p, alive=bool(p.get("pid")) and st._pid_alive(p["pid"])),
                            rates)
                    for p in (gl.Goal(main_root, x["id"]).read() for x in data.get("parts") or [])
                    if p]
    if out["parts"]:
        out["own_cost"] = out.get("cost")
        out["cost"] = (out.get("cost") or 0) + sum(p.get("cost") or 0 for p in out["parts"])
    log_text = _text(goal.log) or ""
    out["log_size"] = len(log_text.encode())
    cs = cards(timeline(log_text, data.get("created"), priced), part=bool(data.get("parent")))
    import asked
    import running
    try:
        asked.attach(cs, goal, data, priced)
    except Exception:  # noqa: BLE001 — past answers are extra: the timeline shows without them
        pass
    out["timeline"] = cs
    out["sent"] = asked.sent(goal, data["awaiting"])
    processes = gv.claude_processes() if data["alive"] else {}
    out["live"] = gv.running_agents(data, processes=processes) if data["alive"] else []
    try:
        running.summarize(out["live"], data, dm.read_control(main_root))
    except Exception:  # noqa: BLE001 — a summary that fails is left out, never the page
        pass
    for a in out["live"]:
        a.pop("path", None)
    try:
        out["lead_edits"] = running.lead_edits(main_root, data, goal.state.read(gl.CALLS_FILE) or priced)
    except Exception:  # noqa: BLE001
        out["lead_edits"] = []
    out["now"] = now(data, processes) if data["alive"] else None
    out["tasks_now"] = gv.tasks_now(data) or []
    out["stages"] = stage_strip(cs, data)
    out["who"] = "Your answer is sent: the goal picks it up next" if out["sent"] else who_works(
        data, out["live"], out["tasks_now"], cs)
    return out


STEP_LINE = re.compile(r"^(\d\d):(\d\d):(\d\d)  (\S.*)$")


def timeline(text, created, calls=()):
    """The log as steps: [{at, title, lines, cost}]. A step line carries only the
    time of day, so the date runs on from `created`, a day on each time that goes
    back. Each call's cost goes to the step it started in."""
    steps, day = [], None
    for line in (text or "").splitlines():
        m = STEP_LINE.match(line)
        if m:
            h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if day is None:
                day = time.mktime(time.localtime(created or time.time())[:3] + (0, 0, 0, 0, 0, -1))
            at = time.mktime(time.localtime(day)[:3] + (h, mi, se, 0, 0, -1))
            while steps and at < steps[-1]["at"] - 60:
                day += 86400
                at = time.mktime(time.localtime(day)[:3] + (h, mi, se, 0, 0, -1))
            steps.append({"at": at, "title": m.group(4).strip(), "lines": [], "cost": 0.0})
        elif steps and line.strip():
            steps[-1]["lines"].append(line[2:] if line.startswith("  ") else line)
    for c in calls or []:
        started = c.get("started")
        if not steps or not isinstance(started, (int, float)):
            continue
        i = max((n for n, step in enumerate(steps) if step["at"] <= started + 1), default=0)
        steps[i]["cost"] += c.get("cost") or 0
    return steps


def kind_of(title):
    """What kind of step a log step is, by its title."""
    for kind, pattern in (("round", r"^Round \d+"), ("tasks", r"^Running \d+ task"),
                          ("you", r"^Asking you|ready for your review|^Asking the goal's lead"),
                          ("check", r"^Reviewing the acceptance criteria|^Checking"),
                          ("ci", r"CI|static checks|^Syncing"), ("pause", r"^Paused"),
                          ("alert", r"^Stopped|failed|^Review comments"),
                          ("ship", r"^Merged|^Finishing|^Watching the PR")):
        if re.search(pattern, title):
            return kind
    return "step"


def task_rows(lines):
    """The tasks a round handed out, from its log lines: [{kind, name, model, result}]."""
    rows, by = [], {}
    for line in lines:
        m = re.match(r"^(task|question): (.+) on (\S+)$", line)
        if m:
            by[m.group(2)] = {"kind": "code" if m.group(1) == "task" else "explore",
                              "name": m.group(2), "model": m.group(3), "result": "running"}
            rows.append(by[m.group(2)])
            continue
        r = re.match(r"^(.+?): (done|failed|stopped|cut off|no report)(.*)$", line)
        if r and r.group(1) in by:
            by[r.group(1)]["result"] = r.group(2) + r.group(3)
    return rows


CALL_LINE = re.compile(r"^(lead|review|check|ci-fix|consult|compact): ")
PAUSE_LINE = re.compile(r"^(Paused — |resumes at |usage is back )")


def handed_out(tasks):
    """What a round handed out, in a few words: "3 coding tasks and 1 question (sonnet)"."""
    code = sum(1 for t in tasks if t["kind"] == "code")
    asks = len(tasks) - code
    what = " and ".join(x for x in ("%d coding task%s" % (code, "" if code == 1 else "s") if code else "",
                                    "%d question%s" % (asks, "" if asks == 1 else "s") if asks else "") if x)
    models = sorted({gv.short_model(t.get("model")) for t in tasks if t.get("model")})
    return "Handed out %s%s" % (what, " (%s)" % ", ".join(models) if models else "")


def card_summary(card):
    said = [l for l in card["lines"] if not CALL_LINE.match(l) and not PAUSE_LINE.match(l) and not l.startswith("! ")]
    if card["kind"] == "round":
        words = " ".join(said)
        if card.get("tasks"):
            head = handed_out(card["tasks"])
        else:
            nxt = card.get("next") or ""
            head = ("Reported done" if nxt.startswith("Syncing with") else
                    "Asked questions" if re.match(r"^Asking", nxt) else
                    "Wrote the plan" if "ready for your review" in nxt else
                    "Said" if words else "")
        return ": ".join(x for x in (head, words) if x)
    if card["kind"] == "check":
        verdict = next((l for l in card["lines"] if re.match(r"^verdict: |^review: \d+ problem", l)), "")
        return re.sub(r"^(verdict|review): ", "", verdict).replace("done", "clean", 1) if verdict.startswith(
            "verdict: done") else re.sub(r"^(verdict|review): ", "", verdict)
    if card["kind"] == "you":
        asked = len([l for l in card["lines"] if l.startswith("Q: ")])
        answered = any(re.match(r"^answered|approved|the plan is approved", l) for l in card["lines"])
        return " · ".join(x for x in ("%d question%s" % (asked, "" if asked == 1 else "s") if asked else "",
                                      "answered" if answered else "") if x)
    return said[-1] if said else ""


BACK = {"conflict": "Merge conflict", "static": "Fixing static checks", "gaps": "Fixing gaps",
        "ci": "Fixing CI"}


def verdict_of(lines):
    """A check's verdict: "clean", "N gaps", or None while it has none."""
    for line in lines:
        if line.startswith("verdict: done"):
            return "clean"
        m = re.match(r"^verdict: (\d+) gap", line)
        if m:
            return "%s gap%s" % (m.group(1), "" if m.group(1) == "1" else "s")
    return None


def cards(steps, part=False):
    """The timeline as a person follows it: each step, with a round and the tasks it
    handed out as one card, in phases: Setup, Plan, Parts, Build, Merge conflict,
    Static checks, Fixing static checks, Check N, Fixing gaps, Merge and push (a
    part's Merge), CI, Fixing CI, PR review, and Revision N, whose later phases carry
    its name. [{i, kind, phase, base, title, at, until, cost, summary, lines, tasks}]:
    `base` is the phase without the revision."""
    out, i = [], 0
    planning, approved, cycle, checks, back, clean = True, False, 0, 0, None, False
    phase, base, carried = "Setup", "Setup", []
    while i < len(steps):
        s = steps[i]
        kind = kind_of(s["title"])
        while kind == "round" and i + 1 < len(steps) and kind_of(steps[i + 1]["title"]) == "pause":
            i += 1
            s = dict(s, lines=s["lines"] + [steps[i]["title"]] + steps[i]["lines"], cost=s["cost"] + steps[i]["cost"])
        title, text = s["title"], "\n".join(s["lines"])
        new = None
        if title.startswith("Review comments on the PR"):
            cycle, checks, back, clean, new = cycle + 1, 0, None, False, "Revision"
        elif re.match(r"^(Reading the|Setting up)", title):
            new = "Setup"
        elif title.startswith("Splitting into"):
            planning, new = False, "Parts"
        elif title.startswith("Small change"):
            planning, new = False, "Build"
        elif planning and not (approved or kind == "tasks" or title.startswith("Small change")):
            new = "Plan"
        elif title.startswith("Syncing with "):
            planning = False
            if "conflicts" in text:
                back, new = "conflict", "Merge conflict"
            elif clean:
                back, new = None, "Merge" if part else "Merge and push"
            else:
                back = None
        elif title.startswith(("Running CI's static checks", "Fixing CI's static checks")):
            new = "Static checks"
            if "over to the lead" in text:
                back = "static"
        elif title.startswith("Checking against the ask"):
            checks += 1
            new = "Check %d" % checks
            clean = verdict_of(s["lines"]) == "clean"
            if not clean:
                back = "gaps"
        elif title.startswith(("Waiting for CI", "Fixing CI (")):
            back, new = "ci", "CI"
        elif title.startswith(("Watching the PR", "Merged", "The PR was closed")):
            new = "PR review"
        elif kind in ("round", "tasks"):
            planning, clean = False, False
            new = BACK.get(back) or ("Revision" if cycle else "Build")
        approved = any("the plan is approved" in l for l in s["lines"])
        if new:
            base = new
            phase = ("Revision %d" % cycle if new == "Revision" else new) if not cycle or new in (
                "Revision", "Setup", "Plan") else "Revision %d · %s" % (cycle, new)
        card = {"i": i, "kind": kind, "phase": phase, "base": base, "title": title, "at": s["at"],
                "cost": s["cost"], "lines": list(s["lines"]), "tasks": None}
        if kind == "check" and title.startswith("Checking"):
            card["verdict"] = verdict_of(s["lines"])
        if title.startswith("Syncing with ") and not new:
            carried.append(card)
        else:
            for c in carried:
                c["phase"], c["base"] = phase, base
            carried = []
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if kind == "round" and nxt and kind_of(nxt["title"]) == "tasks":
            i += 1
            card["tasks_title"], card["tasks_lines"] = nxt["title"], list(nxt["lines"])
            card["cost"] += nxt["cost"]
        elif kind == "tasks":
            card["tasks_lines"] = card["lines"]
        if card.get("tasks_lines") is not None:
            while i + 1 < len(steps) and kind_of(steps[i + 1]["title"]) == "pause":
                i += 1
                card["tasks_lines"] += [steps[i]["title"]] + steps[i]["lines"]
                card["cost"] += steps[i]["cost"]
            card["tasks"] = task_rows(card["tasks_lines"]) or None
        i += 1
        card["next"] = steps[i]["title"] if i < len(steps) else None
        card["summary"] = card_summary(card)
        card["until"] = steps[i]["at"] if i < len(steps) else None
        out.append(card)
    for c in carried:
        c["base"] = "Build" if c["base"] == "Plan" else "Static checks"
        c["phase"] = c["base"] if not cycle else "Revision %d · %s" % (cycle, c["base"])
    return out


STAGE_OF = {"Setup": "plan", "Plan": "plan", "Parts": "plan", "Build": "build", "Revision": "build",
            "Merge conflict": "build", "Static checks": "static", "Fixing static checks": "static",
            "Fixing gaps": "fixing", "Merge": "ship", "Merge and push": "ship", "CI": "ci",
            "Fixing CI": "ci", "PR review": "review"}


def stage_strip(cs, data):
    """Where the goal is, as the stages of its current build or revision: Plan, Build,
    Static checks, the checks and their gaps, Merge or Push, CI, PR review.
    [{key, label, state}], each state done, now or next."""
    part = bool(data.get("parent"))
    starts = [n for n, c in enumerate(cs) if c["title"].startswith("Review comments on the PR")]
    cycle = cs[starts[-1]:] if starts else cs
    base = cycle[-1]["base"] if cycle else "Setup"
    checks = [c for c in cycle if c["base"].startswith("Check ")]
    labels = {"plan": "Plan", "build": "Revision %d" % len(starts) if starts else "Build",
              "static": "Static checks", "check": "Check", "fixing": "Fixing gaps", "again": "Check again",
              "ship": "Merge" if part else "Push", "ci": "CI", "review": "PR review"}
    shown = ["plan", "build", "static", "check", "ship"] + ([] if part else ["ci", "review"])
    name = lambda c: "%s%s" % (c["base"], ": " + c["verdict"] if c.get("verdict") else "")  # noqa: E731
    last = checks[-1] if checks else None
    earlier = checks[-2] if len(checks) > 1 else None
    if last and last.get("verdict") not in (None, "clean"):
        labels["check"] = name(last)
        shown[4:4] = ["fixing", "again"]
    elif last and earlier:
        labels["check"], labels["again"] = name(earlier), name(last)
        shown[4:4] = ["fixing", "again"]
    elif last:
        labels["check"] = name(last)
    key = STAGE_OF.get(base)
    if base.startswith("Check "):
        key = "again" if "again" in shown and last is not checks[0] else "check"
    if base == "Static checks" and "again" in shown and last and last.get("verdict") not in (None, "clean"):
        key = "again"
    if data.get("status") == "review":
        key = "review"
    over = data.get("status") == "done" and (part or data.get("phase") in ("merged", "closed", gl.MARKED)
                                             or not data.get("pr_url"))
    at = shown.index(key) if key in shown else 0
    return [{"key": k, "label": labels[k],
             "state": "done" if over or n < at else "now" if n == at else "next"}
            for n, k in enumerate(shown)]


def who_works(data, live, tasks, cs):
    """Who works on the goal now, in a line."""
    model = lambda m: gv.short_model(m).capitalize() if m else ""  # noqa: E731
    text, tone, _ = describe(data)
    status = data.get("status")
    if tone in ("warn", "bad") or status in ("paused", "queued", "stopped", "failed", "done"):
        return ("You: it " if text.startswith("has ") else "You: ") + text if tone == "warn" else "Nobody: " + text
    running = [t for t in tasks or [] if t.get("status") == "running"]
    if running:
        code = [t for t in running if t.get("kind") != "explore"]
        asks = [t for t in running if t.get("kind") == "explore"]
        models = sorted({model(t.get("model")) for t in running if t.get("model")})
        what = " and ".join(x for x in (
            "%d coding task%s" % (len(code), "" if len(code) == 1 else "s") if code else "",
            "%d question%s" % (len(asks), "" if len(asks) == 1 else "s") if asks else "") if x)
        waiting = sum(1 for t in tasks if t.get("status") == "waiting")
        return "%s%s run%s%s; the lead waits for their reports" % (
            what, " on " + ", ".join(models) if models else "", "s" if len(running) == 1 else "",
            ", %d more wait to start" % waiting if waiting else "")
    base = cs[-1]["base"] if cs else ""
    for a in live or []:
        role, m = a.get("role") or "", model(a.get("model"))
        by = " (%s)" % m if m else ""
        if role == "Lead":
            if data.get("phase") == "planning":
                return "The lead%s analyses the ask and writes the plan" % by
            return "The lead%s reads the reports and decides what to hand out next%s" % (
                by, " (a merge conflict)" if base == "Merge conflict" else "")
        if role == "Checker":
            return "The checker%s checks the branch against the ask and its criteria" % by
        if role == "Reviewer":
            return "The reviewer%s checks the acceptance criteria against the references" % by
        if role == "CI fixer":
            return "The fixer%s fixes the failing %s" % (by, "static checks" if base == "Static checks" else "CI")
    if status == "review":
        return "Nobody: the goal watches the PR for review comments and the merge"
    if data.get("runner_doing"):
        return "The runner: %s" % data["runner_doing"]
    if "waiting for ci" in (data.get("doing") or "").lower():
        return "GitHub runs CI; the runner waits for it"
    return text[:1].upper() + text[1:] if text else ""


def log(main_root, gid, start=0, limit=LOG_CHUNK):
    """The goal's log from byte `start`: {text, next}. A negative start reads the
    last bytes."""
    goal, _ = the_goal(main_root, gid)
    try:
        with open(goal.log, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            start = max(0, end + start) if start < 0 else min(start, end)
            f.seek(start)
            data = f.read(limit)
    except (IOError, OSError):
        return {"text": "", "next": 0}
    return {"text": data.decode("utf-8", "replace"), "next": start + len(data)}


def state_file(main_root, gid, rel):
    """(absolute path, bytes) of a file in the goal's state that its page may read."""
    goal, _ = the_goal(main_root, gid)
    rel = os.path.normpath(rel or "")
    if rel.startswith("..") or os.path.isabs(rel) or not (
            rel in READABLE or any(rel.startswith(p) for p in READABLE if p.endswith("/"))):
        raise Problem(404, "no file %s" % rel)
    path = goal.state.path(rel)
    if not os.path.isfile(path):
        raise Problem(404, "no file %s" % rel)
    with open(path, "rb") as f:
        return path, f.read()


def start(main_root, prompt, files=(), base=None):
    """Start a goal on a prompt. `files` are local paths of files or folders, or
    uploads {name, data} with the bytes in base64. An upload whose name is a path,
    such as `proto/Main.dc.html`, lands in that folder, and the folder is given as
    one. Returns the goal's id."""
    if not (prompt or "").strip():
        raise Problem(400, "a goal needs a prompt")
    add_repo(main_root)
    tmp = tempfile.mkdtemp(prefix="cond-upload-")
    try:
        paths = []
        for n, f in enumerate(files or []):
            if isinstance(f, str):
                if not os.path.exists(os.path.expanduser(f)):
                    raise Problem(400, "no file or folder %s" % f)
                paths.append(os.path.expanduser(f))
                continue
            raw = str((f or {}).get("name") or "file-%d" % (n + 1)).replace("\\", "/")
            rel = os.path.normpath(raw.strip("/"))
            if rel.startswith("..") or os.path.isabs(raw) or rel in (".", ""):
                raise Problem(400, "%s is not a file name" % raw)
            try:
                body = base64.b64decode((f or {}).get("data") or "", validate=True)
            except (ValueError, TypeError):
                raise Problem(400, "%s is not base64" % raw)
            if len(body) > MAX_FILE_BYTES:
                raise Problem(400, "%s is over %d MB" % (raw, MAX_FILE_BYTES // 2 ** 20))
            top = rel.split(os.sep)[0]
            target = os.path.join(tmp, "folders" if os.sep in rel else str(n), rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                out.write(body)
            given = os.path.join(tmp, "folders", top) if os.sep in rel else target
            if given not in paths:
                paths.append(given)
        control = dm.read_control(main_root)
        try:
            gid = gl.create(main_root, prompt, paths, base=base or control.get("base"),
                            **gl.settings_from(control))
        except st.Failure as e:
            raise Problem(400, str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    gl.launch(main_root, gid)
    return gid


def stop(main_root, gid):
    _, data = the_goal(main_root, gid)
    if not data["alive"]:
        raise Problem(409, "the goal is not running")
    try:
        os.killpg(data["pid"], signal.SIGTERM)
    except OSError:
        dm.kill_pid(data["pid"])
    return "stopping"


def resume(main_root, gid):
    _, data = the_goal(main_root, gid)
    if data["alive"]:
        raise Problem(409, "the goal is still running")
    if finished(data):
        raise Problem(409, "the goal is done")
    gl.launch(main_root, gid)
    return "carries on"


def retire_discussions(goal, prefix=""):
    """Put the talks whose key starts with `prefix` away, under `discussions/old/`: a
    talk asked for again starts empty."""
    folder = goal.state.path("discussions")
    if not os.path.isdir(folder):
        return
    os.makedirs(os.path.join(folder, "old"), exist_ok=True)
    for name in os.listdir(folder):
        if name.endswith(".json") and name.startswith(prefix):
            os.replace(os.path.join(folder, name),
                       os.path.join(folder, "old", "%s-%d.json" % (name[:-len(".json")], time.time() * 1000)))


def answer(main_root, gid, text, answers=None, note=None):
    """Hand the person's answer to the goal waiting on it, and keep it with what it
    answers. `answers`, one per question, and `note` are how the page wrote it. A
    decision on the plan puts the plan's talks away."""
    import asked
    goal, _ = the_goal(main_root, gid)
    waiting = goal.state.read("awaiting.json") or {}
    if not waiting.get("asked_at"):
        raise Problem(409, "the goal is not waiting on an answer")
    if not (text or "").strip():
        raise Problem(400, "an empty answer")
    goal.state.write(st.ANSWER_FILE, {"asked_at": waiting["asked_at"], "text": text.strip(),
                                      "at": time.time()})
    good = isinstance(answers, list) and all(isinstance(a, str) for a in answers)
    asked.record(goal, waiting, text.strip(), answers if good else None,
                 note.strip() or None if isinstance(note, str) else None)
    if waiting.get("kind") == "plan":
        retire_discussions(goal, "plan-")
    return "answered"


def approve(main_root, gid):
    goal, _ = the_goal(main_root, gid)
    if (goal.state.read("awaiting.json") or {}).get("kind") != "plan":
        raise Problem(409, "no plan waits on your approval")
    answer(main_root, gid, "continue")
    return "approved"


def mark_done(main_root, gid):
    _, data = the_goal(main_root, gid)
    if data.get("parent"):
        raise Problem(409, "a part is done when it is merged: mark its goal done")
    gl.mark_done(main_root, gid)
    return "marked done"


def clear(main_root, gid):
    goal, data = the_goal(main_root, gid)
    if data["alive"]:
        raise Problem(409, "the goal is running: stop it first")
    for g in gl.goal_and_parts(main_root, gid):
        g.update(cleared=True)
    return "cleared"


def undo(main_root, gid):
    the_goal(main_root, gid)
    try:
        return gl.undo(main_root, gid)
    except st.Failure as e:
        raise Problem(409, str(e))


# --- settings ----------------------------------------------------------------

def settings(main_root):
    """The repo's settings, with each default filled in."""
    control = dm.read_control(main_root)
    models = control.get("models") or {}
    opencode = control.get("opencode") or {}
    return {"base": control.get("base"),
            "runner": control.get("runner") if control.get("runner") in gl.RUNNERS else "claude",
            "opencode_models": {k: opencode.get(k) for k in ("lead", "subagent", "check")},
            "usage_threshold": control.get("usage_threshold") or gl.DEFAULT_THRESHOLD,
            "goal_gate": control.get("goal_gate") if control.get("goal_gate") in GATES
            else gl.DEFAULT_GATE,
            "models": {"lead": models.get("lead") or gl.DEFAULT_MODEL,
                       "subagent": models.get("subagent") or gl.DEFAULT_SUBAGENT_MODEL,
                       "check": models.get("check") or gl.DEFAULT_CHECK_MODEL,
                       "check_effort": models.get("check_effort") or gl.DEFAULT_CHECK_EFFORT,
                       "lead_effort": models.get("lead_effort"),
                       "subagent_effort": models.get("subagent_effort")},
            "providers": control.get("providers") or [],
            "opencode": shutil.which(oc.binary())}


def provider_problem(p):
    """What is wrong with a custom provider, or None."""
    if not isinstance(p, dict) or set(p) - {"id", "name", "base_url", "key_env", "models",
                                            "input_price", "output_price"}:
        return "a provider has id, base_url, key_env, models, and optionally input_price and output_price"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(p.get("id") or "")):
        return "a provider's id is lowercase letters, digits, - and _"
    if p.get("base_url") and not re.match(r"^https?://\S+$", str(p["base_url"])):
        return "%s: base_url is an http(s) URL, or empty for one of OpenCode's own providers" % p["id"]
    if p.get("key_env") and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(p["key_env"])):
        return "%s: key_env is the name of an environment variable, not the key" % p["id"]
    models = p.get("models")
    if not (isinstance(models, list) and models and all(isinstance(m, str) and m.strip()
                                                          and not m.startswith(p["id"] + "/")
                                                          for m in models)):
        return "%s: models is a list of its model names, without %s/ in front" % (p["id"], p["id"])
    for k in ("input_price", "output_price"):
        if k in p and p[k] is not None and not (isinstance(p[k], (int, float)) and p[k] >= 0):
            return "%s: %s is dollars per million tokens" % (p["id"], k)
    return None


def set_settings(main_root, changes):
    """Change some settings. Unknown keys and bad values are refused, all or none."""
    if not isinstance(changes, dict):
        raise Problem(400, "settings are an object")
    unknown = set(changes) - {"base", "usage_threshold", "goal_gate", "models", "providers", "runner",
                              "opencode_models"}
    if unknown:
        raise Problem(400, "unknown settings: %s" % ", ".join(sorted(unknown)))
    base = changes.get("base")
    if "base" in changes and base is not None and not re.fullmatch(r"[A-Za-z0-9._/-]+", str(base)):
        raise Problem(400, "base is not a branch name")
    if "usage_threshold" in changes and not (isinstance(changes["usage_threshold"], int)
                                             and 1 <= changes["usage_threshold"] <= 100):
        raise Problem(400, "usage_threshold is a whole number from 1 to 100")
    if "goal_gate" in changes and changes["goal_gate"] not in GATES:
        raise Problem(400, "goal_gate is one of %s" % ", ".join(GATES))
    models = changes.get("models") or {}
    efforts = ("check_effort", "lead_effort", "subagent_effort")
    if not isinstance(models, dict) or set(models) - {"lead", "subagent", "check"} - set(efforts):
        raise Problem(400, "models has lead, subagent, check and their efforts")
    if any(not (isinstance(v, str) and v.strip()) for k, v in models.items() if k not in efforts):
        raise Problem(400, "a model is a name")
    if "check_effort" in models and models["check_effort"] not in EFFORTS:
        raise Problem(400, "check_effort is one of %s" % ", ".join(EFFORTS))
    for k in ("lead_effort", "subagent_effort"):
        if models.get(k) not in (None, "") + EFFORTS:
            raise Problem(400, "%s is one of %s, or empty for the model's default" % (k, ", ".join(EFFORTS)))
    if "runner" in changes and changes["runner"] not in gl.RUNNERS:
        raise Problem(400, "runner is claude or opencode")
    oc_models = changes.get("opencode_models") or {}
    if not isinstance(oc_models, dict) or set(oc_models) - {"lead", "subagent", "check"}:
        raise Problem(400, "opencode_models has lead, subagent and check")
    if any(v and not (isinstance(v, str) and oc.is_opencode(v)) for v in oc_models.values()):
        raise Problem(400, "an OpenCode model is named provider/model")
    if any(m and oc.is_opencode(m) for k, m in models.items() if k in ("lead", "subagent", "check")):
        raise Problem(400, "a Claude Code model is a Claude model name, not provider/model")
    providers = changes.get("providers")
    if "providers" in changes:
        if not isinstance(providers, list):
            raise Problem(400, "providers is a list")
        problem = next((x for x in (provider_problem(p) for p in providers) if x), None)
        if problem:
            raise Problem(400, problem)
        if len({p["id"] for p in providers}) != len(providers):
            raise Problem(400, "two providers have the same id")
    with dm.control_file(main_root) as control:
        if "providers" in changes:
            control["providers"] = [{k: v for k, v in p.items() if v is not None} for p in providers]
        if oc_models:
            merged = dict(control.get("opencode") or {}, **oc_models)
            control["opencode"] = {k: v for k, v in merged.items() if v}
        if "runner" in changes:
            control["runner"] = changes["runner"]
        for key in ("base", "usage_threshold", "goal_gate"):
            if key in changes:
                control[key] = changes[key] or None
        if models:
            merged = dict(control.get("models") or {}, **models)
            control["models"] = {k: v for k, v in merged.items() if v not in (None, "")}
    return settings(main_root)


def dumps(value):
    return json.dumps(value, indent=1, default=str)
