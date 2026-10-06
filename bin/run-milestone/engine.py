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
import shutil
import signal
import subprocess
import sys
import threading
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
SETTLED = LIVE + ("merged", "failed", "stopped", "undone")

# What a PR comment has to say for a parked conflict to be resolved.
RESOLVE_TRIGGER = "please resolve"

# While a merge is asked for, the PR is looked at this often: something is
# happening, and the next step depends on it.
MERGE_POLL = 15
# How many times a merge resolves conflicts, or fixes failing checks, before it
# stops and says why. Conflicts recur as siblings land; a check that stays red
# after two fixes needs a person.
MERGE_LIMITS = {"resolve": 3, "ci": 2}
# GitHub holds a PR it has just been pushed to before CI has even registered its
# checks, without saying why. A hold is waited on this long before it counts as
# a block; and a block is looked at again this often, so it clears by itself.
HOLD_GRACE = 600
BLOCKED_POLL = 120
# When a shipped PR is merged without being asked: "branches" (when it targets
# anything but the default branch — the recommended default), "always", or
# "asked" (only when asked). Asking, per task, works in every mode.
MERGE_MODES = ("branches", "always", "asked")
_CHECK_FAILED = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED",
                 "STARTUP_FAILURE"}


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


def latest_checks(rollup):
    """Each check once: its latest run. A re-run CI lists a check once per run —
    a cancelled run superseded by a newer one on the same commit is history,
    not the check's state."""
    latest = {}
    for i, check in enumerate(rollup or []):
        name = check.get("name") or check.get("context") or "?"
        when = (check.get("startedAt") or check.get("createdAt") or "", i)
        if name not in latest or when >= latest[name][0]:
            latest[name] = (when, check)
    return [check for _, check in latest.values()]


def check_states(rollup):
    """(pending names, failing [(name, url)]) from a PR's statusCheckRollup, which
    mixes check runs (status + conclusion) and commit statuses (state). Only each
    check's latest run counts."""
    pending, failing = [], []
    for check in latest_checks(rollup):
        name = check.get("name") or check.get("context") or "?"
        url = check.get("detailsUrl") or check.get("targetUrl")
        if check.get("__typename") == "StatusContext" or "state" in check and "status" not in check:
            state = (check.get("state") or "").upper()
            if state in ("PENDING", "EXPECTED"):
                pending.append(name)
            elif state in ("FAILURE", "ERROR"):
                failing.append((name, url))
        elif (check.get("status") or "").upper() != "COMPLETED":
            pending.append(name)
        elif (check.get("conclusion") or "").upper() in _CHECK_FAILED:
            failing.append((name, url))
    return sorted(set(pending)), sorted(set(failing))


def merge_step(view, attempts, limits=None, required=()):
    """The next thing to do for a PR that is to be merged: (action, detail).

    merge · ready (it is a draft) · update (behind its base) · resolve (conflicts)
    · fix_ci (a check failed; detail is the failures) · wait (checks running or
    not yet started, or GitHub still working it out) · held (GitHub will not merge
    and gives no reason — usually checks about to start) · blocked (detail says
    why a person is needed). `required` are the check names the base's rules
    require; one that has not reported yet is waited for.
    """
    limits = limits or MERGE_LIMITS
    attempts = attempts or {}
    status = view.get("mergeStateStatus")
    if view.get("isDraft"):
        return "ready", None
    if status == "DIRTY" or view.get("mergeable") == "CONFLICTING":
        if attempts.get("resolve", 0) >= limits["resolve"]:
            return "blocked", "still conflicting after %d resolve(s)" % attempts["resolve"]
        return "resolve", None
    if status == "BEHIND":
        return "update", None
    # Every check has to be green, required or not: a branch with no rules lets
    # GitHub call a PR mergeable while its CI is still running, or failing.
    pending, failing = check_states(view.get("statusCheckRollup"))
    if status in ("CLEAN", "UNSTABLE", "HAS_HOOKS", "BLOCKED"):
        if failing:
            if attempts.get("ci", 0) >= limits["ci"]:
                return "blocked", "checks still failing after %d fix(es): %s" % (
                    attempts["ci"], ", ".join(n for n, _ in failing))
            return "fix_ci", failing
        if pending:
            return "wait", "checks running: %s" % ", ".join(pending)
        reported = {c.get("name") or c.get("context") for c in view.get("statusCheckRollup") or []}
        missing = [name for name in required if name not in reported]
        if missing:
            return "wait", "waiting for checks to start: %s" % ", ".join(missing)
    if status in ("CLEAN", "UNSTABLE", "HAS_HOOKS"):
        return "merge", None
    if status == "BLOCKED":
        return "held", "GitHub will not merge it yet (a review or a rule, not a check)"
    return "wait", "GitHub is still working out whether it can merge"


def merge_method(repo, rule_methods):
    """The merge method to use: one both the repo and its rules allow, squash
    first, then a merge commit, then rebase. None when nothing is allowed."""
    allowed = {"squash": repo.get("squashMergeAllowed", True),
               "merge": repo.get("mergeCommitAllowed", True),
               "rebase": repo.get("rebaseMergeAllowed", True)}
    for method in ("squash", "merge", "rebase"):
        if allowed[method] and (not rule_methods or method in rule_methods):
            return method
    return None


