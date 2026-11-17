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
    out["timeline"] = cards(timeline(log_text, data.get("created"), priced))
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


CALL_LINE = re.compile(r"^(lead|review|check|ci-fix|consult): ")


def card_summary(card):
    said = [l for l in card["lines"] if not CALL_LINE.match(l)]
    if card["kind"] == "round":
        tasks = card["tasks_title"].replace(" from the lead", "") if card.get("tasks_title") else ""
        return " · ".join(x for x in (tasks, " ".join(said)) if x)
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


def cards(steps):
    """The timeline as a person follows it: each step, with a round and the tasks it
    handed out as one card, in phases: Setup, Analysis and plan, Build, Verify and
    ship, PR review, Revision N. [{i, kind, phase, title, at, until, cost, summary,
    lines, tasks}]."""
    out, phase, revision, approved, i = [], "Setup", 0, False, 0
    while i < len(steps):
        s = steps[i]
        kind = kind_of(s["title"])
        p = phase
        if kind == "round" and phase == "Setup":
            p = "Analysis and plan"
        if (approved or kind == "tasks" or s["title"].startswith("Small change")) and \
                phase in ("Setup", "Analysis and plan"):
            p = "Build"
        approved = any("the plan is approved" in l for l in s["lines"])
        if re.match(r"^Syncing with main|^Running CI's static checks here$", s["title"]) and \
                "Verify" not in phase:
            p = "Verify and ship"
        if s["title"].startswith("Watching the PR"):
            p = "PR review"
        if s["title"].startswith("Review comments on the PR"):
            revision += 1
            p = "Revision %d" % revision
        if kind == "round" and phase == "Verify and ship":
            p = "Build"
        if kind == "round" and phase.startswith("Revision"):
            p = phase
        card = {"i": i, "kind": kind, "phase": p, "title": s["title"], "at": s["at"],
                "cost": s["cost"], "lines": list(s["lines"]), "tasks": None}
        phase = p
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if kind == "round" and nxt and kind_of(nxt["title"]) == "tasks":
            card["tasks"] = task_rows(nxt["lines"]) or None
            card["tasks_title"] = nxt["title"]
            card["tasks_lines"] = nxt["lines"]
            card["cost"] += nxt["cost"]
            i += 1
        elif kind == "tasks":
            card["tasks"] = task_rows(s["lines"]) or None
        card["summary"] = card_summary(card)
        i += 1
        card["until"] = steps[i]["at"] if i < len(steps) else None
        out.append(card)
    return out


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
    unknown = set(changes) - {"base", "usage_threshold", "goal_gate", "models", "providers"}
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
        for key in ("base", "usage_threshold", "goal_gate"):
            if key in changes:
                control[key] = changes[key] or None
        if models:
            merged = dict(control.get("models") or {}, **models)
            control["models"] = {k: v for k, v in merged.items() if v not in (None, "")}
    return settings(main_root)


def dumps(value):
    return json.dumps(value, indent=1, default=str)
