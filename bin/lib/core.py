#!/usr/bin/env python3
#
# core.py — what goals, the TUI and the queue share: git, Asana, a goal's state,
# its questions and answers, worktrees, usage limits and the comment marks.

import contextlib
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent.base import USAGE_KEYS, usage_summary  # noqa: E402,F401


HERE = os.path.dirname(os.path.abspath(__file__))
ASANA = os.path.join(HERE, "asana.py")


# Everything conductor writes into a repo lives under .cortex/, which ignores itself
# (see `ensure_cortex_dir`). Work happens on the branch being developed, so nothing
# the tool leaves behind should ever turn up in that branch's diff.
CORTEX_DIRNAME = ".cortex"


WORKTREES_DIRNAME = "worktrees"
STATE_DIRNAME = "state"


# Where state used to live: a top-level directory that git could see. Runs that
# predate the move are relocated rather than stranded.
LEGACY_STATE_DIRNAME = ".start-task"


INLINE_ATTACHMENT_MAX_BYTES = 256 * 1024


# Every comment the run posts — on the task or the PR — starts with this. The run
# posts as the operator (their token, their gh login), so authorship cannot tell
# its own posts from the operator's replies; the mark can. Runs from before the
# rename posted `LEGACY_BOT_MARK`, and those posts are still the run's own.
BOT_MARK = "\U0001f916 conductor \u00b7"


LEGACY_BOT_MARK = "\U0001f916 cortex \u00b7"


# A goal shows its questions and plan on its ticket, as subtasks of its own: their
# name starts with the robot and their description has the mark. The queue and the
# boards leave those subtasks out: they are the goal's, not work to queue.
GOAL_NAME = "\U0001f916 "


GOAL_MADE = "Planned by a conductor goal"
LEGACY_GOAL_MADE = "Planned by a cortex goal"


def made_by_goal(task):
    task = task or {}
    description = task.get("description") or ""
    return (task.get("name") or "").startswith(GOAL_NAME.strip()) \
        or GOAL_MADE in description or LEGACY_GOAL_MADE in description


# Seconds this process has spent waiting on a reply, so far.
WAITED = [0.0]


# What every agent call for the task has used, summed across all its runs.
USAGE_FILE = "usage.json"


def info(msg):
    sys.stdout.write("  %s\n" % msg)
    sys.stdout.flush()


