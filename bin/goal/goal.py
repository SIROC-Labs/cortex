#!/usr/bin/env python3
#
# goal.py — an Asana ticket, implemented autonomously on one branch, into one PR.
#
# The ask is the ticket: its description, its subtasks, its comments and its
# attachments, read once when the goal starts. Nothing is written back to Asana.
# A lead agent gets the ask and nothing else: it plans, starts its own sub-agents,
# reviewers and checkers as it sees fit, and keeps a journal so it can always pick
# the thread back up. This program is the harness around it. It calls the lead in
# rounds on the same session, pushes the branch after each, hands the person's
# answers back when the lead has a question only they can answer, has an
# independent checker confirm "done" against the ask, and pauses while the Claude
# subscription is at or over its usage threshold. It never merges anything.
#
#   cortex goal new <task URL or gid> [--base feature/x] [--start]   # prints the goal's id
#   cortex goal run <id>                                              # run or resume it
#
# A goal's state is `.cortex/state/<id>/` — `goal.json`, the journal, its
# questions and answers — the same place a task's run keeps its own, so the TUI
# answers both the same way.

import argparse
import datetime
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
START_TASK_DIR = os.path.join(os.path.dirname(HERE), "start-task")
sys.path.insert(0, START_TASK_DIR)
import start_task as st  # noqa: E402
from agent.base import extract_last_json_block, usage_from  # noqa: E402
from agent.claude_cli import parse_envelope  # noqa: E402

PROMPTS = os.path.join(HERE, "prompts")
GOAL_FILE = "goal.json"
JOURNAL_FILE = "journal.md"
LOG_FILE = "goal.log"
CALLS_FILE = "calls.json"
REPORT_FILE = "usage.txt"

DEFAULT_MODEL = "claude-opus-5-5"
# The lead's sub-agents mostly do narrow, well-briefed parts of the work. The lead
# can still ask for a stronger model for one that needs it.
DEFAULT_SUBAGENT_MODEL = "claude-sonnet-5-5"
# The checker only verifies and reports, and runs only when the lead says it is
# done: the one place where the strongest model costs little and catches most.
DEFAULT_CHECK_MODEL = "claude-fable-5-1"
DEFAULT_CHECK_EFFORT = "xhigh"
DEFAULT_THRESHOLD = 75
# Turns in one call before the runner takes the wheel back: to push, to read the
# usage, to see the lead is still getting somewhere. The session carries on.
MAX_TURNS = 200
# How often the usage is read while a call runs.
USAGE_CHECK = 300
# While paused, how often the usage is read again when no reset time is known.
PAUSE_CHECK = 900
# Rounds in a row that change nothing before the person is asked.
STALL_ROUNDS = 3
# Checks in a row that find gaps before the person is asked.
MAX_CHECKS = 4
ANSWER_CHECK = 2

CONTINUE = ("Continue the work. Read your journal if you need to remind yourself where "
            "you are, and end with the result block when you stop.")

# Goals this process started, so finished ones are reaped rather than left as
# zombies that still look alive.
_CHILDREN = []

LIVE = ("setting-up", "working", "checking", "waiting", "paused")
FINISHED = ("done", "failed", "stopped")


# --- pure helpers (unit-tested) ----------------------------------------------

def goal_id(key, name):
    """A goal's id: the ticket's key, and a few words of its name."""
    return "goal-%s-%s" % (st.slugify(key, max_words=3), st.slugify(name, max_words=4))


def title_of(goal, width=70):
    """The ticket's key and name, short enough for a row."""
    line = " ".join(x for x in ((goal or {}).get("key"), (goal or {}).get("name")) if x) or "goal"
    return line if len(line) <= width else line[:width - 1].rstrip() + "…"


def ask_from_ticket(task, url, subtasks=(), comments=(), attachments=()):
    """The ask, as the lead reads it: the ticket and everything hanging off it.
    `subtasks` are full tickets too; `attachments` are download entries with an
    absolute `path`."""
    out = ["# %s: %s" % (st.task_key(task), task.get("name") or ""), url, ""]
    if (task.get("description") or "").strip():
        out += [task["description"].strip(), ""]
    open_subtasks = [t for t in subtasks if not t.get("completed")]
    if open_subtasks:
        out += ["## Subtasks", "", "All of them are part of the ask.", ""]
        for t in open_subtasks:
            out += ["### %s: %s" % (st.task_key(t), t.get("name") or ""), ""]
            if (t.get("description") or "").strip():
                out += [t["description"].strip(), ""]
    said = [c for c in comments
            if (c.get("text") or "").strip() and not c["text"].startswith(st.BOT_MARK)]
    if said:
        out += ["## Comments", ""]
        out += ["- %s: %s" % (c.get("author") or "someone", c["text"].strip()) for c in said]
        out.append("")
    if attachments:
        out += ["## Attachments", ""]
        for a in attachments:
            out.append("- `%s`" % a["path"])
            if a.get("inline"):
                out += ["", "```", a["inline"].rstrip(), "```", ""]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