def render_merge_resolve(base):
    return ("Merge was asked for, and the PR conflicts with its base. Merge `%s` into "
            "the branch and resolve the conflicts, keeping both sides' intent — what "
            "landed on the base is already reviewed and merged, so work around it "
            "rather than undo it.\n" % base)


_LOG_STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# What a failed job's log says went wrong, strongest signals first: an error
# annotation, a line that starts with ERROR or FAIL, a named exception, a failed
# test mark, a non-zero exit. Weaker words count only when nothing strong does.
_STRONG = re.compile(r"##\[error\]|^\s*(?:ERROR|FAIL(?:ED)?|FAILURE)\b|\b\w*(?:Error|Exception):|"
                     r"^\s*(?:✗|✘|×)|AssertionError|Traceback|exit code [1-9]")
_WEAK = re.compile(r"\berror\b|\bfail(?:ed|ure|s)?\b|expected|received|timed? ?out", re.IGNORECASE)
_NOISE = re.compile(r"^(##\[(?:group|endgroup)\]|Post job cleanup|Cleaning up orphan|\s*[✓√]|"
                    r".*Expected Digest)", re.IGNORECASE)


def failure_excerpt(log_text, max_lines=10):
    """The lines of a CI job's log that say what failed: errors, failed tests,
    assertions — the last `max_lines` of them, timestamps off. Falls back on the
    log's last lines when none stand out."""
    lines = []
    for raw in (log_text or "").splitlines():
        line = _ESCAPES.sub("", _LOG_STAMP.sub("", raw)).rstrip()
        if line.strip() and not _NOISE.match(line.strip()):
            lines.append(line.replace("##[error]", "error: "))
    strong = [l for l in lines if _STRONG.search(l)]
    weak = [l for l in lines if _WEAK.search(l)]
    picked = strong or weak or lines
    out = []
    for line in picked[-max_lines * 3:]:
        if line not in out:
            out.append(line[:200])
    return out[-max_lines:]


def render_ci_fix(failing, excerpts=None):
    excerpts = excerpts or {}
    lines = ["Merge was asked for, and required checks failed on the PR:", ""]
    for name, url in failing:
        lines.append("- %s%s" % (name, " — %s" % url if url else ""))
        if excerpts.get(name):
            lines += ["", "  What its log says:", "", "  ```"]
            lines += ["  " + l for l in excerpts[name]] + ["  ```", ""]
    lines += ["", "Find out why with `gh pr checks` and `gh run view <run-id> --log-failed`, "
              "and fix the cause. If a failure is plainly flaky and unrelated to this "
              "change, re-run it with `gh run rerun <run-id> --failed` instead of "
              "changing code, and say so in your reply."]
    return "\n".join(lines) + "\n"


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
        hours = record.get("actual_hours")
        text = "merged — %s of run time" % hhmm(hours) if hours is not None else "merged"
        if record.get("usage"):
            text += " · %s" % st.usage_summary(record["usage"])
        return text
    if task.get("completed"):
        return "completed"
    if phase == "running":
        return "running"
    if phase == "awaiting":
        return "awaiting Justin"
    if phase == "revising":
        return "revising after review"
    merge = record.get("merge")
    if merge and merge.get("blocked") and phase in ("pr_open", "conflict"):
        return "merge blocked: %s" % merge["blocked"]
    if merge and phase in ("pr_open", "conflict", "revising"):
        return "merging — %s" % (merge.get("stage") or "starting")
    if phase == "pr_open":
        return "PR open"
    if phase == "conflict":
        return ("PR conflicts with its base — parked; comment `%s` on the PR to have it "
                "resolved" % RESOLVE_TRIGGER)
    if phase == "failed":
        return "failed: %s" % ((record.get("reason") or "").splitlines() or ["?"])[0]
    if phase == "stopped":
        return "stopped: %s" % record.get("reason")
    if phase == "undone":
        return "undone — %s" % record.get("reason")
    blocked = blockers(gid, tasks, records, me_gid)
    return "; ".join(blocked) if blocked else "ready"


def actual_hours(worked_seconds):
    """A task's run time in hours, at the hundredth Asana shows. None when no run
    recorded any."""
    if not worked_seconds or worked_seconds <= 0:
        return None
    return round(worked_seconds / 3600.0, 2)


def kill_tree(pid):
    """Stop a run and everything it started. A run launched here leads its own
    process group, so its agent and QA commands go with it; anything else gets
    the signal on its own. Returns whether there was something to stop."""
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def has_value(display):
    """Whether a number field already holds something a person put there."""
    try:
        return float(display) != 0
    except (TypeError, ValueError):
        return False