def step(msg):
    # Bold on a terminal; in a log file, plain text with the time, so a slow step
    # shows as one.
    if sys.stdout.isatty():
        sys.stdout.write("\n\033[1m%s\033[0m\n" % msg)
    else:
        sys.stdout.write("\n%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def warn(msg):
    sys.stdout.write("  ! %s\n" % msg)
    sys.stdout.flush()


class Failure(Exception):
    """The run cannot go on. Raised rather than exiting, so a full run can post it
    to the task and wait instead of dying, and so every exit writes an outcome."""


    def __init__(self, msg, escalate=True):
        Exception.__init__(self, msg)
        self.escalate = escalate


class Awaiting(Exception):
    """A question is posted and --no-wait says not to sit on it."""


def die(msg, escalate=True):
    raise Failure(msg, escalate=escalate)


def run(cmd, cwd=None, check=True, capture=True):
    """Run a command. Returns (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    out = proc.stdout.decode("utf-8", "replace").strip() if capture else ""
    errout = proc.stderr.decode("utf-8", "replace").strip() if capture else ""
    if check and proc.returncode != 0:
        die("`%s` failed (exit %d)\n%s" % (" ".join(cmd), proc.returncode, errout or out))
    return proc.returncode, out, errout


def git(args, cwd, check=True):
    return run(["git"] + args, cwd=cwd, check=check)


def asana(args, cwd):
    """Invoke asana.py and parse its JSON stdout.


    cwd matters: asana.py derives its per-repo cache key (and thus its custom-field
    map) from the git remote of the working directory, so it must run in the target
    repo, not in this script's directory.
    """
    code, out, errout = run([sys.executable, ASANA] + args, cwd=cwd, check=False)
    if code != 0:
        die("asana.py %s failed (exit %d)\n%s" % (" ".join(args), code, errout or out))
    if not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return out


def slugify(name, max_words=6):
    """Branch-safe slug from a task name: lowercase words, hyphenated, truncated."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return "-".join(words[:max_words]) or "task"


def task_key(task):
    """Human key (MT251-47) when the project has one, else the Asana gid."""
    return task.get("task_id") or task.get("ref")


def mark(body):
    """A comment body as the run posts it: carrying `BOT_MARK`."""
    return "%s %s" % (BOT_MARK, body)


def is_marked(text):
    """Whether a comment is one the run posted itself."""
    return (text or "").lstrip().startswith((BOT_MARK, LEGACY_BOT_MARK))


class State(object):
    """Per-task working state, at the MAIN repo root — not in the worktree, which
    does not exist when the prologue starts writing and may be removed after ship."""


    def __init__(self, main_root, task_id):
        self.dir = os.path.join(main_root, CORTEX_DIRNAME, STATE_DIRNAME, task_id)
        self.legacy_dir = os.path.join(main_root, LEGACY_STATE_DIRNAME, task_id)
        self.main_root = main_root
        self.task_id = task_id


    def ensure(self):
        self.migrate_legacy()
        # Via ensure_cortex_dir, so the ignore file is in place before anything
        # is written under it — not one run later.
        ensure_cortex_dir(self.main_root)
        os.makedirs(os.path.join(self.dir, "attachments"), exist_ok=True)


    def migrate_legacy(self):
        """Move state written before it lived under `.cortex/`. A task in flight
        keeps its phases, its session and its answers; the alternative is a run
        that reports no state for work it did yesterday."""
        if os.path.isdir(self.dir) or not os.path.isdir(self.legacy_dir):
            return
        ensure_cortex_dir(self.main_root)
        os.makedirs(os.path.dirname(self.dir), exist_ok=True)
        os.rename(self.legacy_dir, self.dir)
        info("moved %s state into %s" % (self.task_id, self.dir))
        try:
            os.rmdir(os.path.dirname(self.legacy_dir))
        except OSError:
            pass  # other tasks still there


    def path(self, name):
        return os.path.join(self.dir, name)


    def remove(self, name):
        try:
            os.remove(self.path(name))
        except OSError:
            pass


    def write_text(self, name, text):
        """Persist raw text beside the JSON state. Returns the path, for printing."""
        path = self.path(name)
        with open(path, "w") as f:
            f.write(text)
        return path


    def read(self, name, default=None):
        try:
            with open(self.path(name), "r") as f:
                return json.load(f)
        except (IOError, OSError, ValueError):
            return default


    def write(self, name, data):
        """Written whole, then moved into place: a reader at the same moment sees the
        old file or the new one, never an empty one."""
        self.ensure()
        path = self.path(name)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)


    def phases_done(self):
        return set(self.read("state.json", {}).get("done", []))


    def mark_done(self, phase):
        current = self.read("state.json", {"done": []})
        done = [p for p in current.get("done", []) if p != phase] + [phase]
        current["done"] = done
        self.write("state.json", current)


    @staticmethod
    def find(main_root, task_id):
        state = State(main_root, task_id)
        state.migrate_legacy()
        if not os.path.isdir(state.dir):
            die("no state for %s — run `prologue` first (looked in %s)"
                % (task_id, state.dir))
        return state


def main_repo_root(cwd):
    """The primary worktree's root, so state lands in one place regardless of
    which worktree the command is run from."""
    code, out, _ = run(
        ["git", "worktree", "list", "--porcelain"], cwd=cwd, check=False)
    if code == 0:
        for line in out.splitlines():
            if line.startswith("worktree "):
                return line[len("worktree "):].strip()
    _, top, _ = git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return top


def download_attachment(att, dest_dir):
    """Save an attachment; inline small text ones. Returns the manifest entry, or
    None when the download failed (a missing attachment is not fatal)."""
    url = att.get("download_url")
    name = att.get("name") or "attachment"
    if not url:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    path = os.path.join(dest_dir, safe)
    try:
        with urllib.request.urlopen(url) as resp:
            body = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        warn("could not download attachment %r (%s)" % (name, e))
        return None
    with open(path, "wb") as f:
        f.write(body)


    entry = {"name": name, "path": os.path.join("attachments", safe),
             "is_image": att.get("is_image", False), "bytes": len(body)}
    if not entry["is_image"] and len(body) <= INLINE_ATTACHMENT_MAX_BYTES:
        try:
            entry["inline"] = body.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return entry


def base_ref(name):
    """A base branch as the remote-tracking ref to branch off. Always origin/…:
    given a bare branch name that exists only on the remote — `feature/x` —
    `git worktree add -b` ignores -b and checks out a new local `feature/x`."""
    return name if name.startswith("origin/") else "origin/" + name