_LIMIT_LINE = re.compile(r"^(?P<name>[^:\n]+):\s*(?P<used>\d+)%\s*used(?:\s*·\s*resets\s+(?P<resets>.+))?$")
_RESET = re.compile(r"^(?:(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+at\s+)?"
                    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>[ap]m)"
                    r"(?:\s*\((?P<zone>[^)]+)\))?")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_reset(text, now):
    """When a limit resets, as epoch seconds, from "Oct 27 at 3:30pm (Africa/Johannesburg)"
    or "3:30pm (…)". None when it cannot be read."""
    m = _RESET.match((text or "").strip())
    if not m:
        return None
    zone = None
    if m.group("zone"):
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(m.group("zone").strip())
        except Exception:
            zone = None
    current = datetime.datetime.fromtimestamp(now, zone)
    hour = int(m.group("hour")) % 12 + (12 if m.group("half") == "pm" else 0)
    try:
        reset = current.replace(hour=hour, minute=int(m.group("minute") or 0),
                                second=0, microsecond=0)
        if m.group("month"):
            reset = reset.replace(month=_MONTHS.index(m.group("month")) + 1,
                                  day=int(m.group("day")))
            if reset < current - datetime.timedelta(days=1):
                reset = reset.replace(year=reset.year + 1)
        elif reset <= current:
            reset += datetime.timedelta(days=1)
    except ValueError:
        return None
    return reset.timestamp()


def parse_usage(text, now):
    """The limits `/usage` reports: [{name, used, resets_at}]."""
    out = []
    for line in (text or "").splitlines():
        m = _LIMIT_LINE.match(line.strip())
        if m:
            out.append({"name": m.group("name").strip(), "used": int(m.group("used")),
                        "resets_at": parse_reset(m.group("resets"), now)})
    return out


def over_threshold(limits, threshold):
    """The limit at or over the threshold that frees up last — the one a pause has
    to outlast — or None."""
    over = [l for l in limits or [] if l["used"] >= threshold]
    if not over:
        return None
    return max(over, key=lambda l: l["resets_at"] or 0)


def lead_report(structured):
    """What the lead's result block says: ("progress" | "done" | "question", block).
    A missing or unreadable block is progress — the lead stopped, not finished."""
    if not isinstance(structured, dict):
        return "progress", {}
    status = structured.get("status")
    if status == "question" and st.parse_agent_questions(structured):
        return "question", structured
    if status == "done":
        return "done", structured
    return "progress", structured


def check_verdict(structured):
    """The checker's verdict: (done, gaps). An unreadable verdict is not done."""
    if not isinstance(structured, dict):
        return False, ["the checker gave no verdict"]
    gaps = [str(g) for g in structured.get("gaps") or [] if str(g).strip()]
    return structured.get("verdict") == "done" and not gaps, gaps


def gaps_prompt(gaps):
    return ("An independent checker compared the branch with the ask and found that it "
            "is not finished:\n\n%s\n\nFix these, then report done again. If you think "
            "a gap is wrong, write why in the journal and say so in your summary."
            % "\n".join("- %s" % g for g in gaps))


def answer_prompt(questions, answer):
    lines = ["You asked the person:", ""]
    lines += ["- %s" % q["q"] for q in questions or []]
    lines += ["", "They answered:", "", answer.strip(), "", CONTINUE]
    return "\n".join(lines)


# --- what each call cost --------------------------------------------------------
#
# A call's own messages and each sub-agent's are in Claude Code's transcripts, with
# their model, tokens and times. The call's result says what each model cost in
# all; that is shared out by tokens, weighted as the API prices them.

TOKEN_KEYS = (("input", "input_tokens", "inputTokens"),
              ("output", "output_tokens", "outputTokens"),
              ("cache_read", "cache_read_input_tokens", "cacheReadInputTokens"),
              ("cache_write", "cache_creation_input_tokens", "cacheCreationInputTokens"))
TOKEN_WEIGHTS = {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25}
MODEL_NAMES = (("fable", "fable"), ("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku"))


