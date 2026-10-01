#!/usr/bin/env python3
#
# engine.py — the loop that works a set of Asana tasks through start-task to merge.
#
# Shared by `run-milestone` (the set is a board's milestones) and the `tui` daemon
# (the set is whatever is queued). A subclass says which tasks are in scope and
# where they go; everything else — readiness, sprint and assignment, launching
# start-task, watching PRs, revise on feedback, parking conflicts, completing on
# merge, reconciling after a restart — is here, as plain code. No model is called.
#
# Dependencies: Python 3 stdlib, git, gh, and start-task (sibling directory).

import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
START_TASK_DIR = os.path.join(os.path.dirname(HERE), "start-task")
START_TASK = os.path.join(START_TASK_DIR, "start_task.py")
ASANA = os.path.join(START_TASK_DIR, "asana.py")
sys.path.insert(0, START_TASK_DIR)
import start_task as st  # noqa: E402

TICK = 15
REFRESH_EVERY = 300
PR_POLL_START = 60
PR_POLL_CAP = 600
# A parked conflict is waiting on a person to type a comment, so it is looked at
# often rather than backed off.
CONFLICT_POLL = 60

# A record in one of these has work in flight or a PR being watched — the loop is
# not finished while any task is in one. A conflicting PR is watched only for a
# resolve request, and holds up nothing but its own dependents.
LIVE = ("running", "awaiting", "revising", "pr_open", "conflict")
# A record in one of these is never launched again by the loop.
SETTLED = LIVE + ("merged", "failed", "stopped")

# What a PR comment has to say for a parked conflict to be resolved.
RESOLVE_TRIGGER = "please resolve"


def log(msg):
    sys.stdout.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


class Stop(Exception):
    pass


# --- pure helpers (unit-tested) ---------------------------------------------

_PROJECT_RE = re.compile(r"/project/(\d+)")
_ZERO_RE = re.compile(r"^/0/(\d+)(?:/|$)")


def parse_project_ref(ref):
    """A board's gid from its Asana URL, or a bare gid; None otherwise."""
    from urllib.parse import urlparse
    ref = (ref or "").strip()
    if re.fullmatch(r"\d+", ref):
        return ref
    path = urlparse(ref).path
    m = _PROJECT_RE.search(path) or _ZERO_RE.search(path)
    return m.group(1) if m else None