def merge_refresh(local, fetched):
    """Fold a background re-read of Asana into what the loop knows now. The read
    may have started before a merge the loop has since made, so completion only
    ever moves forward: a task or dependency done here stays done."""
    done = {gid for gid, t in local.items() if t.get("completed")}
    for gid, task in fetched.items():
        if gid in done:
            task["completed"] = True
        known = {d.get("ref"): d for d in (local.get(gid) or {}).get("deps") or []}
        for dep in task.get("deps") or []:
            if dep.get("ref") in done or (known.get(dep.get("ref")) or {}).get("completed"):
                dep["completed"] = True
    return fetched


def hhmm(hours):
    """Hours as HH:MM, to the nearest minute."""
    minutes = int(round(hours * 60))
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def phase_note(phase, record):
    """What a task's log says when it enters a phase, or None when the run it
    starts writes its own account."""
    reason = (record.get("reason") or "").splitlines()
    return {
        "awaiting": "Waiting on you — the question is on the task and the TUI's Runs tab",
        "pr_open": (None if record.get("merge") is not None
                    else "PR open — watching for review comments and the merge"),
        "conflict": "PR conflicts with its base — parked until a resolve or a merge is asked for",
        "failed": "Failed: %s" % (reason[0] if reason else "see above"),
        "stopped": "Stopped: %s" % (reason[0] if reason else "?"),
    }.get(phase)


def run_header(label, at=None):
    """The line that opens each run in a task's log, saying why it started."""
    return "\n━━ %s · %s ━━\n" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at)), label)