def _when(text):
    try:
        return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def transcript_usage(lines, since=0):
    """From a transcript's JSON lines: {model, tokens, first, last}, counting each
    message once and only what came at or after `since`. None when nothing did."""
    seen, tokens, models, times = set(), dict.fromkeys(TOKEN_WEIGHTS, 0), {}, []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = _when(row.get("timestamp"))
        if at is None or at < since:
            continue
        times.append(at)
        message = row.get("message") or {}
        usage = message.get("usage")
        if not isinstance(usage, dict) or message.get("id") in seen:
            continue
        seen.add(message.get("id"))
        for name, key, _ in TOKEN_KEYS:
            tokens[name] += usage.get(key) or 0
        if message.get("model"):
            models[message["model"]] = models.get(message["model"], 0) + 1
    if not seen:
        return None
    return {"model": max(models, key=models.get) if models else None, "tokens": tokens,
            "first": min(times), "last": max(times)}


def weight(tokens):
    return sum(TOKEN_WEIGHTS[k] * (tokens.get(k) or 0) for k in TOKEN_WEIGHTS)


def unit_costs(model_usage):
    """{model: dollars per weighted token}, from a call result's `modelUsage`."""
    out = {}
    for model, use in (model_usage or {}).items():
        units = weight({name: use.get(camel) or 0 for name, _, camel in TOKEN_KEYS})
        if units and use.get("costUSD") is not None:
            out[model] = use["costUSD"] / units
    return out


def priced(entry, costs):
    cost = costs.get(entry.get("model"))
    return dict(entry, cost=None if cost is None else cost * weight(entry["tokens"]))


def short_model(model):
    return next((short for key, short in MODEL_NAMES if key in (model or "")), model or "?")


def _tokens(n):
    return "%.1fM" % (n / 1e6) if n >= 1e6 else "%dk" % round(n / 1e3) if n >= 1e3 else str(n)