def resolve_base(repo, explicit):
    """Base ref, read from the remote — the local base branch is never checked out."""
    if explicit:
        return base_ref(explicit)
    git(["fetch", "origin"], cwd=repo, check=False)
    code, _, _ = run(["git", "rev-parse", "--verify", "--quiet", "origin/main"],
                     cwd=repo, check=False)
    if code == 0:
        return "origin/main"
    code, out, _ = run(["git", "symbolic-ref", "--quiet",
                        "refs/remotes/origin/HEAD"], cwd=repo, check=False)
    if code == 0 and out:
        resolved = out.replace("refs/remotes/", "")
        warn("origin/main not found — using %s" % resolved)
        return resolved
    die("could not resolve a base branch (no origin/main, no origin/HEAD)")


def create_draft_pr(tid, name, task_url, base, branch, cwd):
    """Open the task's draft PR. (url, None), or (None, what gh said)."""
    code, out, errout = run(
        ["gh", "pr", "create", "--draft", "--base", base.replace("origin/", ""),
         "--head", branch, "--title", "%s :: %s" % (tid, name),
         "--body", "## Task\n%s\n" % task_url], cwd=cwd, check=False)
    if code == 0 and out.strip():
        return out.strip().splitlines()[-1], None
    return None, (errout or out or "gh pr create failed").strip()


def worktree_path(main_root, task_id, slug=None):
    """Where a task's worktree belongs: `<repo>/.cortex/worktrees/<id>+<slug>`.


    The slug is in the name because a human scanning the directory should be able
    to tell what each worktree is for; the id alone does not say. Any separator in
    the slug is flattened, so the name is always a single directory.
    """
    name = task_id
    slug = (slug or "").strip().strip("/")
    if slug:
        name = "%s+%s" % (task_id, slug.replace("/", "-"))
    return os.path.abspath(
        os.path.join(main_root, CORTEX_DIRNAME, WORKTREES_DIRNAME, name))