_PR_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(url):
    """(owner, repo, number) of a GitHub PR URL, or None."""
    m = _PR_RE.search(url or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def blockers(gid, tasks, records, me_gid):
    """Why a task cannot start now, as readable strings. Empty means ready —
    unless its record says it already ran, which the caller checks."""
    task = tasks[gid]
    out = []
    if task.get("completed"):
        return ["completed"]
    status = (task.get("status") or "").strip()
    if status.lower() == "canceled":
        return ["canceled"]
    if status.lower() not in st.NOT_STARTED:
        out.append("status is %s" % (status or "unset"))
    for dep in task.get("deps") or []:
        if dep.get("completed"):
            continue
        name = dep.get("name") or dep.get("ref")
        if dep.get("ref") not in tasks:
            out.append("waits on %s (not in this run)" % name)
        elif (records.get(dep.get("ref")) or {}).get("phase") == "failed":
            out.append("waits on %s (failed)" % name)
        else:
            out.append("waits on %s" % name)
    assignee = task.get("assignee_gid")
    if assignee and me_gid and assignee != me_gid:
        out.append("assigned to %s" % (task.get("assignee") or "someone else"))
    return out


def ready_tasks(tasks, records, me_gid):
    """Gids that can start now, in milestone order."""
    return [gid for gid in tasks
            if (records.get(gid) or {}).get("phase") not in SETTLED
            and not blockers(gid, tasks, records, me_gid)]


def _is_bot(user):
    user = user or {}
    return user.get("type") == "Bot" or (user.get("login") or "").endswith("[bot]")


def collect_feedback(reviews, review_comments, issue_comments, handled):
    """New review feedback on a PR, as [(id, heading, body)].

    A submitted review's own text, every inline comment, and every top-level
    comment count — but never one the run posted (it carries the mark), one from
    a bot account, or one already handled.
    """
    handled = set(handled or ())
    out = []
    for r in reviews or []:
        fid = "review:%s" % r.get("id")
        body = (r.get("body") or "").strip()
        if (fid in handled or r.get("state") == "PENDING" or not body
                or st.is_marked(body) or _is_bot(r.get("user"))):
            continue
        out.append((fid, "Review by @%s (%s)" % ((r.get("user") or {}).get("login"),
                                                 r.get("state")), body))
    for c in review_comments or []:
        fid = "inline:%s" % c.get("id")
        body = (c.get("body") or "").strip()
        if fid in handled or not body or st.is_marked(body) or _is_bot(c.get("user")):
            continue
        where = "`%s`" % c.get("path")
        if c.get("line"):
            where += " line %s" % c["line"]
        out.append((fid, "%s — @%s" % (where, (c.get("user") or {}).get("login")), body))
    for c in issue_comments or []:
        fid = "comment:%s" % c.get("id")
        body = (c.get("body") or "").strip()
        if fid in handled or not body or st.is_marked(body) or _is_bot(c.get("user")):
            continue
        out.append((fid, "Comment by @%s" % (c.get("user") or {}).get("login"), body))
    return out


def render_feedback(items):
    lines = []
    for _, heading, body in items:
        lines += ["### %s" % heading, "", body, ""]
    return "\n".join(lines).strip() + "\n"


def resolve_request(items):
    """The first feedback item asking for a parked conflict to be resolved."""
    for item in items:
        if RESOLVE_TRIGGER in item[2].lower():
            return item
    return None


def render_resolve(item):
    return ("The PR conflicts with its base branch, and the operator asked for that to "
            "be resolved. Merge the base into the branch and resolve the conflicts, "
            "keeping both sides' intent.\n\n### %s\n\n%s\n" % (item[1], item[2]))


def outcome_phase(code, outcome):
    """What a finished start-task process means for the loop: (phase, reason)."""
    outcome = outcome or {}
    if code == st.EXIT_OK and outcome.get("status") in ("shipped", "revised"):
        return "pr_open", None
    if code == st.EXIT_AWAITING:
        return "awaiting", outcome.get("reason")
    return "failed", outcome.get("reason") or "start-task exited with code %s" % code


def reconcile(record, outcome, live_pid):
    """A record as it stands after a restart, from what start-task left behind.

    `outcome` is the task's last `outcome.json`; `live_pid` a process still
    working the task, or None. A run that was going when the loop died is
    relaunched (start-task resumes it); one that finished meanwhile is taken at
    its word; one still going is adopted rather than started twice.
    """
    record = dict(record or {})
    phase = record.get("phase")
    record.pop("pid", None)
    if live_pid:
        if phase not in ("running", "awaiting", "revising"):
            record["phase"] = "running"
        record["pid"] = live_pid
        return record
    newer = bool(outcome) and outcome.get("at", 0) > record.get("since", 0)
    if newer and phase not in ("merged", "stopped"):
        if outcome.get("status") in ("shipped", "revised") and outcome.get("pr_url"):
            record.update(phase="pr_open", pr_url=outcome["pr_url"],
                          branch=outcome.get("branch"))
            if phase == "revising":
                record["handled"] = sorted(set(record.get("handled") or [])
                                           | set(record.get("inflight") or []))
            record.pop("inflight", None)
            return record
        if outcome.get("status") == "failed" and phase in ("running", "awaiting", "revising"):
            record.update(phase="failed", reason=outcome.get("reason"))
            return record
    if phase in ("running", "awaiting"):
        record["phase"] = None
    elif phase == "revising":
        record["phase"] = "pr_open"
        record.pop("inflight", None)
    return record


def describe(gid, tasks, records, me_gid):
    """One line of status for a task."""
    record = records.get(gid) or {}
    phase = record.get("phase")
    task = tasks[gid]
    if phase == "merged":
        return "merged"
    if task.get("completed"):
        return "completed"
    if phase == "running":
        return "running"
    if phase == "awaiting":
        return "awaiting Justin"
    if phase == "revising":
        return "revising after review"
    if phase == "pr_open":
        return "PR open"
    if phase == "conflict":
        return ("PR conflicts with its base — parked; comment `%s` on the PR to have it "
                "resolved" % RESOLVE_TRIGGER)
    if phase == "failed":
        return "failed: %s" % ((record.get("reason") or "").splitlines() or ["?"])[0]
    if phase == "stopped":
        return "stopped: %s" % record.get("reason")
    blocked = blockers(gid, tasks, records, me_gid)
    return "; ".join(blocked) if blocked else "ready"


def task_url(board, gid):
    return "https://app.asana.com/0/%s/%s" % (board or 0, gid)


# --- side effects -----------------------------------------------------------

def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (proc.returncode, proc.stdout.decode("utf-8", "replace").strip(),
            proc.stderr.decode("utf-8", "replace").strip())


class Engine(object):
    """The loop over a set of tasks. A subclass provides `scope()` — the tasks in
    play, as [{gid, board}] — and puts the sprint in `data["sprint"]`."""

    def __init__(self, state_dir, repo, forward):
        self.repo = os.path.abspath(repo)
        self.main_root = st.main_repo_root(self.repo)
        self.forward = forward
        self.dir = state_dir(self.main_root) if callable(state_dir) else state_dir
        self.data = self.load()
        self.children = {}
        self.refresh_due = 0

    # state

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def load(self):
        try:
            with open(self.path("state.json")) as f:
                return json.load(f)
        except (IOError, OSError, ValueError):
            return {"tasks": {}, "records": {}}

    def save(self):
        st.ensure_cortex_dir(self.main_root)
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path("state.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.path("state.json"))

    @property
    def tasks(self):
        return self.data["tasks"]

    @property
    def records(self):
        return self.data["records"]

    def record(self, gid):
        return self.records.setdefault(gid, {})

    def key_of(self, gid):
        return (self.tasks.get(gid) or {}).get("key") or gid

    def set_phase(self, gid, phase, **fields):
        record = self.record(gid)
        if record.get("phase") != phase:
            log("%s %s → %s" % (self.key_of(gid), record.get("phase") or "new", phase))
        record.update(fields, phase=phase, since=time.time())

    def start_state(self, gid):
        return st.State(self.main_root, self.key_of(gid))

    # asana / github

    def asana(self, args, check=True):
        code, out, err = run([sys.executable, ASANA] + args, cwd=self.repo)
        if code != 0:
            if check:
                raise Stop("asana.py %s failed (exit %d): %s"
                           % (" ".join(args), code, err or out))
            return code, None
        try:
            return code, json.loads(out) if out else None
        except ValueError:
            return code, out

    def gh_json(self, args):
        code, out, err = run(["gh"] + args, cwd=self.repo)
        if code != 0:
            log("gh %s failed: %s" % (" ".join(args[:3]), err or out))
            return None
        try:
            return json.loads(out) if out else None
        except ValueError:
            return None

    def gh_list(self, path):
        code, out, err = run(["gh", "api", "--paginate", path, "--jq", ".[]"],
                             cwd=self.repo)
        if code != 0:
            log("gh api %s failed: %s" % (path, err or out))
            return None
        rows = []
        for line in out.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    # setup

    def resolve_me(self):
        _, me = self.asana(["user", "me"])
        self.data["me"] = {"gid": me.get("gid"), "name": me.get("name")}
        return me

    def resolve_sprint(self, ref):
        sprint_gid = parse_project_ref(ref)
        if not sprint_gid:
            raise Stop("not an Asana board URL or gid for the sprint: %s" % ref)
        _, sprint = self.asana(["project", "get", sprint_gid])
        self.data["sprint"] = {"gid": sprint.get("gid"), "name": sprint.get("name")}
        return sprint

    def scope(self):
        raise NotImplementedError

    def refresh(self, only=None):
        """Re-read the tasks in scope from Asana. `only` re-reads just those gids —
        the ones newly in scope — and keeps the rest as last read."""
        tasks = {}
        for item in self.scope():
            gid = item["gid"]
            if only is not None and gid not in only and gid in self.tasks:
                tasks[gid] = self.tasks[gid]
                continue
            _, task = self.asana(["task", "get", gid])
            previous = self.tasks.get(gid) or {}
            deps = previous.get("deps") or []
            if not task.get("completed"):
                _, deps = self.asana(["task", "dependencies", gid])
            tasks[gid] = {
                "name": task.get("name"),
                "key": st.task_key(task),
                "completed": bool(task.get("completed")),
                "status": task.get("status"),
                "assignee": task.get("assignee"),
                "assignee_gid": task.get("assignee_gid"),
                "boards": [b.get("project") for b in task.get("board") or []],
                "deps": deps or [],
                "board_gid": item.get("board"),
            }
        self.data["tasks"] = tasks
        if only is None:
            self.data["refreshed_at"] = time.time()
            self.refresh_due = time.time() + REFRESH_EVERY

    def reconcile_all(self):
        for gid in self.tasks:
            record = self.records.get(gid)
            state = self.start_state(gid)
            live = st.live_run_pid(state.read("run.json"))
            updated = reconcile(record, state.read(st.OUTCOME_FILE), live)
            updated.pop("next_poll", None)
            if updated != (record or {}):
                self.records[gid] = updated
                if updated.get("phase") != (record or {}).get("phase"):
                    log("%s reconciled: %s → %s" % (self.key_of(gid),
                                                    (record or {}).get("phase") or "new",
                                                    updated.get("phase") or "to relaunch"))

    # launching

    def prepare(self, gid):
        task = self.tasks[gid]
        sprint = self.data["sprint"]
        if sprint["name"] not in (task.get("boards") or []):
            self.asana(["task", "add-to-board", gid, sprint["gid"]])
            log("%s added to %s" % (task["key"], sprint["name"]))
        if not task.get("assignee_gid"):
            self.asana(["task", "set-field", gid, "Assignee", self.data["me"]["gid"]])
            log("%s assigned to %s" % (task["key"], self.data["me"]["name"]))

    def spawn(self, gid, argv, phase, **fields):
        key = self.key_of(gid)
        os.makedirs(self.path("logs"), exist_ok=True)
        os.makedirs(self.path("results"), exist_ok=True)
        result = self.path("results", "%s.json" % gid)
        try:
            os.remove(result)
        except OSError:
            pass
        logfile = open(self.path("logs", "%s.log" % key), "a")
        logfile.write("\n==== %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), phase))
        logfile.flush()
        cmd = ([sys.executable, START_TASK] + argv
               + ["--repo", self.repo, "--result-file", result] + self.forward)
        proc = subprocess.Popen(cmd, cwd=self.repo, stdin=subprocess.DEVNULL,
                                stdout=logfile, stderr=subprocess.STDOUT)
        logfile.close()
        self.children[gid] = proc
        self.set_phase(gid, phase, pid=proc.pid, log=self.path("logs", "%s.log" % key),
                       **fields)

    def launch(self, gid):
        try:
            self.prepare(gid)
        except Stop as e:
            self.set_phase(gid, "failed", reason=str(e))
            return
        self.spawn(gid, [task_url(self.tasks[gid].get("board_gid"), gid)], "running")

    def launch_revise(self, gid, items, text):
        os.makedirs(self.path("feedback"), exist_ok=True)
        path = self.path("feedback", "%s-%d.md" % (self.key_of(gid), time.time()))
        with open(path, "w") as f:
            f.write(text)
        log("%s: %d review item(s) — revising" % (self.key_of(gid), len(items)))
        self.spawn(gid, [self.key_of(gid), "--phase", "revise",
                         "--feedback-file", path], "revising",
                   inflight=[fid for fid, _, _ in items])

    # watching

    def reap(self):
        for gid in list(self.records):
            record = self.records[gid]
            if gid not in self.tasks and gid not in self.children:
                continue
            if record.get("phase") not in ("running", "awaiting", "revising"):
                continue
            proc = self.children.get(gid)
            if proc is not None:
                code = proc.poll()
                if code is None:
                    self.track_awaiting(gid)
                    continue
                del self.children[gid]
                self.finished(gid, code)
            elif record.get("pid"):
                if st.live_run_pid({"pid": record["pid"]}):
                    self.track_awaiting(gid)
                    continue
                self.finished(gid, None)

    def track_awaiting(self, gid):
        waiting = bool(self.start_state(gid).read("awaiting.json"))
        phase = self.records[gid]["phase"]
        if waiting and phase == "running":
            self.set_phase(gid, "awaiting")
        elif not waiting and phase == "awaiting":
            self.set_phase(gid, "running")

    def finished(self, gid, code):
        record = self.records[gid]
        outcome = None
        try:
            with open(self.path("results", "%s.json" % gid)) as f:
                outcome = json.load(f)
        except (IOError, OSError, ValueError):
            pass
        if code is None:
            # An adopted run: no exit code to read, so its outcome is the word.
            outcome = outcome or self.start_state(gid).read(st.OUTCOME_FILE)
            if outcome and outcome.get("at", 0) > record.get("since", 0):
                code = st.EXIT_FAILED if outcome.get("status") == "failed" else st.EXIT_OK
        phase, reason = outcome_phase(code, outcome)
        if phase == "pr_open":
            handled = set(record.get("handled") or [])
            if record.get("phase") == "revising":
                handled |= set(record.get("inflight") or [])
            self.set_phase(gid, "pr_open", pr_url=outcome.get("pr_url"),
                           branch=outcome.get("branch"), handled=sorted(handled),
                           inflight=[], next_poll=0, poll_attempt=0, pid=None)
        else:
            self.set_phase(gid, phase, reason=reason, pid=None)
            if phase == "failed":
                log("%s failed: %s (log: %s)" % (self.key_of(gid),
                                                 (reason or "").splitlines()[0] if reason else "?",
                                                 record.get("log")))

    def poll_pr(self, gid):
        """One look at a task's PR. Open and mergeable: feedback goes to revise.
        Conflicting: the task is parked until a comment asks for a resolve. Closed
        without merging: the task stops. Merged: the task is done."""
        record = self.records[gid]
        if time.time() < record.get("next_poll", 0):
            return
        parts = parse_pr_url(record.get("pr_url"))
        if not parts:
            self.set_phase(gid, "failed", reason="no PR URL recorded")
            return
        owner, name, number = parts
        view = self.gh_json(["pr", "view", record["pr_url"], "--json",
                             "state,mergedAt,mergeable"])
        changed = False
        if view is not None:
            if view.get("state") == "MERGED":
                self.merged(gid)
                return
            if view.get("state") == "CLOSED":
                self.set_phase(gid, "stopped", reason="PR closed without merging")
                return
            mergeable = view.get("mergeable")
            if mergeable == "CONFLICTING" and record["phase"] == "pr_open":
                self.post_conflict(gid)
                self.set_phase(gid, "conflict")
                changed = True
            elif mergeable == "MERGEABLE" and record["phase"] == "conflict":
                self.set_phase(gid, "pr_open")
                changed = True
            items = self.feedback(owner, name, number, record.get("handled"))
            if items and record["phase"] == "pr_open":
                self.launch_revise(gid, items, render_feedback(items))
                return
            ask = resolve_request(items or [])
            if ask and record["phase"] == "conflict":
                self.launch_revise(gid, [ask], render_resolve(ask))
                return
        record["poll_attempt"] = 0 if changed else record.get("poll_attempt", 0) + 1
        if record["phase"] == "conflict":
            record["next_poll"] = time.time() + CONFLICT_POLL
        else:
            record["next_poll"] = time.time() + st.poll_interval(
                max(1, record["poll_attempt"]), start=PR_POLL_START, cap=PR_POLL_CAP)

    def feedback(self, owner, name, number, handled):
        base = "repos/%s/%s" % (owner, name)
        reviews = self.gh_list("%s/pulls/%d/reviews" % (base, number))
        inline = self.gh_list("%s/pulls/%d/comments" % (base, number))
        comments = self.gh_list("%s/issues/%d/comments" % (base, number))
        if None in (reviews, inline, comments):
            return None
        return collect_feedback(reviews, inline, comments, handled)

    def post_task(self, gid, body):
        self.asana(["comment", "add", gid, st.mark(body)], check=False)

    def post_conflict(self, gid):
        record = self.records[gid]
        text = ("This PR conflicts with its base — most likely a sibling task merged "
                "first and touched the same files. The task is parked. Comment `%s` on "
                "the PR to have the base merged in and the conflicts resolved (never a "
                "rebase or force-push), or resolve it yourself." % RESOLVE_TRIGGER)
        run(["gh", "pr", "comment", record["pr_url"], "--body", st.mark(text)], cwd=self.repo)
        self.post_task(gid, "%s\n\n%s" % (text, record["pr_url"]))
        log("%s: PR conflicts with its base — parked" % self.key_of(gid))

    def merged(self, gid):
        key = self.key_of(gid)
        self.asana(["task", "complete", gid])
        code, _ = self.asana(["task", "set-status", gid, "Done"], check=False)
        if code != 0:
            log("%s: could not move to Done" % key)
        worktree = (self.start_state(gid).read("context.json") or {}).get("git", {}).get("worktree")
        if worktree and os.path.isdir(worktree) and os.path.abspath(worktree) != self.main_root:
            with st.repo_lock(self.main_root):
                code, _, err = run(["git", "worktree", "remove", worktree], cwd=self.main_root)
            if code != 0:
                log("%s: left the worktree in place (%s)" % (key, err))
        self.tasks[gid]["completed"] = True
        for task in self.tasks.values():
            for dep in task.get("deps") or []:
                if dep.get("ref") == gid:
                    dep["completed"] = True
        self.set_phase(gid, "merged")
        self.refresh_due = 0

    def stop_finished_elsewhere(self):
        """A task completed or canceled in Asana by hand is left alone from here."""
        for gid, task in self.tasks.items():
            record = self.records.get(gid) or {}
            phase = record.get("phase")
            if phase in (None, "merged", "stopped", "failed"):
                continue
            canceled = (task.get("status") or "").lower() == "canceled"
            if not (task.get("completed") or canceled):
                continue
            self.stop(gid, "canceled in Asana" if canceled else "completed in Asana")

    def stop(self, gid, reason):
        """End whatever is running for a task and leave it be. Its worktree stays."""
        self.kill(gid)
        self.set_phase(gid, "stopped", pid=None, reason=reason)

    def kill(self, gid):
        proc = self.children.pop(gid, None)
        pid = proc.pid if proc else (self.records.get(gid) or {}).get("pid")
        if pid and st.live_run_pid({"pid": pid}):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def kill_all(self):
        """Stop every run this engine launched or adopted, so none outlives it
        unseen. Their records stay as they are; a restart relaunches them."""
        for gid in set(self.children) | {g for g, r in self.records.items() if r.get("pid")}:
            self.kill(gid)

    # loop

    def tick(self):
        self.reap()
        if time.time() >= self.refresh_due:
            self.refresh()
            self.stop_finished_elsewhere()
        if self.data.get("sprint"):
            for gid in ready_tasks(self.tasks, self.records, self.data["me"]["gid"]):
                self.launch(gid)
        for gid, record in list(self.records.items()):
            if gid in self.tasks and record.get("phase") in ("pr_open", "conflict"):
                self.poll_pr(gid)
        self.save()

    def done(self):
        if time.time() >= self.refresh_due:
            return False
        if self.children or any((self.records.get(gid) or {}).get("phase") in LIVE
                                for gid in self.tasks):
            return False
        if ready_tasks(self.tasks, self.records, self.data["me"]["gid"]):
            return False
        return True

    def report(self, title):
        me = (self.data.get("me") or {}).get("gid")
        sys.stdout.write("\n\033[1m%s\033[0m\n" % title)
        refreshed = self.data.get("refreshed_at")
        if refreshed:
            sys.stdout.write("  as of %s\n" % time.strftime("%Y-%m-%d %H:%M",
                                                          time.localtime(refreshed)))
        for gid, task in self.tasks.items():
            record = self.records.get(gid) or {}
            sys.stdout.write("\n  %-8s %s\n" % (task.get("key"), task.get("name")))
            sys.stdout.write("           %s\n" % describe(gid, self.tasks, self.records, me))
            awaiting = self.start_state(gid).read("awaiting.json")
            if awaiting and record.get("phase") == "awaiting":
                for q in awaiting.get("questions") or []:
                    sys.stdout.write("           Q: %s\n" % q.get("q"))
                if awaiting.get("headline"):
                    sys.stdout.write("           %s\n" % awaiting["headline"])
            sys.stdout.write("           %s\n" % task_url(task.get("board_gid"), gid))
            if record.get("pr_url"):
                sys.stdout.write("           %s\n" % record["pr_url"])
            if record.get("phase") in ("failed", "running", "awaiting", "revising"):
                sys.stdout.write("           log: %s\n" % record.get("log"))
        sys.stdout.flush()