def _span(seconds):
    seconds = int(seconds or 0)
    return ("%dh %02dm" % (seconds // 3600, seconds % 3600 // 60) if seconds >= 3600
            else "%dm %02ds" % (seconds // 60, seconds % 60) if seconds >= 60 else "%ds" % seconds)


def _cost(cost):
    return "≈ $%.2f" % cost if cost is not None else "cost unknown"


def _line(name, entry, width=46):
    tokens = entry["tokens"]
    total = sum(tokens.values())
    name = name if len(name) <= width else name[:width - 1] + "…"
    return "  %-*s %-7s %8s  %6s in · %5s out  %s" % (
        width, name, short_model(entry.get("model")), _span(entry.get("seconds")),
        _tokens(total - tokens["output"]), _tokens(tokens["output"]), _cost(entry.get("cost")))


def usage_report(calls):
    """The goal's usage, as the TUI shows it: totals by role, then each call with
    its sub-agents."""
    roles = {}
    for call in calls:
        for role, entry in [("lead" if call["label"] == "lead" else "checker", call["main"])] + [
                ("sub-agents", a) for a in call.get("subagents") or []]:
            r = roles.setdefault(role, {"tokens": dict.fromkeys(TOKEN_WEIGHTS, 0), "seconds": 0,
                                        "cost": 0.0, "count": 0, "models": set()})
            for k in TOKEN_WEIGHTS:
                r["tokens"][k] += entry["tokens"][k]
            r["seconds"] += entry.get("seconds") or 0
            r["count"] += 1
            r["models"].add(short_model(entry.get("model")))
            r["cost"] = None if r["cost"] is None or entry.get("cost") is None else r["cost"] + entry["cost"]
    total_cost = sum(c["cost"] or 0 for c in calls) if calls else 0
    known = all(c.get("cost") is not None for c in calls)
    out = ["Costs are at API prices: on a subscription, what the work would cost, not a bill.",
           "Time is each agent's own; sub-agents run alongside their call.", "",
           "All calls: %s · %s%s" % (_span(sum(c["main"].get("seconds") or 0 for c in calls)),
                                     _tokens(sum(sum(r["tokens"].values()) for r in roles.values())),
                                     " · ≈ $%.2f" % total_cost + ("" if known else " so far known")),
           ""]
    for role in ("lead", "sub-agents", "checker"):
        if role in roles:
            r = roles[role]
            entry = dict(r, model="/".join(sorted(r["models"])))
            out.append(_line("%s (%d)" % (role, r["count"]), entry))
    for call in calls:
        out += ["", "%s · %s%s · %s · %s" % (
            "Round %s" % call["round"] if call["label"] == "lead" else "Check %s" % call["round"],
            short_model(call["model"]), " %s effort" % call["effort"] if call.get("effort") else "",
            time.strftime("%a %H:%M", time.localtime(call["started"])), _cost(call.get("cost")))]
        out.append(_line(call["label"] + " itself", call["main"]))
        for agent in call.get("subagents") or []:
            out.append(_line("  " + (agent.get("description") or "sub-agent"), agent))
    return "\n".join(out) + "\n"


def read_call(session, since, model_usage=None, claude_dir=None):
    """(main, [sub-agents]) of a call, from its session's transcripts: each with
    model, tokens, seconds and cost."""
    base = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    found = glob.glob(os.path.join(base, "projects", "*", session + ".jsonl"))
    if not found:
        return None, []
    costs = unit_costs(model_usage)

    def entry(path, **extra):
        with open(path) as f:
            use = transcript_usage(f, since)
        if not use:
            return None
        return priced(dict(extra, model=use["model"], tokens=use["tokens"],
                           seconds=use["last"] - use["first"]), costs)

    main = entry(found[0])
    agents = []
    for path in sorted(glob.glob(os.path.join(found[0][:-len(".jsonl")], "subagents", "agent-*.jsonl"))):
        try:
            with open(path[:-len(".jsonl")] + ".meta.json") as f:
                meta = json.load(f)
        except (IOError, OSError, ValueError):
            meta = {}
        agent = entry(path, description=meta.get("description"), depth=meta.get("spawnDepth"))
        if agent:
            agents.append(agent)
    if main and costs:
        # The call's own share is what its model cost, less its sub-agents on that model.
        same = sum(a["cost"] or 0 for a in agents if a["model"] == main["model"])
        own = (model_usage.get(main["model"]) or {}).get("costUSD")
        if own is not None:
            main["cost"] = max(0.0, own - same)
    agents.sort(key=lambda a: a.get("seconds") or 0, reverse=True)
    return main, agents


# --- state -------------------------------------------------------------------

class Goal(object):
    def __init__(self, main_root, gid):
        self.main_root = main_root
        self.id = gid
        self.state = st.State(main_root, gid)

    def read(self):
        return self.state.read(GOAL_FILE, {})

    def update(self, **fields):
        data = self.read()
        data.update(fields)
        data["updated"] = time.time()
        self.state.write(GOAL_FILE, data)
        return data

    @property
    def journal(self):
        return self.state.path(JOURNAL_FILE)

    @property
    def log(self):
        return self.state.path(LOG_FILE)


def task_url(gid, board=None):
    return "https://app.asana.com/0/%s/%s" % (board or 0, gid)


def settings_from(control):
    """The models a new goal uses, from the repo's control file (the TUI's Setup
    tab): {model, subagent_model, check_model, check_effort}."""
    models = (control or {}).get("models") or {}
    return {"model": models.get("lead") or DEFAULT_MODEL,
            "subagent_model": models.get("subagent") or DEFAULT_SUBAGENT_MODEL,
            "check_model": models.get("check") or DEFAULT_CHECK_MODEL,
            "check_effort": models.get("check_effort") or DEFAULT_CHECK_EFFORT}


def create(main_root, ref, key, name, url=None, base=None, threshold=DEFAULT_THRESHOLD,
           model=DEFAULT_MODEL, subagent_model=DEFAULT_SUBAGENT_MODEL,
           check_model=DEFAULT_CHECK_MODEL, check_effort=DEFAULT_CHECK_EFFORT, now=None):
    """Write a new goal for the ticket `ref`. Returns its id; nothing runs yet, and the
    ticket itself is read when it starts."""
    gid, n = goal_id(key, name), 1
    while os.path.isdir(Goal(main_root, gid).state.dir):
        n += 1
        gid = "%s-%d" % (goal_id(key, name), n)
    goal = Goal(main_root, gid)
    goal.state.ensure()
    goal.update(id=gid, ref=ref, key=key, name=name, url=url or task_url(ref), base=base,
                threshold=threshold, model=model, subagent_model=subagent_model,
                check_model=check_model or model, check_effort=check_effort,
                created=now or time.time(), status="new",
                round=0)
    return gid


def find_goal(main_root, ref):
    """The goal on the list for the ticket `ref`, if there is one."""
    return next((g for g in list_goals(main_root) if g.get("ref") == ref), None)


def launch(main_root, gid):
    """Run a goal in its own session, so closing the TUI leaves it going. Returns
    its pid."""
    goal = Goal(main_root, gid)
    logfile = open(goal.log, "a")
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run", gid,
                             "--repo", main_root], cwd=main_root, stdin=subprocess.DEVNULL,
                            stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
    logfile.close()
    _CHILDREN.append(proc)
    goal.update(pid=proc.pid, status="setting-up", reason=None)
    return proc.pid


def list_goals(main_root):
    """Every goal in the repo not cleared from the list, newest first, with whether
    its process still runs, where its log is, and what it is asking you, if anything."""
    for proc in list(_CHILDREN):
        if proc.poll() is not None:
            _CHILDREN.remove(proc)
    root = os.path.join(main_root, st.CORTEX_DIRNAME, st.STATE_DIRNAME)
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if not name.startswith("goal-"):
            continue
        goal = Goal(main_root, name)
        data = goal.read()
        if data and not data.get("cleared"):
            data["alive"] = bool(data.get("pid")) and st._pid_alive(data["pid"])
            data["log"] = goal.log
            data["awaiting"] = goal.state.read("awaiting.json")
            out.append(data)
    return sorted(out, key=lambda g: -(g.get("created") or 0))


# --- the run -----------------------------------------------------------------

class Stopped(Exception):
    pass


class Runner(object):
    def __init__(self, main_root, gid):
        self.main_root = main_root
        self.goal = Goal(main_root, gid)
        self.data = self.goal.read()
        if not self.data:
            st.die("no goal %s in %s" % (gid, main_root), escalate=False)
        self.child = None
        signal.signal(signal.SIGTERM, self.on_term)

    def on_term(self, *_):
        if self.child and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except OSError:
                pass
        raise Stopped()

    def set(self, **fields):
        self.data = self.goal.update(**fields)

    # setup

    def read_ticket(self):
        """The ask, from the ticket as it is now. Read once, when the goal starts."""
        st.step("Reading the ticket")
        ref = self.data["ref"]
        task = st.asana(["task", "get", ref], cwd=self.main_root)
        subtasks = [dict(st.asana(["task", "get", t["ref"]], cwd=self.main_root) or {},
                         completed=t.get("completed"))
                    for t in st.asana(["task", "subtasks", ref], cwd=self.main_root) or []
                    if not t.get("completed")]
        comments = st.asana(["comment", "list", ref], cwd=self.main_root) or []
        attachments = []
        for att in st.asana(["task", "attachments", ref], cwd=self.main_root) or []:
            entry = st.download_attachment(att, self.goal.state.path("attachments"))
            if entry:
                attachments.append(dict(entry, path=self.goal.state.path(entry["path"])))
        st.info("%d subtask(s) · %d comment(s) · %d attachment(s)"
                % (len(subtasks), len(comments), len(attachments)))
        self.set(ask=ask_from_ticket(task, self.data["url"], subtasks, comments, attachments),
                 name=task.get("name") or self.data.get("name"))

    def set_up(self):
        if not self.data.get("ask"):
            os.makedirs(self.goal.state.path("attachments"), exist_ok=True)
            self.read_ticket()
        if self.data.get("worktree") and os.path.isdir(self.data["worktree"]):
            return
        st.step("Setting up")
        key, name = self.data["key"], self.data["name"]
        base = st.resolve_base(self.main_root, self.data.get("base"))
        branch = "%s/goal-%s" % (key, st.slugify(name))
        worktree = st.worktree_path(self.main_root, self.goal.id)
        with st.repo_lock(self.main_root):
            st.git(["fetch", "origin"], cwd=self.main_root, check=False)
            st.git(["worktree", "add", worktree, "-b", branch, base], cwd=self.main_root)
        st.git(["commit", "--allow-empty", "-m", "%s :: start the goal" % key], cwd=worktree)
        st.git(["push", "-u", "origin", branch], cwd=worktree)
        st.info("created %s off %s in %s" % (branch, base, worktree))
        pr_url, error = st.create_draft_pr(key, name, self.data["url"], base, branch, worktree)
        if pr_url:
            st.info("draft PR: %s" % pr_url)
        else:
            st.warn("could not open the draft PR: %s" % error)
        self.set(base=base.replace("origin/", "", 1), branch=branch, worktree=worktree,
                 pr_url=pr_url)

    # usage

    def usage(self):
        code, out, _ = st.run(["claude", "-p", "/usage", "--output-format", "json"],
                              cwd=self.main_root, check=False)
        text = out
        try:
            text = json.loads(out).get("result") or ""
        except (ValueError, AttributeError):
            pass
        limits = parse_usage(text, time.time())
        if limits:
            self.set(limits=limits, limits_at=time.time())
        return limits

    def wait_for_usage(self):
        """Pause while the subscription is at or over the threshold."""
        while True:
            worst = over_threshold(self.usage(), self.data.get("threshold", DEFAULT_THRESHOLD))
            if not worst:
                if self.data.get("status") == "paused":
                    st.info("usage is back under %d%% — going on" % self.data["threshold"])
                return
            until = worst["resets_at"] or time.time() + PAUSE_CHECK
            what = "%s at %d%%" % (worst["name"], worst["used"])
            if self.data.get("status") != "paused":
                st.step("Paused — %s" % what)
                st.info("resumes at %s" % time.strftime("%a %H:%M", time.localtime(until)))
            self.set(status="paused", doing="paused — %s, until %s"
                     % (what, time.strftime("%a %H:%M", time.localtime(until))))
            time.sleep(max(60, min(until - time.time() + 60, PAUSE_CHECK)))

    # agent calls

    def call(self, prompt, session, resume, label, model=None, effort=None):
        """One `claude -p` call. Returns (structured, stop_reason, error). A call
        cut off because the usage crossed the threshold returns stop_reason
        "usage"; its session carries on afterwards."""
        model = model or self.data["model"]
        cmd = ["claude", "-p", "--output-format", "json", "--model", model,
               "--permission-mode", "bypassPermissions", "--max-turns", str(MAX_TURNS),
               "--add-dir", self.goal.state.dir]
        cmd += ["--effort", effort] if effort else []
        cmd += ["--resume", session] if resume else ["--session-id", session]
        st.info("%s: calling claude%s" % (label, " (continuing)" if resume else ""))
        started = time.time()
        env = dict(os.environ, CLAUDE_CODE_SUBAGENT_MODEL=self.data.get(
            "subagent_model") or DEFAULT_SUBAGENT_MODEL)
        self.child = subprocess.Popen(cmd + [prompt], cwd=self.data["worktree"], env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, start_new_session=True)
        threshold = self.data.get("threshold", DEFAULT_THRESHOLD)
        while True:
            try:
                out, err = self.child.communicate(timeout=USAGE_CHECK)
                break
            except subprocess.TimeoutExpired:
                worst = over_threshold(self.usage(), threshold)
                if worst:
                    st.warn("%s at %d%% — stopping the call; it carries on later"
                            % (worst["name"], worst["used"]))
                    os.killpg(self.child.pid, signal.SIGTERM)
                    self.child.communicate()
                    self.child = None
                    self.record_call(label, model, effort, session, started)
                    return None, "usage", None
        code, self.child = self.child.returncode, None
        self.record_call(label, model, effort, session, started, out)
        text, telemetry = parse_envelope(out.decode("utf-8", "replace"))
        usage = telemetry.get("usage")
        if usage:
            at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.goal.state.write(st.USAGE_FILE, st.add_usage(
                self.goal.state.read(st.USAGE_FILE), usage, label, model, at))
        if telemetry.get("ok") is False or not out.strip():
            return None, None, (telemetry.get("error") or err.decode("utf-8", "replace").strip()
                                or "claude exited %d" % code)
        st.info("%s: %s turns" % (label, telemetry.get("turns") or "?"))
        return extract_last_json_block(text), telemetry.get("stop_reason"), None

    def record_call(self, label, model, effort, session, started, out=b""):
        """Note what a call cost, by agent, and rewrite the goal's usage report."""
        try:
            envelope = json.loads(out.decode("utf-8", "replace")) if out.strip() else {}
        except ValueError:
            envelope = {}
        main, agents = read_call(session, started - 1, envelope.get("modelUsage"))
        if not main:
            return
        calls = self.goal.state.read(CALLS_FILE) or []
        rounds = self.data.get("round") if label == "lead" else len(
            [c for c in calls if c["label"] != "lead"]) + 1
        calls.append({"label": label, "round": rounds, "model": model, "effort": effort,
                      "started": started, "cost": envelope.get("total_cost_usd"),
                      "main": dict(main, seconds=time.time() - started), "subagents": agents})
        self.goal.state.write(CALLS_FILE, calls)
        with open(self.goal.state.path(REPORT_FILE), "w") as f:
            f.write(usage_report(calls))
        self.set(cost=sum(c.get("cost") or 0 for c in calls))

    def lead(self, prompt):
        """Call the lead on its session, through failures and pauses. Returns
        (report, block)."""
        failures = 0
        while True:
            self.wait_for_usage()
            session = self.data.get("session")
            resume = bool(session) and self.data.get("session_used")
            if not session:
                session = str(uuid.uuid4())
                self.set(session=session)
            self.set(status="working", doing="round %d" % self.data["round"])
            block, stop, error = self.call(prompt, session, resume, "lead")
            self.set(session_used=True)
            if error:
                pause = st.limit_pause(error, time.time())
                if pause:
                    st.wait_out_limit(self.goal.state, "lead", *pause)
                    continue
                if resume and failures == 0 and re.search(r"session|conversation", error, re.I):
                    st.warn("could not continue the session (%s) — starting a new one" % error)
                    self.set(session=None, session_used=False)
                    prompt = self.first_prompt() + "\n\n" + CONTINUE
                    failures += 1
                    continue
                failures += 1
                if failures < 3:
                    st.warn("the call failed (%s) — trying again" % error.splitlines()[0][:200])
                    time.sleep(30)
                    continue
                answer = self.ask_problem("The lead agent keeps failing", error)
                prompt, failures = "The person says:\n\n%s\n\n%s" % (answer, CONTINUE), 0
                continue
            if stop in ("usage", "max_turns"):
                return "progress", {}
            return lead_report(block)

    def check(self):
        """An independent check of the branch against the ask: (done, gaps)."""
        self.wait_for_usage()
        self.set(status="checking", doing="checking the branch against the ask")
        st.step("Checking against the ask")
        prompt = render(os.path.join(PROMPTS, "check.md"), **self.fields())
        block, stop, error = self.call(prompt, str(uuid.uuid4()), False, "check",
                                       self.data.get("check_model"), self.data.get("check_effort"))
        # Files the checks leave behind — caches, reports — are not changes to the work.
        _, dirty, _ = st.git(["status", "--porcelain", "--untracked-files=no"],
                             cwd=self.data["worktree"], check=False)
        if dirty:
            st.git(["stash", "push", "-m", "changes the checker made"],
                   cwd=self.data["worktree"], check=False)
            st.warn("the checker changed files — they are set aside in `git stash`")
        if error or stop == "usage":
            return False, ["the check did not finish: %s" % (error or "usage threshold")]
        done, gaps = check_verdict(block)
        st.info("verdict: %s" % ("done" if done else "%d gap(s)" % len(gaps)))
        for gap in gaps:
            st.info("- %s" % gap)
        return done, gaps

    def fields(self):
        return {"ask": self.data["ask"], "branch": self.data["branch"],
                "base": self.data["base"], "journal": self.goal.journal,
                "subagent_model": self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL}

    def first_prompt(self):
        return render(os.path.join(PROMPTS, "lead.md"), **self.fields())

    # the person

    def wait_for_answer(self, record):
        """Leave a question for the person and wait for their answer from the TUI."""
        asked_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        pending = self.goal.state.read("awaiting.json") or {}
        if pending.get("asked_at") and pending.get("kind") == record["kind"]:
            asked_at = pending["asked_at"]
        else:
            self.goal.state.write("awaiting.json", dict(record, asked_at=asked_at))
        self.set(status="waiting", doing="waiting on you")
        st.info("waiting on you — the question is on the TUI's Runs tab")
        while True:
            text = st.local_answer(self.goal.state.read(st.ANSWER_FILE), asked_at)
            if text:
                self.goal.state.remove(st.ANSWER_FILE)
                self.goal.state.remove("awaiting.json")
                st.info("answered")
                return text
            time.sleep(ANSWER_CHECK)

    def ask_questions(self, questions):
        st.step("Asking you")
        for q in questions:
            st.info("Q: %s" % q["q"])
        return self.wait_for_answer({"kind": "questions", "label": "lead", "questions": questions})

    def ask_problem(self, headline, detail=None):
        st.step("Stopped — %s" % headline)
        return self.wait_for_answer({"kind": "problem", "headline": headline,
                                     "detail": (detail or "").strip()[-1500:] or None})

    # git

    def push(self):
        worktree, branch = self.data["worktree"], self.data["branch"]
        while True:
            code, _, err = st.git(["push", "-u", "origin", branch], cwd=worktree, check=False)
            if code == 0:
                return
            self.ask_problem("could not push %s" % branch, err)

    def head(self):
        _, sha, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
        return "%s\n%s" % (sha, st.worktree_fingerprint(self.data["worktree"]))

    def finish(self, block):
        st.step("Finishing")
        worktree, pr_url = self.data["worktree"], self.data.get("pr_url")
        self.push()
        if pr_url:
            body = "## Task\n%s\n\n%s\n" % (self.data["url"], block.get("summary") or "")
            st.run(["gh", "pr", "edit", pr_url, "--body", body], cwd=worktree, check=False)
            comment = (block.get("walkthrough") or "").strip()
            if (block.get("checks") or "").strip():
                comment += "\n\n## Checks\n\n%s" % block["checks"].strip()
            if comment.strip():
                st.run(["gh", "pr", "comment", pr_url, "--body", st.mark(comment.strip())],
                       cwd=worktree, check=False)
            st.run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
            st.info("PR ready: %s" % pr_url)
        self.set(status="done", doing=block.get("summary") or "done", finished=time.time())

    # the loop

    def run(self):
        try:
            self.set(pid=os.getpid(), status="setting-up", reason=None)
            self.set_up()
            pending = self.goal.state.read("awaiting.json") or {}
            if pending.get("kind") == "questions":
                prompt = answer_prompt(pending.get("questions"),
                                       self.wait_for_answer(pending))
            elif pending.get("kind") == "problem":
                prompt = "The person says:\n\n%s\n\n%s" % (self.wait_for_answer(pending), CONTINUE)
            else:
                prompt = self.first_prompt() if not self.data.get("session_used") else CONTINUE
            unchanged, checks, before = 0, 0, self.head()
            while True:
                self.set(round=self.data.get("round", 0) + 1)
                st.step("Round %d" % self.data["round"])
                report, block = self.lead(prompt)
                if block.get("summary"):
                    st.info(block["summary"])
                self.push()
                after = self.head()
                unchanged = unchanged + 1 if after == before else 0
                before = after
                if report == "question":
                    prompt = answer_prompt(block["questions"], self.ask_questions(block["questions"]))
                    continue
                if report == "done":
                    done, gaps = self.check()
                    if done:
                        self.finish(block)
                        return 0
                    checks += 1
                    if checks >= MAX_CHECKS:
                        answer = self.ask_problem(
                            "the checker still finds gaps after %d tries" % checks, "\n".join(gaps))
                        prompt, checks = "The person says:\n\n%s\n\n%s" % (answer, gaps_prompt(gaps)), 0
                    else:
                        prompt = gaps_prompt(gaps)
                    continue
                if unchanged >= STALL_ROUNDS:
                    answer = self.ask_problem("%d rounds in a row changed nothing" % unchanged)
                    prompt, unchanged = "The person says:\n\n%s\n\n%s" % (answer, CONTINUE), 0
                    continue
                prompt = CONTINUE
        except Stopped:
            self.set(status="stopped", reason="stopped", doing="stopped")
            return 1
        except st.Failure as e:
            self.set(status="failed", reason=str(e), doing=str(e).splitlines()[0][:200])
            st.warn(str(e))
            return 1
        finally:
            self.set(pid=None)


def render(path, **kwargs):
    with open(path) as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


# --- command line --------------------------------------------------------------

def main(argv):
    parser = argparse.ArgumentParser(prog="cortex goal", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="make a goal from an Asana ticket")
    new.add_argument("task", help="the ticket: its URL or gid")
    new.add_argument("--base", help="the branch to build on and open the PR into")
    new.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                     help="pause while any usage limit is at or over this percentage")
    new.add_argument("--model", default=DEFAULT_MODEL, help="the lead's model")
    new.add_argument("--subagent-model", default=DEFAULT_SUBAGENT_MODEL,
                     help="the default for the lead's sub-agents; it can ask for another")
    new.add_argument("--check-model", default=DEFAULT_CHECK_MODEL, help="the checker's model")
    new.add_argument("--check-effort", default=DEFAULT_CHECK_EFFORT,
                     choices=("low", "medium", "high", "xhigh", "max"), help="the checker's effort")
    new.add_argument("--start", action="store_true", help="start it in the background")
    new.add_argument("--repo", default=".")
    run = sub.add_parser("run", help="run or resume a goal in the foreground")
    run.add_argument("id")
    run.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    main_root = st.main_repo_root(os.path.abspath(args.repo))
    if args.cmd == "new":
        ref = st.asana(["ref", "parse", args.task], cwd=main_root)
        if not ref:
            parser.error("%r is not an Asana task" % args.task)
        ref = str(ref).strip()
        existing = find_goal(main_root, ref)
        if existing:
            parser.error("the ticket is already the goal %s" % existing["id"])
        task = st.asana(["task", "get", ref], cwd=main_root)
        gid = create(main_root, ref, st.task_key(task), task.get("name"), base=args.base,
                     threshold=args.threshold, model=args.model,
                     subagent_model=args.subagent_model, check_model=args.check_model,
                     check_effort=args.check_effort)
        if args.start:
            launch(main_root, gid)
        print(gid)
        return 0
    return Runner(main_root, args.id).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
