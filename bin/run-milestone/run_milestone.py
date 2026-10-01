#!/usr/bin/env python3
#
# run-milestone — works a board's milestones through start-task, in parallel, to merge.
#
# A deterministic loop over plain code — no model is called here. It finds the
# ready tasks in the milestones it was given (not done, every dependency done),
# puts each in the sprint it was given, assigns it, and runs `start-task` on it. A
# shipped PR is watched until it merges: review feedback in the meantime is handed
# back to the task's session through `start-task --phase revise`, and a merge
# completes the task in Asana, which is what readies its dependents. A PR that
# conflicts with its base parks its task until someone asks for a resolve; a PR
# closed without merging stops it.
#
# Every run that is going, waiting on a human, or watching a PR is recorded under
# `<repo>/.cortex/milestones/<board>/`, and a restart reconciles that record
# against Asana, GitHub and start-task's own state rather than trusting it.
#
#   cortex run-milestone <board-url> "M1" --sprint <sprint-url>   # until M1 is done
#   cortex run-milestone <board-url> M1 M2 --sprint <sprint-url>  # several at once
#   cortex run-milestone <board-url> --status                     # where every task stands
#   cortex run-milestone <board-url> M1 --sprint <url> --backend echo  # rest → start-task
#
# Dependencies: Python 3 stdlib, git, gh, and start-task (sibling directory).

import argparse
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

MILESTONES_DIRNAME = "milestones"

TICK = 15
REFRESH_EVERY = 300
PR_POLL_START = 60
PR_POLL_CAP = 600

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


def match_milestones(wanted, listing):
    """The milestones named in `wanted`, out of a board's `milestone list`.

    Each entry may be the milestone's full name, the short name before ` :: `
    ("M1"), or its task's gid or URL. Returns [{name, ref}] in the order asked;
    raises ValueError naming anything that matched nothing, or more than one.
    """
    out = []
    for item in wanted:
        gid = task_ref(item)
        key = item.strip().lower()
        hits = [m for m in listing
                if m.get("ref") == gid
                or (m.get("name") or "").strip().lower() == key
                or (m.get("name") or "").split(" :: ")[0].strip().lower() == key]
        if len(hits) != 1:
            names = ", ".join(m.get("name") or "?" for m in listing) or "none"
            raise ValueError("%r matches %s milestone(s) on this board (it has: %s)"
                             % (item, len(hits) or "no", names))
        if hits[0] not in out:
            out.append(hits[0])
    return out


def task_ref(item):
    """A task gid from a URL or a bare gid, by the provider's own rules."""
    from asana import asana_extract_ref
    return asana_extract_ref(item)


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
            out.append("waits on %s (outside the milestone)" % name)
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


def task_url(project, gid):
    return "https://app.asana.com/0/%s/%s" % (project, gid)


# --- side effects -----------------------------------------------------------

def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (proc.returncode, proc.stdout.decode("utf-8", "replace").strip(),
            proc.stderr.decode("utf-8", "replace").strip())