@contextlib.contextmanager
def repo_lock(main_root):
    """Hold the repo's git lock. Parallel runs share one object store and one set
    of refs; `fetch --prune` and `worktree add` racing each other is how a
    worktree ends up half-made, so those go through here one run at a time."""
    ensure_cortex_dir(main_root)
    with open(os.path.join(main_root, CORTEX_DIRNAME, "git.lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ensure_cortex_dir(main_root):
    """Create `.cortex/` and make it ignore itself.


    A self-ignoring directory leaves the repo's own `.gitignore` untouched, which
    matters: conductor writes into the branch it is working on, and nothing it does
    should turn up in that branch's diff. `*` covers the .gitignore too, so the
    whole directory is invisible to git.
    """
    root = os.path.join(main_root, CORTEX_DIRNAME)
    os.makedirs(os.path.join(root, WORKTREES_DIRNAME), exist_ok=True)
    os.makedirs(os.path.join(root, STATE_DIRNAME), exist_ok=True)
    ignore = os.path.join(root, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w") as f:
            f.write("# Created by conductor. Local scratch — never committed.\n*\n")
    return root
POLL_START = 30
POLL_CAP = 120


# An answer can also be handed over locally — by the TUI — as a file in the
# task's state. It is looked for this often, so it lands at once rather than on
# the next Asana poll.
ANSWER_FILE = "answer.json"


ANSWER_CHECK = 1


def parse_agent_questions(structured):
    """The questions an agent is blocked on, or None when it is not blocked.


    Anything that is not a non-empty list of usable questions is "not blocked" —
    a malformed block must fall through to the existing raw-text handling rather
    than strand the run waiting for an answer to nothing.
    """
    if not isinstance(structured, dict):
        return None
    raw = structured.get("questions")
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        name = ""
        if isinstance(item, dict):
            question = (item.get("q") or "").strip()
            why = (item.get("why") or "").strip()
            name = (item.get("title") or "").strip()
        elif isinstance(item, str):
            question, why = item.strip(), ""
        else:
            continue
        if question:
            entry = dict({"q": question, "why": why}, **({"title": name} if name else {}))
            options = question_options(item) if isinstance(item, dict) else []
            if options:
                entry["options"] = options
            if isinstance(item, dict) and str(item.get("recommend") or "").strip():
                entry["recommend"] = str(item["recommend"]).strip()
            out.append(entry)
    return out or None


def question_options(item):
    """A question's options, each a label, the flow it means and what it changes:
    the usable ones only."""
    out = []
    for o in item.get("options") or []:
        if not isinstance(o, dict) or not str(o.get("label") or "").strip():
            continue
        flow = [str(x).strip() for x in o.get("flow") or [] if str(x).strip()]
        out.append(dict({"label": str(o["label"]).strip(), "flow": flow},
                        **({"means": str(o["means"]).strip()} if str(o.get("means") or "").strip() else {})))
    return out


def options_lines(q, indent=""):
    """A question's options as lines a person reads: each label, its flow as
    numbered steps, and what choosing it means."""
    lines = []
    for o in q.get("options") or []:
        lines.append("%s%s" % (indent, o["label"]))
        lines += ["%s   %d. %s" % (indent, n, step) for n, step in enumerate(o.get("flow") or [], 1)]
        if o.get("means"):
            lines.append("%s   → %s" % (indent, o["means"]))
        lines.append("")
    if q.get("recommend"):
        lines += ["%sSuggested: %s" % (indent, q["recommend"]), ""]
    return lines


def question_brief(q):
    """A question as one line for an agent: the question and its options' labels."""
    labels = "; ".join(o["label"] for o in q.get("options") or [])
    return "%s%s" % (q["q"], " (options: %s)" % labels if labels else "")


def select_answer(comments, watermark):
    """The first comment that answers the question: posted after `watermark`, not
    carrying `BOT_MARK`, with something in it.


    There is deliberately no author filter. The run comments with the operator's
    own token, so "ignore our own comments" would discard the very reply it waits
    for; the mark is what tells the run's posts apart. The watermark is the
    question comment's created_at — minted by the task manager, so it needs no
    agreement with the local clock.
    """
    for comment in comments or []:
        created = comment.get("created_at") or ""
        if not created or created <= watermark:
            continue
        if is_marked(comment.get("text")):
            continue
        if not (comment.get("text") or "").strip():
            continue
        return comment
    return None


def local_answer(record, asked_at):
    """The text of an answer handed over locally, when it answers the question
    asked at `asked_at`. One left over from an earlier question is not it."""
    if not isinstance(record, dict) or record.get("asked_at") != asked_at:
        return None
    return (record.get("text") or "").strip() or None


def poll_interval(attempt, start=POLL_START, cap=POLL_CAP):
    """Seconds to wait before the next check. Doubles to `cap` so an overnight
    wait costs a handful of requests rather than a thousand."""
    return min(cap, start * (2 ** max(0, attempt - 1)))


def live_run_pid(record, is_alive=None):
    """The pid of a run still going for this task, or None.


    A pid recorded in state whose process is gone is a crashed or killed run, and
    saying so is the point: it is how an abandoned checkpoint is told from one
    another terminal is still working on.
    """
    if is_alive is None:
        is_alive = _pid_alive
    if not isinstance(record, dict):
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    return pid if is_alive(pid) else None


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


# Failures that are about the provider's capacity, not the task: wait them out.
_LIMIT = re.compile(r"session limit|usage limit|rate.?limit|overloaded|too many requests|"
                    r"\b429\b|\b529\b|quota", re.IGNORECASE)


_RESETS = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*(?:\(([^)]+)\))?",
                     re.IGNORECASE)
LIMIT_RETRY = 900


def limit_pause(text, now):
    """When an agent call failed on a usage or rate limit: (what it said, seconds
    to wait) — until the reset it names, a minute after, or LIMIT_RETRY when it
    names none. None for any other failure."""
    if not text or not _LIMIT.search(text):
        return None
    what = text.strip().splitlines()[0][:200]
    m = _RESETS.search(text)
    if not m:
        return what, LIMIT_RETRY
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if half == "pm" and hour != 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    zone = None
    if m.group(4):
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(m.group(4).strip())
        except Exception:
            zone = None
    current = datetime.datetime.fromtimestamp(now, zone) if zone else datetime.datetime.fromtimestamp(now)
    try:
        reset = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return what, LIMIT_RETRY
    if reset <= current:
        reset += datetime.timedelta(days=1)
    return what, (reset - current).total_seconds() + 60


def doing(label):
    """What an agent call was for, the way a person says it."""
    if label.startswith("qa-repair-"):
        return "repairing a failing QA gate (attempt %s)" % label.rsplit("-", 1)[1]
    return {"implement": "implementing the task",
            "revise": "applying the review feedback"}.get(label, label)


def worktree_fingerprint(cwd):
    """What the worktree looks like right now, in one string. `status --porcelain`
    as well as `diff --stat`, so a stretch of work that only added new files still
    reads as progress."""
    _, status, _ = git(["status", "--porcelain"], cwd=cwd, check=False)
    _, stat, _ = git(["diff", "--stat"], cwd=cwd, check=False)
    return "%s\n%s" % ((status or "").strip(), (stat or "").strip())


def wait_out_limit(state, label, what, seconds):
    """Sit out a usage or rate limit, then let the call be made again. Not the
    task's problem and nothing for a person to answer, so nothing is posted; the
    pause is recorded for whoever is watching, and not counted as run time."""
    until = time.time() + seconds
    step("Paused — %s" % what)
    info("resumes at %s (in %s) — nothing to do; the run carries on by itself"
         % (time.strftime("%H:%M", time.localtime(until)), _elapsed(int(seconds))))
    if state is not None:
        state.write("paused.json", {"reason": what, "until": until, "label": label})
    try:
        while time.time() < until:
            slept = time.monotonic()
            time.sleep(min(30, max(1, until - time.time())))
            WAITED[0] += time.monotonic() - slept
    finally:
        if state is not None:
            state.remove("paused.json")
    info("resuming %s" % doing(label))


def _elapsed(seconds):
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm%02ds" % (seconds // 60, seconds % 60)
    return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


def pending_kind(pending):
    """What an `awaiting.json` is waiting on. One written before there were kinds
    is an agent's questions — the only thing that could be pending then."""
    if not isinstance(pending, dict):
        return None
    return pending.get("kind") or ("questions" if pending.get("questions") else None)


def escalate(state, ref, cwd, args, kind, body, extra=None):
    """Post `body` to the task and block until someone replies there. Returns the
    reply's text.


    Every way a run can stop short of a ready PR comes through here, so none of
    them is silent. A question already pending for the same `kind` is not posted
    again: a run restarted mid-wait picks the wait up, and a reply that came in
    while nothing was running still counts. Unbounded on purpose — an idle wait is
    one request every two minutes. `--no-wait` posts and stops instead.
    """
    pending = state.read("awaiting.json") or {}
    if pending_kind(pending) == kind and pending.get("asked_at"):
        watermark = pending["asked_at"]
        info("already asked at %s — checking for a reply" % watermark)
    else:
        story = asana(["comment", "add", ref, mark(body)], cwd=cwd)
        watermark = (story or {}).get("created_at")
        if not watermark:
            die("posted to the task but the task manager returned no timestamp — "
                "cannot tell a reply from the post itself", escalate=False)
        record = {"kind": kind, "task": ref, "asked_at": watermark}
        record.update(extra or {})
        state.write("awaiting.json", record)
        info("posted to the task")
    if args.no_wait:
        raise Awaiting("waiting on a reply in the task (%s)" % kind)
    info("waiting for a reply (Ctrl-C to stop; progress is saved)")
    attempt, waited, next_poll, next_note = 0, 0, 0, 600
    while True:
        text = local_answer(state.read(ANSWER_FILE), watermark)
        if text:
            info("answer handed over locally after %s" % _elapsed(waited))
            state.remove(ANSWER_FILE)
            state.remove("awaiting.json")
            return text
        if waited >= next_poll:
            answer = select_answer(asana(["comment", "list", ref], cwd=cwd), watermark)
            if answer:
                info("reply from %s after %s" % (answer.get("author") or "someone",
                                                 _elapsed(waited)))
                state.remove(ANSWER_FILE)
                state.remove("awaiting.json")
                return (answer.get("text") or "").strip()
            attempt += 1
            next_poll = waited + poll_interval(attempt)
        slept = time.monotonic()
        time.sleep(ANSWER_CHECK)
        waited += ANSWER_CHECK
        WAITED[0] += time.monotonic() - slept
        if waited >= next_note:
            info("still waiting (%s)" % _elapsed(waited))
            next_note += 600


def add_usage(total, usage, label, model=None, at=None):
    """A task's usage total with one more call in it, and that call on its own
    in `calls_log` — when, what for, which model, every count — for analysis
    later. Pure."""
    total = dict(total or {})
    total["calls_log"] = list(total.get("calls_log") or []) + [dict(
        {k: int(usage.get(k) or 0) for k in USAGE_KEYS},
        at=at, kind="qa-repair" if label.startswith("qa-repair") else label, label=label,
        model=model, cost_usd=float(usage.get("cost_usd") or 0))]
    for key in USAGE_KEYS:
        total[key] = int(total.get(key) or 0) + int(usage.get(key) or 0)
    total["cost_usd"] = round(float(total.get("cost_usd") or 0) + float(usage.get("cost_usd") or 0), 6)
    total["calls"] = int(total.get("calls") or 0) + 1
    by = dict(total.get("by_call") or {})
    kind = "qa-repair" if label.startswith("qa-repair") else label
    by[kind] = int(by.get(kind) or 0) + sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
    total["by_call"] = by
    return total
