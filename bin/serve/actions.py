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
for tool in ("lib", "goal", "tui"):
    if os.path.join(BIN, tool) not in sys.path:
        sys.path.insert(0, os.path.join(BIN, tool))
import control as dm  # noqa: E402
import core as st  # noqa: E402
import goal as gl  # noqa: E402
import goal_view as gv  # noqa: E402
import repos as rp  # noqa: E402

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
    return out


def goals(main_root):
    """The repo's goals, newest first, each followed by its parts; a goal's cost and
    agents include its parts'."""
    listed = gl.list_goals(main_root)
    rates = gl.repo_rates(main_root) if listed else {}
    processes = gv.claude_processes() if any(g.get("alive") for g in listed) else {}
    out = [summary(main_root, g, rates, processes) for g in listed]
    for g in out:
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
    return sorted("%s/%s" % (sub, n) for n in os.listdir(folder)) if os.path.isdir(folder) else []


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
    log_text = _text(goal.log) or ""
    out["log_size"] = len(log_text.encode())
    out["timeline"] = timeline(log_text, data.get("created"), priced)
    out["live"] = gv.running_agents(data, processes=gv.claude_processes()) if data["alive"] else []
    out["tasks_now"] = gv.tasks_now(data) or []
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
    """Start a goal on a prompt. `files` are local paths, or {name, data} with the
    file's bytes in base64. Returns the goal's id."""
    if not (prompt or "").strip():
        raise Problem(400, "a goal needs a prompt")
    add_repo(main_root)
    tmp = tempfile.mkdtemp(prefix="cond-upload-")
    try:
        paths = []
        for n, f in enumerate(files or []):
            if isinstance(f, str):
                if not os.path.isfile(os.path.expanduser(f)):
                    raise Problem(400, "no file %s" % f)
                paths.append(os.path.expanduser(f))
                continue
            name = os.path.basename(str((f or {}).get("name") or "file-%d" % (n + 1))) or "file"
            try:
                body = base64.b64decode((f or {}).get("data") or "", validate=True)
            except (ValueError, TypeError):
                raise Problem(400, "%s is not base64" % name)
            if len(body) > MAX_FILE_BYTES:
                raise Problem(400, "%s is over %d MB" % (name, MAX_FILE_BYTES // 2 ** 20))
            folder = os.path.join(tmp, str(n))
            os.makedirs(folder)
            paths.append(os.path.join(folder, name))
            with open(paths[-1], "wb") as out:
                out.write(body)
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


def answer(main_root, gid, text):
    """Hand the person's answer to the goal waiting on it."""
    goal, _ = the_goal(main_root, gid)
    waiting = goal.state.read("awaiting.json") or {}
    if not waiting.get("asked_at"):
        raise Problem(409, "the goal is not waiting on an answer")
    if not (text or "").strip():
        raise Problem(400, "an empty answer")
    goal.state.write(st.ANSWER_FILE, {"asked_at": waiting["asked_at"], "text": text.strip(),
                                      "at": time.time()})
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
    return {"base": control.get("base"),
            "usage_threshold": control.get("usage_threshold") or gl.DEFAULT_THRESHOLD,
            "goal_gate": control.get("goal_gate") if control.get("goal_gate") in GATES
            else gl.DEFAULT_GATE,
            "models": {"lead": models.get("lead") or gl.DEFAULT_MODEL,
                       "subagent": models.get("subagent") or gl.DEFAULT_SUBAGENT_MODEL,
                       "check": models.get("check") or gl.DEFAULT_CHECK_MODEL,
                       "check_effort": models.get("check_effort") or gl.DEFAULT_CHECK_EFFORT}}


def set_settings(main_root, changes):
    """Change some settings. Unknown keys and bad values are refused, all or none."""
    if not isinstance(changes, dict):
        raise Problem(400, "settings are an object")
    unknown = set(changes) - {"base", "usage_threshold", "goal_gate", "models"}
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
    if not isinstance(models, dict) or set(models) - {"lead", "subagent", "check", "check_effort"}:
        raise Problem(400, "models has lead, subagent, check and check_effort")
    if any(not (isinstance(v, str) and v.strip()) for k, v in models.items() if k != "check_effort"):
        raise Problem(400, "a model is a name")
    if "check_effort" in models and models["check_effort"] not in EFFORTS:
        raise Problem(400, "check_effort is one of %s" % ", ".join(EFFORTS))
    with dm.control_file(main_root) as control:
        for key in ("base", "usage_threshold", "goal_gate"):
            if key in changes:
                control[key] = changes[key] or None
        if models:
            control["models"] = dict(control.get("models") or {}, **models)
    return settings(main_root)


def dumps(value):
    return json.dumps(value, indent=1, default=str)