class BoardRun(object):
    """The loop over one board. Which tasks it works is `scope()` — here, the
    members of the milestones it was given."""

    def __init__(self, board, milestones, sprint, repo, forward):
        self.project = parse_project_ref(board)
        if not self.project:
            raise Stop("not an Asana board URL or gid: %s" % board)
        self.wanted = milestones
        self.sprint_ref = sprint
        self.repo = os.path.abspath(repo)
        self.main_root = st.main_repo_root(self.repo)
        self.forward = forward
        self.dir = os.path.join(self.main_root, st.CORTEX_DIRNAME, MILESTONES_DIRNAME,
                                self.project)
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
            return {"project": self.project, "tasks": {}, "records": {}}

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

    def resolve(self):
        """Who the tasks are assigned to, which sprint they go into and which
        milestones are in scope — all from what was given, nothing guessed."""
        _, me = self.asana(["user", "me"])
        self.data["me"] = {"gid": me.get("gid"), "name": me.get("name")}
        _, board = self.asana(["project", "get", self.project])
        self.data["board"] = board.get("name")
        sprint_gid = parse_project_ref(self.sprint_ref)
        if not sprint_gid:
            raise Stop("not an Asana board URL or gid for --sprint: %s" % self.sprint_ref)
        _, sprint = self.asana(["project", "get", sprint_gid])
        self.data["sprint"] = {"gid": sprint.get("gid"), "name": sprint.get("name")}
        _, listing = self.asana(["milestone", "list", self.project])
        try:
            self.data["milestones"] = match_milestones(self.wanted, listing or [])
        except ValueError as e:
            raise Stop(str(e))
        log("board %s · %s · sprint %s · assigning to %s"
            % (board.get("name"), ", ".join(m["name"] for m in self.data["milestones"]),
               sprint.get("name"), me.get("name")))

    def scope(self):
        members = []
        for milestone in self.data["milestones"]:
            _, rows = self.asana(["milestone", "tasks", self.project, milestone["ref"]])
            members += [r["gid"] for r in rows or [] if r["gid"] not in members]
        return members

    def refresh(self):
        tasks = {}
        for gid in self.scope():
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
            }
        self.data["tasks"] = tasks
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
        self.spawn(gid, [task_url(self.project, gid)], "running")

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
            outcome = self.start_state(gid).read(st.OUTCOME_FILE)
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
            proc = self.children.pop(gid, None)
            pid = proc.pid if proc else record.get("pid")
            if pid and st.live_run_pid({"pid": pid}):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            self.set_phase(gid, "stopped", pid=None,
                           reason="canceled in Asana" if canceled else "completed in Asana")

    # loop

    def tick(self):
        self.reap()
        if time.time() >= self.refresh_due:
            self.refresh()
            self.stop_finished_elsewhere()
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

    def run_loop(self):
        self.resolve()
        self.refresh()
        self.reconcile_all()
        self.save()
        try:
            while True:
                self.tick()
                if self.done():
                    break
                time.sleep(TICK)
        finally:
            self.save()
        self.report()
        return 0 if all(t["completed"] for t in self.tasks.values()) else 1

    def report(self):
        me = (self.data.get("me") or {}).get("gid")
        sys.stdout.write("\n\033[1m%s\033[0m\n" % (self.data.get("board") or self.project))
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
            sys.stdout.write("           %s\n" % task_url(self.project, gid))
            if record.get("pr_url"):
                sys.stdout.write("           %s\n" % record["pr_url"])
            if record.get("phase") in ("failed", "running", "awaiting", "revising"):
                sys.stdout.write("           log: %s\n" % record.get("log"))
        sys.stdout.flush()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cortex run-milestone",
        description="Work every task in the given milestones of an Asana board through "
                    "start-task, in parallel, until each is merged. Arguments not "
                    "listed here are passed to every start-task run (e.g. --backend "
                    "echo).")
    parser.add_argument("board", help="URL (or gid) of the board the milestones are on")
    parser.add_argument("milestones", nargs="*",
                        help="milestones to work: full name, the short name before "
                             "' :: ' (e.g. M1), or the milestone task's URL or gid")
    parser.add_argument("--sprint", default=None,
                        help="URL (or gid) of the sprint board tasks are added to")
    parser.add_argument("--repo", default=os.getcwd(),
                        help="target repository (default: cwd)")
    parser.add_argument("--status", action="store_true",
                        help="report where every task stands, from the last run's "
                             "record; no network, no work")
    return parser


def main(argv):
    parser = build_parser()
    args, forward = parser.parse_known_args(argv)
    if "--no-wait" in forward:
        sys.stderr.write("run-milestone: --no-wait does not apply — every run waits on "
                         "its own questions\n")
        return 2
    if not args.status and (not args.milestones or not args.sprint):
        parser.error("name at least one milestone, and the sprint with --sprint")
    try:
        board = BoardRun(args.board, args.milestones, args.sprint, args.repo, forward)
        if args.status:
            if not board.tasks:
                raise Stop("no record of this board in %s — run it first" % board.dir)
            board.report()
            return 0
        return board.run_loop()
    except Stop as e:
        sys.stderr.write("\nrun-milestone: %s\n" % e)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.stderr.write("\n\nrun-milestone: interrupted — progress is recorded; run the "
                         "same command to carry on.\n")
        sys.exit(130)