def auto_merge_due(mode, record, base=None, default_branch=None):
    """Whether a task's PR should be put on to merge without being asked: once
    it ships, unless a merge for it was called off — always, or in "branches"
    mode when its base is known and is not the default branch."""
    if record.get("phase") not in ("pr_open", "conflict") or record.get("merge") is not None \
            or record.get("merge_declined"):
        return False
    if mode == "always":
        return True
    if mode == "branches":
        return bool(base and default_branch and base != default_branch)
    return False


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
        # Slow work in hand, by name: (what it is, the task it is for or None) — for
        # whoever is watching to see why something is taking a while, and on which
        # task.
        self.busy = {}
        self.refreshing = None
        self.fetched = None

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
        changed = record.get("phase") != phase
        if changed:
            log("%s %s → %s" % (self.key_of(gid), record.get("phase") or "new", phase))
        record.update(fields, phase=phase, since=time.time())
        if changed and phase_note(phase, record):
            self.note(gid, phase_note(phase, record))

    def log_path(self, gid):
        return self.path("logs", "%s.log" % self.key_of(gid))

    def note(self, gid, heading, details=()):
        """A step in the task's own log, beside what its runs wrote — so the log
        tells the whole story, not just the part start-task did."""
        try:
            os.makedirs(self.path("logs"), exist_ok=True)
            with open(self.log_path(gid), "a") as f:
                f.write("\n%s  %s\n" % (time.strftime("%H:%M:%S"), heading))
                for line in details:
                    f.write("  %s\n" % line)
        except OSError:
            pass

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
        """Re-read the tasks in scope from Asana, now. `only` re-reads just those
        gids — the ones newly in scope — and keeps the rest as last read."""
        self.data["tasks"] = self.fetch_tasks(self.scope(), dict(self.tasks), only)
        if only is None:
            self.data["refreshed_at"] = time.time()
            self.refresh_due = time.time() + REFRESH_EVERY

    def start_refresh(self):
        """Re-read everything in a thread, so a board of tasks — dozens of calls —
        never holds up commands, merges or noticing a run finish."""
        previous = dict(self.tasks)

        def work():
            self.busy["refresh"] = ("reading the tasks from Asana", None)
            try:
                self.fetched = (self.fetch_tasks(self.scope(), previous), None)
            except Exception as e:  # reported by the loop, never fatal
                self.fetched = (None, str(e))
            finally:
                self.busy.pop("refresh", None)

        self.refreshing = threading.Thread(target=work, daemon=True)
        self.refreshing.start()

    def take_refresh(self):
        """Fold in a finished background re-read. True when one landed."""
        if self.refreshing is None or self.refreshing.is_alive() or self.fetched is None:
            return False
        tasks, error = self.fetched
        self.refreshing, self.fetched = None, None
        if error:
            log("could not re-read Asana (%s) — trying again shortly" % error)
            self.refresh_due = time.time() + 60
            return False
        self.data["tasks"] = merge_refresh(self.tasks, tasks)
        self.data["refreshed_at"] = time.time()
        self.refresh_due = time.time() + REFRESH_EVERY
        return True

    def fetch_tasks(self, items, previous, only=None):
        """The tasks in `items`, read from Asana. A completed task's dependencies
        are not re-read — they no longer matter."""
        tasks = {}
        for item in items:
            gid = item["gid"]
            if only is not None and gid not in only and gid in previous:
                tasks[gid] = previous[gid]
                continue
            _, task = self.asana(["task", "get", gid])
            deps = (previous.get(gid) or {}).get("deps") or []
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
        return tasks

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

    def spawn(self, gid, argv, phase, label, **fields):
        key = self.key_of(gid)
        os.makedirs(self.path("logs"), exist_ok=True)
        os.makedirs(self.path("results"), exist_ok=True)
        result = self.path("results", "%s.json" % gid)
        try:
            os.remove(result)
        except OSError:
            pass
        logfile = open(self.log_path(gid), "a")
        logfile.write(run_header(label))
        logfile.flush()
        cmd = ([sys.executable, START_TASK] + argv
               + ["--repo", self.repo, "--result-file", result] + self.forward)
        # Its own process group, so stopping the run stops its agent too.
        proc = subprocess.Popen(cmd, cwd=self.repo, stdin=subprocess.DEVNULL,
                                stdout=logfile, stderr=subprocess.STDOUT,
                                start_new_session=True)
        logfile.close()
        self.children[gid] = proc
        self.set_phase(gid, phase, pid=proc.pid, log=self.log_path(gid), **fields)

    def launch(self, gid):
        try:
            self.prepare(gid)
        except Stop as e:
            self.set_phase(gid, "failed", reason=str(e))
            return
        base = self.data.get("base")
        self.spawn(gid, [task_url(self.tasks[gid].get("board_gid"), gid)]
                   + (["--base", base] if base else []), "running",
                   "start-task: from the ticket to a ready PR%s" % (" on %s" % base if base else ""))

    def launch_revise(self, gid, items, text, why, issues=()):
        """Start a revise. `issues` — what is wrong, a line each — go in the task's
        log ahead of the run, and `why` stays on the record for the TUI's row."""
        os.makedirs(self.path("feedback"), exist_ok=True)
        path = self.path("feedback", "%s-%d.md" % (self.key_of(gid), time.time()))
        with open(path, "w") as f:
            f.write(text)
        log("%s: revising — %s" % (self.key_of(gid), why))
        self.note(gid, "Revising — %s" % why, list(issues) or ["(see the feedback below)"])
        self.spawn(gid, [self.key_of(gid), "--phase", "revise",
                         "--feedback-file", path], "revising", "revise: %s" % why,
                   inflight=[fid for fid, _, _ in items], revise_why=why)

    def ci_excerpts(self, failing):
        """For each failed check, the telling lines of its job's log, read from
        GitHub: {name: [lines]}. A log that cannot be read is simply left out."""
        out = {}
        for name, url in failing:
            m = re.search(r"github\.com/([^/]+)/([^/]+)/actions/runs/\d+/job/(\d+)", url or "")
            if not m:
                continue
            code, text, _ = run(["gh", "api", "--allow-escape-sequences",
                                 "repos/%s/%s/actions/jobs/%s/logs" % m.groups()], cwd=self.repo)
            if code == 0 and text:
                out[name] = failure_excerpt(text)
        return out

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
        if record.get("merge"):
            self.drive_merge(gid, owner, name)
            return
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
                self.launch_revise(gid, items, render_feedback(items),
                                   "addressing %d review comment(s)" % len(items),
                                   ["%s: %s" % (h, (b.strip().splitlines() or [""])[0][:140])
                                    for _, h, b in items])
                return
            ask = resolve_request(items or [])
            if ask and record["phase"] == "conflict":
                self.launch_revise(gid, [ask], render_resolve(ask),
                                   "resolving conflicts with the base, as asked",
                                   ["the PR conflicts with its base; merging the base in, "
                                    "keeping both sides' intent"])
                return
        record["poll_attempt"] = 0 if changed else record.get("poll_attempt", 0) + 1
        if record["phase"] == "conflict":
            record["next_poll"] = time.time() + CONFLICT_POLL
        else:
            record["next_poll"] = time.time() + st.poll_interval(
                max(1, record["poll_attempt"]), start=PR_POLL_START, cap=PR_POLL_CAP)

    def request_merge(self, gid, auto=False):
        """Get the task onto its base: from here the PR is driven to merge. False
        when merging is turned off."""
        record = self.record(gid)
        record.pop("merge_declined", None)
        record["merge"] = {"requested_at": time.time(), "attempts": {}, "stage": "starting",
                           "blocked": None, "auto": auto}
        record["next_poll"] = 0
        log("%s: merge %s" % (self.key_of(gid), "started automatically" if auto else "asked for"))
        self.note(gid, "Merge %s — conflicts and failing checks are handled on the way"
                  % ("started automatically (%s)" % auto if auto else "asked for"),
                  ["review comments from here on are not acted on"])
        if record.get("phase") == "conflict":
            self.set_phase(gid, "pr_open")
        return True

    def cancel_merge(self, gid):
        self.record(gid).pop("merge", None)
        self.record(gid)["merge_declined"] = True
        log("%s: merge no longer asked for" % self.key_of(gid))
        self.note(gid, "Merge called off — back to watching the PR")

    def retarget(self, gid, base):
        """Move a task's open PR onto `base`, and record that as its base so the
        merge rules judge it by where it now goes. Returns (done, why not)."""
        record = self.record(gid)
        url = record.get("pr_url")
        if record.get("phase") not in ("pr_open", "conflict") or not url:
            return False, "it has no open PR"
        self.busy["loop"] = ("changing %s's PR base branch to %s" % (self.key_of(gid), base), gid)
        try:
            code, _, err = run(["gh", "pr", "edit", url, "--base", base], cwd=self.repo)
        finally:
            self.busy.pop("loop", None)
        if code != 0:
            return False, "gh pr edit refused: %s" % ((err.splitlines() or ["?"])[-1])
        state = self.start_state(gid)
        context = state.read("context.json") or {}
        old = (context.get("git") or {}).get("base")
        context.setdefault("git", {})["base"] = "origin/%s" % base
        state.write("context.json", context)
        record["base"] = base
        record.pop("merge_declined", None)
        record["next_poll"] = 0
        log("%s: PR moved onto %s" % (self.key_of(gid), base))
        self.note(gid, "PR moved onto %s (was %s)" % (base, old or "?"),
                  ["from here it merges by the rules for %s" % base])
        return True, None

    def undo_plan(self, gid):
        """What undoing a task would do, a line a step, before anything is done —
        for the person to read and confirm."""
        record = self.records.get(gid) or {}
        key = self.key_of(gid)
        git_info = (self.start_state(gid).read("context.json") or {}).get("git") or {}
        if record.get("phase") == "merged":
            base = (git_info.get("base") or "").replace("origin/", "", 1) or "its base"
            return ["open a PR reverting %s's merge into %s — it waits for you to merge it" % (key, base),
                    "reopen the task in Asana, take it off the sprint and unassign it"]
        steps = []
        if record.get("phase") in ("running", "awaiting", "revising"):
            steps.append("stop its run")
        if record.get("pr_url"):
            steps.append("close its PR and delete the branch, on GitHub and here")
        elif git_info.get("branch"):
            steps.append("delete its branch %s" % git_info["branch"])
        if git_info.get("worktree"):
            steps.append("remove its worktree and saved state")
        steps.append("take it off the sprint and unassign it in Asana")
        return steps

    def started_dependents(self, gid):
        """Tasks that wait on this one and have already started or merged."""
        return [t.get("key") for g, t in self.tasks.items()
                if any(d.get("ref") == gid for d in t.get("deps") or [])
                and (self.records.get(g) or {}).get("phase") not in (None, "stopped", "undone")]

    def undo(self, gid):
        """Take a task's work back out: a revert PR when it merged, otherwise its
        run, PR, branch, worktree and state go. Either way it comes off the
        sprint, is unassigned, and leaves the queue. Returns (done, why not)."""
        key = self.key_of(gid)
        record = self.record(gid)
        self.busy["loop"] = ("undoing %s" % key, gid)
        try:
            if record.get("phase") == "merged":
                done, detail = self.undo_merged(gid)
            else:
                done, detail = self.undo_unmerged(gid)
        finally:
            self.busy.pop("loop", None)
        if not done:
            log("%s: could not undo — %s" % (key, detail))
            self.note(gid, "Undo failed — %s" % detail)
            return False, detail
        self.reset_in_asana(gid, detail)
        record.pop("merge", None)
        self.set_phase(gid, "undone", reason=detail, pid=None)
        log("%s: undone — %s" % (key, detail))
        return True, None

    def undo_unmerged(self, gid):
        self.kill(gid)
        state = self.start_state(gid)
        git_info = (state.read("context.json") or {}).get("git") or {}
        worktree, branch = git_info.get("worktree"), git_info.get("branch")
        pr = self.records.get(gid, {}).get("pr_url") or git_info.get("pr_url")
        done = []
        with st.repo_lock(self.main_root):
            if worktree and os.path.isdir(worktree) and os.path.abspath(worktree) != self.main_root:
                run(["git", "worktree", "remove", "--force", worktree], cwd=self.main_root)
                done.append("worktree removed")
            if branch:
                run(["git", "branch", "-D", branch], cwd=self.main_root)
        if pr:
            code, _, err = run(["gh", "pr", "close", pr, "--delete-branch", "--comment",
                                st.mark("Undone from the cortex TUI — this work is discarded.")],
                               cwd=self.main_root)
            done.append("PR closed, branch deleted" if code == 0 else "PR not closed: %s" % err)
        elif branch:
            run(["git", "push", "origin", "--delete", branch], cwd=self.main_root)
            done.append("branch deleted")
        if os.path.isdir(state.dir):
            shutil.rmtree(state.dir, ignore_errors=True)
        return True, "; ".join(done) or "nothing had been started"

    def undo_merged(self, gid):
        record = self.records[gid]
        key = self.key_of(gid)
        view = self.gh_json(["pr", "view", record.get("pr_url") or "", "--json",
                             "mergeCommit,baseRefName,number,title"]) or {}
        sha = (view.get("mergeCommit") or {}).get("oid")
        base = view.get("baseRefName")
        if not sha or not base:
            return False, "could not read the merge from GitHub"
        branch = "revert/%s-%d" % (key, int(time.time()))
        path = st.worktree_path(self.main_root, "revert-%s" % key)
        try:
            with st.repo_lock(self.main_root):
                run(["git", "fetch", "origin", base], cwd=self.main_root)
                code, _, err = run(["git", "worktree", "add", path, "-b", branch,
                                    "origin/%s" % base], cwd=self.main_root)
            if code != 0:
                return False, "could not set up the revert: %s" % err
            code, _, err = run(["git", "revert", "--no-edit", sha], cwd=path)
            if code != 0:
                run(["git", "revert", "--abort"], cwd=path)
                return False, ("its merge does not revert cleanly — later work builds on it; "
                               "revert it by hand")
            code, _, err = run(["git", "push", "-u", "origin", branch], cwd=path)
            if code != 0:
                return False, "could not push the revert: %s" % err
            code, out, err = run(["gh", "pr", "create", "--base", base, "--head", branch,
                                  "--title", "Revert \u201c%s\u201d" % view.get("title", key),
                                  "--body", st.mark("Reverts #%s — %s undone from the cortex TUI. "
                                                    "Not merged automatically: merge it when you "
                                                    "are sure." % (view.get("number"), key))],
                                 cwd=path)
            if code != 0:
                return False, "pushed %s, but could not open the PR: %s" % (branch, err)
            record["revert_pr"] = out.strip().splitlines()[-1]
            return True, "revert PR %s opened — it waits for you" % record["revert_pr"]
        finally:
            with st.repo_lock(self.main_root):
                run(["git", "worktree", "remove", "--force", path], cwd=self.main_root)

    def reset_in_asana(self, gid, what):
        """Put the task back to not started: reopened, off the sprint, unassigned —
        and say so on the task."""
        key = self.key_of(gid)
        task = self.tasks.get(gid) or {}
        sprint = self.data.get("sprint") or {}
        if task.get("completed") or (self.records.get(gid) or {}).get("phase") == "merged":
            self.asana(["task", "reopen", gid], check=False)
            task["completed"] = False
        if sprint.get("gid") and sprint.get("name") in (task.get("boards") or [sprint.get("name")]):
            self.asana(["task", "remove-from-board", gid, sprint["gid"]], check=False)
        if task.get("assignee_gid") == (self.data.get("me") or {}).get("gid"):
            self.asana(["task", "unassign", gid], check=False)
        self.asana(["comment", "add", gid, st.mark("Undone from the cortex TUI: %s. The task is "
                                                    "back to not started." % what)], check=False)
        self.note(gid, "Undone — %s" % what, ["Asana: reopened if it was done, taken off the "
                                               "sprint, unassigned"])

    def drive_merge(self, gid, owner, name):
        """One step towards merging: whatever GitHub says stands in the way, do
        the thing that removes it — or say why it cannot be done."""
        record = self.records[gid]
        merge = record["merge"]
        url = record["pr_url"]
        self.busy["loop"] = ("merging %s" % self.key_of(gid), gid)
        try:
            self.merge_step_for(gid, owner, name, record, merge, url)
        finally:
            self.busy.pop("loop", None)

    def merge_step_for(self, gid, owner, name, record, merge, url):
        blocked = merge.get("blocked")
        self.merge_step_once(gid, owner, name, record, merge, url)
        if merge.get("blocked") and merge["blocked"] != blocked:
            self.note(gid, "Merge blocked: %s" % merge["blocked"],
                      ["fix it, then m in the TUI tries again"])

    def stage(self, gid, merge, text):
        """Where a merge has got to; each new stage goes in the task's log as it
        starts, ahead of any run it launches."""
        if merge.get("stage") != text:
            self.note(gid, "Merge: %s" % text)
        merge["stage"] = text

    def merge_step_once(self, gid, owner, name, record, merge, url):
        view = self.gh_json(["pr", "view", url, "--json", "state,mergeable,mergeStateStatus,"
                                                          "isDraft,baseRefName,statusCheckRollup"])
        record["next_poll"] = time.time() + MERGE_POLL
        if view is None:
            return
        if view.get("state") == "MERGED":
            self.merged(gid)
            return
        if view.get("state") == "CLOSED":
            self.set_phase(gid, "stopped", reason="PR closed without merging")
            return
        base = view.get("baseRefName") or "main"
        rules = self.branch_rules(owner, name, base)
        action, detail = merge_step(view, merge["attempts"], required=rules["required"])
        key = self.key_of(gid)
        if action == "held":
            held_since = merge.setdefault("held_since", time.time())
            if time.time() - held_since < HOLD_GRACE:
                action, detail = "wait", "GitHub is holding it — usually checks about to start"
            else:
                action = "blocked"
        else:
            merge.pop("held_since", None)
        if action != "blocked" and merge.get("blocked"):
            log("%s: merge no longer blocked — carrying on" % key)
            self.note(gid, "Merge no longer blocked — carrying on")
            merge["blocked"] = None
        if action == "merge":
            method = self.merge_method_for(owner, name, base)
            if not method:
                merge["blocked"] = "no merge method the repo allows"
                return
            self.stage(gid, merge, "merging (%s)" % method)
            code, _, err = run(["gh", "pr", "merge", url, "--" + method], cwd=self.repo)
            if code == 0:
                log("%s: merged (%s)" % (key, method))
                record["next_poll"] = 0
            else:
                merge["blocked"] = "gh pr merge refused: %s" % (err.splitlines() or ["?"])[-1]
        elif action == "ready":
            self.stage(gid, merge, "marking the PR ready")
            run(["gh", "pr", "ready", url], cwd=self.repo)
        elif action == "update":
            self.stage(gid, merge, "bringing the branch up to date")
            code, _, err = run(["gh", "pr", "update-branch", url], cwd=self.repo)
            if code != 0:
                merge["attempts"]["resolve"] = merge["attempts"].get("resolve", 0) + 1
                self.stage(gid, merge, "resolving conflicts")
                self.launch_revise(gid, [], render_merge_resolve(base),
                                   "resolving conflicts with %s, to merge" % base,
                                   ["the branch is behind %s and cannot be updated cleanly; "
                                    "merging %s in" % (base, base)])
        elif action == "resolve":
            merge["attempts"]["resolve"] = merge["attempts"].get("resolve", 0) + 1
            self.stage(gid, merge, "resolving conflicts (%d)" % merge["attempts"]["resolve"])
            log("%s: conflicts with %s — resolving to merge" % (key, base))
            self.launch_revise(gid, [], render_merge_resolve(base),
                               "resolving conflicts with %s, to merge" % base,
                               ["the PR conflicts with %s — likely a sibling merged first; "
                                "merging %s in, keeping both sides' intent" % (base, base)])
        elif action == "fix_ci":
            merge["attempts"]["ci"] = merge["attempts"].get("ci", 0) + 1
            self.stage(gid, merge, "fixing failing checks (%d)" % merge["attempts"]["ci"])
            log("%s: checks failing (%s) — fixing to merge"
                % (key, ", ".join(n for n, _ in detail)))
            excerpts = self.ci_excerpts(detail)
            issues = []
            for check, _ in detail:
                issues.append("%s failed%s" % (check, ":" if excerpts.get(check) else
                                               " (its log could not be read)"))
                issues += ["  %s" % line for line in excerpts.get(check, [])]
            self.launch_revise(gid, [], render_ci_fix(detail, excerpts),
                               "fixing failing checks (%s), to merge"
                               % ", ".join(n for n, _ in detail), issues)
        elif action == "wait":
            self.stage(gid, merge, detail)
        else:
            if merge.get("blocked") != detail:
                log("%s: merge blocked — %s" % (key, detail))
            merge["blocked"] = detail
            record["next_poll"] = time.time() + BLOCKED_POLL

    def pr_base(self, gid):
        """The branch a task's PR targets, as its run recorded it."""
        record = self.record(gid)
        if not record.get("base"):
            base = ((self.start_state(gid).read("context.json") or {}).get("git") or {}).get("base")
            if base:
                record["base"] = base[len("origin/"):] if base.startswith("origin/") else base
        return record.get("base")

    def default_branch(self):
        """The repo's default branch, asked of origin once."""
        if not self.data.get("default_branch"):
            code, out, _ = run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                               cwd=self.main_root)
            if code == 0 and out.startswith("origin/"):
                self.data["default_branch"] = out[len("origin/"):]
            else:
                view = self.gh_json(["repo", "view", "--json", "defaultBranchRef"])
                self.data["default_branch"] = ((view or {}).get("defaultBranchRef") or {}).get("name")
        return self.data.get("default_branch")

    def branch_rules(self, owner, name, base):
        """What the base branch's rules say, asked of GitHub once per run: the
        merge method to use and the checks it requires."""
        cache = self.rules_cache = getattr(self, "rules_cache", {})
        slug = "%s/%s@%s" % (owner, name, base)
        if slug not in cache:
            repo = self.gh_json(["repo", "view", "%s/%s" % (owner, name), "--json",
                                 "squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed"])
            from urllib.parse import quote
            rules = self.gh_json(["api", "repos/%s/%s/rules/branches/%s"
                                  % (owner, name, quote(base, safe=""))])
            methods, required = [], []
            for rule in rules or []:
                params = rule.get("parameters") or {}
                methods += params.get("allowed_merge_methods") or []
                required += [c.get("context") for c in params.get("required_status_checks") or []
                             if c.get("context")]
            cache[slug] = {"method": merge_method(repo or {}, methods),
                           "required": sorted(set(required))}
        return cache[slug]

    def merge_method_for(self, owner, name, base):
        return self.branch_rules(owner, name, base)["method"]

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
        self.busy["loop"] = ("finishing %s in Asana" % key, gid)
        self.record_actual(gid)
        self.asana(["task", "complete", gid])
        code, _ = self.asana(["task", "set-status", gid, "Done"], check=False)
        if code != 0:
            log("%s: could not move to Done" % key)
        hours = self.record(gid).get("actual_hours")
        usage = self.start_state(gid).read(st.USAGE_FILE)
        attached = self.attach_usage(gid, usage)
        if usage:
            self.record(gid)["usage"] = {k: v for k, v in usage.items() if k != "calls_log"}
        self.note(gid, "Merged — finishing up", [
            "Asana: completed%s" % ("" if code else ", moved to Done"),
            "Actual: %.2fh of run time" % hours if hours is not None else "Actual: left alone",
            "tokens: %s over %d agent call(s)%s" % (
                st.usage_summary(usage), usage.get("calls", 0),
                ", each one in the attached %s" % attached if attached else "")
            if usage else "tokens: none reported",
            "worktree: being removed"])
        worktree = (self.start_state(gid).read("context.json") or {}).get("git", {}).get("worktree")
        if worktree and os.path.isdir(worktree) and os.path.abspath(worktree) != self.main_root:
            # Thousands of files in node_modules and .venv: done in a thread that
            # the process waits for on the way out, so it is never left half done.
            threading.Thread(target=self.remove_worktree, args=(key, worktree, gid)).start()
        self.tasks[gid]["completed"] = True
        for task in self.tasks.values():
            for dep in task.get("deps") or []:
                if dep.get("ref") == gid:
                    dep["completed"] = True
        self.set_phase(gid, "merged")
        self.busy.pop("loop", None)
        self.refresh_due = 0

    def attach_usage(self, gid, usage):
        """Attach the task's agent calls to it in Asana as a CSV, one row a call.
        Returns the file's name, or None when there was nothing to attach or the
        upload failed."""
        calls = (usage or {}).get("calls_log")
        if not calls:
            return None
        key = self.key_of(gid)
        name = "token-usage-%s.csv" % key
        state = self.start_state(gid)
        state.ensure()
        path = state.write_text(name, st.usage_csv(key, gid, calls))
        code, _ = self.asana(["task", "attach", gid, path], check=False)
        if code != 0:
            log("%s: could not attach %s (kept at %s)" % (key, name, path))
            return None
        log("%s: attached %s (%d call(s))" % (key, name, len(calls)))
        return name

    def remove_worktree(self, key, worktree, gid=None):
        name = "worktree-%s" % key
        self.busy[name] = ("removing %s's worktree" % key, gid)
        try:
            with st.repo_lock(self.main_root):
                code, _, err = run(["git", "worktree", "remove", worktree], cwd=self.main_root)
            if code != 0:
                log("%s: left the worktree in place (%s)" % (key, err))
        finally:
            self.busy.pop(name, None)

    def record_actual(self, gid):
        """Put the task's run time — what its start-task runs spent working, not
        waiting — in its Actual field, and the tokens its agent calls used in its
        Tokens field; either is left alone when someone already filled it in."""
        key = self.key_of(gid)
        worked = (self.start_state(gid).read(st.TIMING_FILE) or {}).get("worked_seconds")
        usage = self.start_state(gid).read(st.USAGE_FILE)
        hours = actual_hours(worked)
        tokens = sum(int((usage or {}).get(k) or 0) for k in st.USAGE_KEYS) or None
        if hours is None:
            log("%s: no run time recorded — Actual left alone" % key)
        if tokens is None:
            log("%s: no token usage recorded — Tokens left alone" % key)
        if hours is None and tokens is None:
            return
        _, task = self.asana(["task", "get", gid], check=False)
        fields = (task or {}).get("fields") or {}
        for name, value, shown in (("Actual", hours, "%.2fh" % (hours or 0)),
                                   ("Tokens", tokens, "%d" % (tokens or 0))):
            if value is None:
                continue
            if has_value(fields.get(name)):
                log("%s: %s already set (%s) — left alone" % (key, name, fields[name]))
                continue
            code, _ = self.asana(["task", "set-field", gid, name, str(value)], check=False)
            log("%s: %s → %s" % (key, name, shown) if code == 0
                else "%s: could not set %s" % (key, name))
        if hours is not None:
            self.record(gid)["actual_hours"] = hours

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
            kill_tree(pid)
        if proc is not None:
            # Collect its exit, or it lingers as a zombie — dead, but answering
            # "are you there?" as if it were still a run.
            threading.Thread(target=proc.wait, daemon=True).start()

    def kill_all(self):
        """Stop every run this engine launched or adopted, so none outlives it
        unseen. Their records stay as they are; a restart relaunches them."""
        for gid in set(self.children) | {g for g, r in self.records.items() if r.get("pid")}:
            self.kill(gid)

    # loop

    def tick(self):
        self.reap()
        if self.take_refresh():
            self.stop_finished_elsewhere()
        if time.time() >= self.refresh_due and self.refreshing is None:
            self.start_refresh()
        if self.data.get("sprint"):
            for gid in ready_tasks(self.tasks, self.records, self.data["me"]["gid"]):
                self.launch(gid)
        mode = self.data.get("merge_mode") or "asked"
        for gid, record in list(self.records.items()):
            if gid not in self.tasks or mode == "asked":
                continue
            base = self.pr_base(gid)
            if auto_merge_due(mode, record, base, self.default_branch()):
                self.request_merge(gid, auto="merging is set to always" if mode == "always"
                                   else "it targets %s, not the default branch" % base)
        for gid, record in list(self.records.items()):
            if gid in self.tasks and record.get("phase") in ("pr_open", "conflict"):
                self.poll_pr(gid)
        self.save()

    def done(self):
        if self.refreshing is not None or time.time() >= self.refresh_due:
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
