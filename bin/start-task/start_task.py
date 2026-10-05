#!/usr/bin/env python3
#
# start_task.py — the start-task lifecycle as an explicit program.
#
# Control flow is Python. A model is invoked exactly twice, and only where one is
# genuinely required: to implement the task, and to repair a failing QA gate.
# Everything else — fetching, gating, branching, the draft PR, status moves, the
# start/ship comments — is deterministic and costs zero tokens.
#
# Every model call goes through `agent/`, which exposes AgentRequest /
# AgentResult / AgentBackend and nothing else. No vendor name and no SDK import
# appears outside `agent/<backend>.py`, so the provider is a flag: the default
# shells out to `claude -p`, and `--backend claude-sdk` swaps in the Claude Agent
# SDK, which can additionally report the tool calls its harness refused.
#
# See DESIGN.md for the rationale and the phase contract.
#
# Usually reached through the `cortex` dispatcher:
#
#   cortex start-task <task-url>                  # the whole lifecycle
#   cortex start-task <task-url> --phase prologue # one phase, zero model calls
#   cortex start-task <task-id>  --phase qa
#   cortex start-task <task-id>  --status         # phase progress, no work
#   cortex start-task --backends                  # which providers are usable
#
# Dependencies: Python 3 stdlib, git, gh, asana.py (sibling), and whatever the
# selected backend needs (the default needs only `claude` on PATH).

import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import (  # noqa: E402
    DEFAULT_BACKEND, AgentRequest, available_backends, backend_names,
    extract_last_json_block, get_backend, tools_for,
)
from agent.base import USAGE_KEYS, usage_summary  # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
ASANA = os.path.join(HERE, "asana.py")
PROMPTS = os.path.join(HERE, "prompts")
# Everything cortex writes into a repo lives under .cortex/, which ignores itself
# (see `ensure_cortex_dir`). Work happens on the branch being developed, so nothing
# the tool leaves behind should ever turn up in that branch's diff.
CORTEX_DIRNAME = ".cortex"
WORKTREES_DIRNAME = "worktrees"
STATE_DIRNAME = "state"
# Where state used to live: a top-level directory that git could see. Runs that
# predate the move are relocated rather than stranded.
LEGACY_STATE_DIRNAME = ".start-task"

QA_CONFIG = ".start-task.json"

# Lifecycle states meaning "not yet started" — a task in one of these is a candidate
# to start. Mirrors readiness.py's NOT_STARTED_NAMES (the neutral workflow profile).
NOT_STARTED = {
    "requirements", "sizing", "refinement",
    "unassigned", "scheduled", "assigned",
}

PHASES = ("prologue", "implement", "qa", "ship", "revise")

# Turn ceiling applied to every model call. It is a checkpoint rather than a
# limit on the work: a call that hits it is resumed while it keeps making
# changes (see `should_continue`). Development is many small edits, so the
# ceiling is high enough that reaching it usually means something is wrong.
DEFAULT_MAX_TURNS = 300

# What a resumed call is told. The session carries the rest — it is the same
# conversation, not a fresh one that has to be re-briefed.
CONTINUE_PROMPT = (
    "Continue. You stopped at a turn limit, not because the work was finished: "
    "pick up exactly where you left off, and end with the result block you were "
    "asked for once you are done."
)

MAX_QA_ATTEMPTS = 2
INLINE_ATTACHMENT_MAX_BYTES = 256 * 1024

# Every comment the run posts — on the task or the PR — starts with this. The run
# posts as the operator (their token, their gh login), so authorship cannot tell
# its own posts from the operator's replies; the mark can.
BOT_MARK = "\U0001f916 cortex \u00b7"

# How a run ended, for whatever launched it. The same word is in `outcome.json`.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_AWAITING = 3
OUTCOME_FILE = "outcome.json"
# How long runs have worked on the task, summed across every run of it — the
# task's actual time. Waiting on a human does not count, and neither does time
# the machine spends asleep: it is measured on the monotonic clock, which stops
# while the system sleeps (macOS and Linux both).
TIMING_FILE = "timing.json"

# Seconds this process has spent waiting on a reply, so far.
WAITED = [0.0]

# What every agent call for the task has used, summed across all its runs.
USAGE_FILE = "usage.json"


# --- output -----------------------------------------------------------------

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


# --- process helpers --------------------------------------------------------

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


# --- pure helpers (unit-tested) ---------------------------------------------

def slugify(name, max_words=6):
    """Branch-safe slug from a task name: lowercase words, hyphenated, truncated."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return "-".join(words[:max_words]) or "task"


_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")
# Hosts whose links are already handled elsewhere in the flow, or are noise.
_BORING_HOSTS = ("app.asana.com", "github.com", "githubusercontent.com")


def extract_external_links(*texts):
    """URLs worth surfacing to the implement call, de-duplicated, order preserved.

    These are passed through as bare text: the implement call runs with no MCP
    servers, so nothing here can actually read a Figma or Notion page. Surfacing
    them at least lets the agent say what it could not see.
    """
    seen = []
    for text in texts:
        if not isinstance(text, str):
            continue
        for url in _URL_RE.findall(text):
            url = url.rstrip(".,;:")
            if any(h in url for h in _BORING_HOSTS):
                continue
            if url not in seen:
                seen.append(url)
    return seen


def evaluate_gate(task, dependencies, current_user_gid, strict=False, ignore_deps=False,
                  resuming=False):
    """Decide whether a task may be started. Pure: no network, no side effects.

    Returns {blocking: [...], warnings: [...], self_assign: bool}. The caller acts
    on `self_assign` (an unassigned task is claimed, not rejected) and refuses to
    proceed when `blocking` is non-empty.

    `resuming` is a task this run already started: its status moved because of
    us, so a started status is expected rather than a reason to stop.
    """
    blocking = []
    warnings = []
    self_assign = False

    status = (task.get("status") or "").strip().lower()
    if not status:
        if not resuming:
            blocking.append("no status set — expected one of: %s"
                            % ", ".join(sorted(NOT_STARTED)))
    elif status not in NOT_STARTED:
        if resuming:
            warnings.append("status is %r — resuming a run already started"
                            % task.get("status"))
        else:
            blocking.append("status is %r — not a not-yet-started state"
                            % task.get("status"))

    incomplete = [d for d in (dependencies or []) if not d.get("completed")]
    if incomplete:
        names = ", ".join(d.get("name") or "?" for d in incomplete)
        msg = "blocked by %d incomplete dependency/ies: %s" % (len(incomplete), names)
        if ignore_deps:
            warnings.append(msg + " (ignored)")
        else:
            blocking.append(msg)

    assignee_gid = task.get("assignee_gid")
    if not assignee_gid:
        self_assign = True
    elif current_user_gid and assignee_gid != current_user_gid:
        blocking.append("assigned to %s, not you" % (task.get("assignee") or "someone else"))

    estimate = (task.get("fields") or {}).get("Estimate")
    if not estimate:
        (blocking if strict else warnings).append("no Estimate set")

    if strict:
        # Sprint membership is only checked in strict mode: it costs an extra API
        # round-trip and the implementation never reads it.
        boards = [b.get("project") or "" for b in (task.get("board") or [])]
        if not any(re.search(r"sprint", b, re.IGNORECASE) for b in boards):
            blocking.append("not on a sprint board (boards: %s)"
                            % (", ".join(boards) or "none"))

    return {"blocking": blocking, "warnings": warnings, "self_assign": self_assign}


# Result parsing lives in the seam (agent/base.py) — it is identical whatever
# produced the text, and a backend needs it too.


def task_key(task):
    """Human key (MT251-47) when the project has one, else the Asana gid."""
    return task.get("task_id") or task.get("ref")


def mark(body):
    """A comment body as the run posts it: carrying `BOT_MARK`."""
    return "%s %s" % (BOT_MARK, body)


def is_marked(text):
    """Whether a comment is one the run posted itself."""
    return (text or "").lstrip().startswith(BOT_MARK)


def path_matches(path, pattern):
    """A changed file against one entry of a gate's `paths`: the file itself, or a
    directory it sits under. A trailing slash is optional."""
    pattern = pattern.strip().rstrip("/")
    return bool(pattern) and (path == pattern or path.startswith(pattern + "/"))


def select_gates(config, changed):
    """The QA commands that apply to a branch, as [(name, command, cwd)].

    A gate under `gates` runs when a changed file matches one of its `paths`, or
    always when it lists none. `changed` of None means the diff could not be
    worked out, so every gate runs — a gate wrongly skipped ships a break, one
    wrongly run costs minutes. The flat `lint`/`build`/`test` keys predate gates
    and always run.
    """
    out = []
    for gate in config.get("gates") or []:
        if not isinstance(gate, dict) or not gate.get("run"):
            raise ValueError("every gate needs a `run` command: %r" % (gate,))
        paths = gate.get("paths") or []
        if changed is None or not paths or any(
                path_matches(f, p) for f in changed for p in paths):
            out.append((gate.get("name") or gate["run"], gate["run"], gate.get("cwd")))
    out += [(name, config[name], None) for name in ("lint", "build", "test")
            if config.get(name)]
    return out


def build_outcome(status, task_ref, context=None, session=None, reason=None):
    """What a run tells whatever launched it. Built from state, never from the
    console, so a caller needs no knowledge of what the run printed."""
    context = context or {}
    git_info = context.get("git") or {}
    session = session or {}
    return {
        "status": status,
        "task": (context.get("task") or {}).get("id") or task_ref,
        "gid": (context.get("task") or {}).get("gid"),
        "pr_url": git_info.get("pr_url"),
        "branch": git_info.get("branch"),
        "worktree": git_info.get("worktree"),
        "session": {"token": session.get("token"), "backend": session.get("backend"),
                    "command": session.get("command")} if session.get("token") else None,
        "reason": reason,
        "at": time.time(),
    }


def render_prompt(name, **kwargs):
    with open(os.path.join(PROMPTS, name), "r") as f:
        template = f.read()
    for key, value in kwargs.items():
        template = template.replace("{{%s}}" % key, value)
    return template


# --- state ------------------------------------------------------------------

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
        self.ensure()
        with open(self.path(name), "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

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


# --- prologue ---------------------------------------------------------------

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


def find_existing_work(repo, task_id):
    """Existing branch / open PR for this task, if any."""
    git(["fetch", "--prune", "origin"], cwd=repo, check=False)
    _, local, _ = run(
        ["git", "branch", "--list", "*%s*" % task_id, "--format=%(refname:short)"],
        cwd=repo, check=False)
    _, remote, _ = run(
        ["git", "branch", "-r", "--list", "*%s*" % task_id,
         "--format=%(refname:short)"], cwd=repo, check=False)
    branches = [b.strip() for b in (local + "\n" + remote).splitlines() if b.strip()]

    pr_url = None
    code, out, _ = run(
        ["gh", "pr", "list", "--search", task_id, "--state", "open",
         "--json", "url,headRefName"], cwd=repo, check=False)
    if code == 0 and out:
        try:
            prs = json.loads(out)
            if prs:
                pr_url = prs[0].get("url")
        except ValueError:
            pass
    return branches, pr_url


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


def phase_prologue(args):
    repo = os.path.abspath(args.repo)
    main_root = main_repo_root(repo)

    step("Fetching task")
    ref = asana(["ref", "parse", args.task], cwd=repo)
    if not ref:
        die("could not parse %r as an Asana task reference" % args.task)
    ref = ref.strip() if isinstance(ref, str) else str(ref)
    task = asana(["task", "get", ref], cwd=repo)
    me = asana(["user", "me"], cwd=repo)
    deps = asana(["task", "dependencies", ref], cwd=repo) or []
    tid = task_key(task)
    args.task_key = tid
    state = State(main_root, tid)
    recorded = state.read("context.json") or {}
    resuming = ("prologue" in state.phases_done()
                and bool((recorded.get("git") or {}).get("branch")))
    info("%s — %s" % (tid, task.get("name")))
    info("status: %s · assignee: %s · estimate: %s"
         % (task.get("status"), task.get("assignee") or "none",
            (task.get("fields") or {}).get("Estimate") or "none"))

    step("Preconditions")
    gate = evaluate_gate(task, deps, (me or {}).get("gid"), strict=args.strict,
                         ignore_deps=args.ignore_deps, resuming=resuming)
    for w in gate["warnings"]:
        warn(w)
    if gate["blocking"]:
        for b in gate["blocking"]:
            sys.stderr.write("  ✗ %s\n" % b)
        die("preconditions not met — resolve them in Asana and re-run:\n%s"
            % "\n".join("- %s" % b for b in gate["blocking"]))
    if gate["self_assign"]:
        asana(["task", "set-field", ref, "Assignee", (me or {}).get("gid")], cwd=repo)
        info("unassigned — claimed for %s" % (me or {}).get("name"))
    info("ok")

    step("Gathering context")
    subtasks = asana(["task", "subtasks", ref], cwd=repo) or []
    comments = asana(["comment", "list", ref], cwd=repo) or []
    attachments_meta = asana(["task", "attachments", ref], cwd=repo) or []
    info("%d subtask(s) · %d comment(s) · %d attachment(s) · %d dependency/ies"
         % (len(subtasks), len(comments), len(attachments_meta), len(deps)))

    state.ensure()
    attachments = []
    for att in attachments_meta:
        entry = download_attachment(att, os.path.join(state.dir, "attachments"))
        if entry:
            attachments.append(entry)

    links = extract_external_links(
        task.get("description"), *[c.get("text") for c in comments])
    if links:
        warn("%d external link(s) found; they are passed as text only "
             "(no MCP servers in the implement call)" % len(links))

    step("Branch and PR")
    with repo_lock(main_root):
        branch, base, worktree, pr_url = set_up_branch(args, repo, main_root, tid, task)

    step("Updating Asana")
    code, _, errout = run([sys.executable, ASANA, "task", "set-status", ref,
                           "In Progress"], cwd=repo, check=False)
    info("status → In Progress" if code == 0
         else "could not set status: %s" % errout)

    marker = "🏁 Starting work — branch: `%s`" % branch
    if any(marker in (c.get("text") or "") for c in comments):
        info("start comment already present")
    else:
        comment = mark(marker + ("\nPR: %s" % pr_url if pr_url else ""))
        run([sys.executable, ASANA, "comment", "add", ref, comment],
            cwd=repo, check=False)
        info("posted start comment")

    context = {
        "task": {
            "id": tid, "gid": ref, "url": args.task,
            "name": task.get("name"), "description": task.get("description"),
            "category": (task.get("fields") or {}).get("Category"),
            "status": task.get("status"),
            "estimate": (task.get("fields") or {}).get("Estimate"),
            "assignee": task.get("assignee"),
        },
        "subtasks": subtasks,
        "dependencies": deps,
        "comments": comments,
        "attachments": attachments,
        "external_links": links,
        "git": {"branch": branch, "base": base, "worktree": worktree,
                "pr_url": pr_url, "main_root": main_root},
        "repo": {"root": worktree},
    }
    state.write("context.json", context)
    state.mark_done("prologue")

    step("Ready")
    info("context: %s" % state.path("context.json"))
    info("worktree: %s" % worktree)
    info("next: cortex start-task %s --phase implement" % tid)
    return tid


def set_up_branch(args, repo, main_root, tid, task):
    """The task's branch, worktree and draft PR, reusing any that exist. Returns
    (branch, base, worktree, pr_url). Every git write that touches the shared repo is in
    here, so parallel runs can take it one at a time under `repo_lock`."""
    slug = slugify(task.get("name"))
    branch = "%s/%s" % (tid, slug)
    branches, existing_pr = find_existing_work(repo, tid)
    base = resolve_base(repo, args.base)

    ensure_cortex_dir(main_root)
    worktree = worktree_path(main_root, tid, slug)

    # A branch can only be checked out once. Honouring an existing worktree — which
    # may sit at a path an older version of this script chose — keeps work in flight
    # from being stranded when the layout changes.
    _, listing, _ = git(["worktree", "list", "--porcelain"], cwd=repo, check=False)
    for candidate in {branch} | {b.replace("origin/", "") for b in branches}:
        existing_wt = worktree_for_branch(listing, candidate)
        if existing_wt and os.path.isdir(existing_wt):
            if os.path.abspath(existing_wt) != worktree:
                info("branch %s is already checked out at %s — using it"
                     % (candidate, existing_wt))
            worktree = os.path.abspath(existing_wt)
            branch = candidate
            break

    if args.no_worktree:
        worktree = repo
        if branches:
            info("existing branch %s — checking out" % branches[0])
            git(["checkout", branches[0].replace("origin/", "")], cwd=repo)
            branch = branches[0].replace("origin/", "")
        else:
            git(["checkout", "-b", branch, base], cwd=repo)
            info("created %s off %s" % (branch, base))
    elif os.path.isdir(worktree):
        info("worktree already exists at %s" % worktree)
        _, branch, _ = git(["branch", "--show-current"], cwd=worktree)
    elif branches:
        existing = branches[0].replace("origin/", "")
        info("existing branch %s — attaching worktree" % existing)
        git(["worktree", "add", worktree, existing], cwd=repo)
        branch = existing
    else:
        git(["worktree", "add", worktree, "-b", branch, base], cwd=repo)
        _, on, _ = git(["branch", "--show-current"], cwd=worktree, check=False)
        if on != branch:
            die("the worktree came up on %r, not %r — nothing was committed or pushed; "
                "remove %s and the local branch %r, then run again" % (on, branch, worktree, on))
        info("created %s off %s in %s" % (branch, base, worktree))

    pr_url = existing_pr
    if not pr_url:
        code, _, _ = run(["git", "rev-parse", "--verify", "--quiet",
                          "origin/" + branch], cwd=worktree, check=False)
        if code != 0:
            git(["commit", "--allow-empty", "-m",
                 "%s :: %s (start)" % (tid, slugify(task.get("name")))], cwd=worktree)
            git(["push", "-u", "origin", branch], cwd=worktree)
        body = "## Task\n%s\n" % args.task
        code, out, errout = run(
            ["gh", "pr", "create", "--draft", "--base", base.replace("origin/", ""),
             "--head", branch, "--title", "%s :: %s" % (tid, task.get("name")),
             "--body", body], cwd=worktree, check=False)
        if code == 0:
            pr_url = out.strip().splitlines()[-1] if out.strip() else None
            info("draft PR: %s" % pr_url)
        else:
            warn("could not create draft PR: %s" % (errout or out))
    else:
        info("existing PR: %s" % pr_url)
    return branch, base, worktree, pr_url


# --- implement --------------------------------------------------------------

# --- worktrees --------------------------------------------------------------
#
# Worktrees live inside the repo, under .cortex/worktrees/<id>+<slug>. One
# directory holds every task's checkout instead of scattering siblings beside the
# clone, and one directory has to be ignored.


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
    matters: cortex writes into the branch it is working on, and nothing it does
    should turn up in that branch's diff. `*` covers the .gitignore too, so the
    whole directory is invisible to git.
    """
    root = os.path.join(main_root, CORTEX_DIRNAME)
    os.makedirs(os.path.join(root, WORKTREES_DIRNAME), exist_ok=True)
    os.makedirs(os.path.join(root, STATE_DIRNAME), exist_ok=True)
    ignore = os.path.join(root, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w") as f:
            f.write("# Created by cortex. Local scratch — never committed.\n*\n")
    return root


def worktree_for_branch(porcelain, branch):
    """The worktree already checked out on `branch`, or None.

    Parses `git worktree list --porcelain`: blank-line separated records, each
    starting with `worktree <path>` and carrying either `branch <ref>` or
    `detached`. A branch can only be checked out once, so finding it is what lets
    the worktree location move without stranding work already in flight.
    """
    path = None
    for line in (porcelain or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and path:
            ref = line[len("branch "):].strip()
            if ref == "refs/heads/%s" % branch or ref == branch:
                return path
    return None


# --- asking the task manager ------------------------------------------------
#
# An agent that cannot proceed ends its turn with a questions block instead of a
# summary. The orchestrator posts those to the task, waits for a human to reply
# there, and calls the agent again with the answer. The agent seam knows none of
# this: a backend is handed a prompt and returns text, exactly as before.

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
        if isinstance(item, dict):
            question = (item.get("q") or "").strip()
            why = (item.get("why") or "").strip()
        elif isinstance(item, str):
            question, why = item.strip(), ""
        else:
            continue
        if question:
            out.append({"q": question, "why": why})
    return out or None


def format_questions_comment(questions, branch=None):
    """The comment body. It has to tell a human who did not start the run what is
    waiting on them and what to do about it."""
    lines = ["\U0001f914 **Blocked — I need a decision before I can continue.**", ""]
    for n, q in enumerate(questions, 1):
        lines.append("%d. %s" % (n, q["q"]))
        if q.get("why"):
            lines.append("   _%s_" % q["why"])
    lines += ["", "Reply on this task and the run picks up automatically — any "
                  "comment here will do."]
    if branch:
        lines += ["", "Branch: `%s`" % branch]
    return "\n".join(lines)


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


def checkpoint_problems(context, isdir=None):
    """Reasons the recorded progress should not be trusted for a resume. Empty
    means state.json and the filesystem still agree."""
    if isdir is None:
        isdir = os.path.isdir
    if not context:
        return ["no context.json — the checkpoint is incomplete"]
    problems = []
    worktree = ((context.get("git") or {}).get("worktree"))
    if worktree and not isdir(worktree):
        problems.append("recorded worktree is gone: %s" % worktree)
    return problems


def phases_to_run(phases, done):
    """The phases still outstanding, in order. `done` is what state.json recorded;
    a name in it that is no longer a phase is simply not in the result."""
    return [p for p in phases if p not in done]


# Failures that are about the provider's capacity, not the task: wait them out.
_LIMIT = re.compile(r"session limit|usage limit|rate.?limit|overloaded|too many requests|"
                    r"\b429\b|\b529\b|quota", re.IGNORECASE)
_RESETS = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*(?:\(([^)]+)\))?",
                     re.IGNORECASE)
LIMIT_RETRY = 900
# Calls cut off from outside — the machine slept, the connection dropped — are
# made again shortly, continuing the same session when there is one.
_INTERRUPTED = re.compile(r"went to sleep|computer was asleep|connection (?:error|lost|reset)|"
                          r"econnreset|socket hang up|network error|stream (?:was )?(?:closed|"
                          r"suspended|interrupted)", re.IGNORECASE)
INTERRUPTED_RETRY = 30


def interrupted(text):
    """Whether an agent call was cut off from outside rather than failing."""
    return bool(text and _INTERRUPTED.search(text))


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


def failure_detail(result, tail=2000):
    """Why a backend call failed, in one string. A non-zero exit with an empty
    stderr says nothing on its own — the reason is in whatever the provider
    printed, so fall through to the tail of that rather than report the exit
    code alone."""
    error = (getattr(result, "error", None) or "").strip()
    if error:
        return error
    text = (getattr(result, "text", None) or "").strip()
    if text:
        return "no error reported; last %d chars of output:\n%s" % (tail, text[-tail:])
    return "unknown error — the backend produced no output"


def record_session(state, label, cwd, backend, result):
    """Keep the agent's session so a person can pick the conversation up by hand.

    Overwritten by every call: the newest one is the live conversation, and it is
    the only one anybody asks for.
    """
    if state is None or not result.resume_token:
        return
    state.write("session.json", {
        "label": label,
        "token": result.resume_token,
        "backend": backend.name,
        "cwd": cwd,
        "command": backend.resume_command(result.resume_token, cwd),
        "at": time.time(),
    })


def report_session(state):
    """Print how to take over the agent's last session, when the backend offers a
    way in. Printed as recorded — a session the provider has since expired is not
    something this can check, and claiming otherwise would be worse than stale."""
    session = (state.read("session.json") or {}) if state else {}
    if not session.get("command"):
        return
    info("")
    info("continue this session yourself (%s):" % session.get("label"))
    info("  %s" % session["command"])


def worktree_fingerprint(cwd):
    """What the worktree looks like right now, in one string. `status --porcelain`
    as well as `diff --stat`, so a stretch of work that only added new files still
    reads as progress."""
    _, status, _ = git(["status", "--porcelain"], cwd=cwd, check=False)
    _, stat, _ = git(["diff", "--stat"], cwd=cwd, check=False)
    return "%s\n%s" % ((status or "").strip(), (stat or "").strip())


def should_continue(result, fingerprint, previous):
    """Whether a call that came back should be resumed. Returns (go, reason),
    where a reason is a stop the operator should hear about.

    The turn ceiling is a checkpoint, not the end of the work, so a call that hits
    it is picked up where it left off. Progress is the guard: a call that burns a
    whole ceiling without touching the worktree is going in circles, and resuming
    it again would only cost more.
    """
    if result.stop_reason != "max_turns":
        return False, None
    if not result.resume_token:
        return False, "this backend cannot resume a call"
    if fingerprint == previous:
        return False, "it reached the limit again without changing anything"
    return True, None


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


def call_agent(prompt, cwd, args, label, autonomy=None, state=None, ref=None,
               resume=None):
    """One unit of work for a model, through the seam. A call stopped by the turn
    ceiling is resumed for as long as it keeps changing the worktree, so the
    ceiling bounds a single call and not the task. Returns the final AgentResult.

    `resume` continues an earlier session instead of starting one; a session the
    provider no longer has is replaced by a fresh call with the same prompt. A call
    that fails, or stalls at the ceiling, goes to the task (`ref`) when the run
    waits on failures, and is retried with the reply.
    """
    autonomy = autonomy or args.autonomy
    backend = get_backend(args.backend)
    usable, reason = backend.available()
    if not usable:
        die("backend %r is unavailable: %s" % (args.backend, reason))

    first_resume = resume
    next_prompt, previous, hop = prompt, None, 0
    while True:
        hop += 1
        request = AgentRequest(
            prompt=next_prompt,
            cwd=cwd,
            model=args.model,
            allowed_tools=tools_for(autonomy),
            autonomy=autonomy,
            max_turns=args.max_turns,
            load_project_context=not args.no_project_context,
            resume=resume,
            extra={"argv": args.agent_cmd} if args.agent_cmd else {},
        )
        info("%s: calling %s%s"
             % (label, backend.name, " (continuation %d)" % hop if hop > 1 else ""))
        result = backend.run(request)

        for item in result.unsupported:
            warn("%s ignored %s (not supported by this backend)"
                 % (backend.name, item))
        if result.denied_tools:
            warn("%d tool call(s) were denied: %s — the agent may have done less "
                 "than asked; consider --autonomy full or an allowlist"
                 % (len(result.denied_tools),
                    ", ".join(sorted(set(result.denied_tools)))))
        info("%s: %s" % (label, result.summary()))
        record_usage(state, label, result.usage)
        if not result.ok:
            if first_resume and hop == 1:
                warn("%s: could not resume the earlier session (%s) — starting a "
                     "fresh one" % (label, failure_detail(result)))
                resume, next_prompt, first_resume = None, prompt, None
                continue
            reason = failure_detail(result)
            if state is not None and result.text:
                warn("raw output kept at %s" % state.write_text(
                    "%s.failure.log" % label, result.text))
            pause = limit_pause(reason, time.time())
            if pause:
                wait_out_limit(state, label, *pause)
                continue
            if interrupted(reason):
                warn("%s was cut off (%s) — going on in %ds%s"
                     % (label, reason.splitlines()[0][:120], INTERRUPTED_RETRY,
                        ", in the same session" if result.resume_token else ""))
                slept = time.monotonic()
                time.sleep(INTERRUPTED_RETRY)
                WAITED[0] += time.monotonic() - slept
                if result.resume_token:
                    resume, next_prompt = result.resume_token, CONTINUE_PROMPT
                continue
            headline = "The agent call failed while %s: %s" % (
                doing(label), reason.splitlines()[0][:200])
            if state is None or ref is None:
                die("%s\n%s" % (headline, reason))
            raise_problem(state, ref, cwd, args, "agent", headline, reason)
            continue

        fingerprint = worktree_fingerprint(cwd)
        go, stopped_because = should_continue(result, fingerprint, previous)
        if go:
            info("%s: hit the turn limit, resuming the session" % label)
            resume, previous, next_prompt = result.resume_token, fingerprint, CONTINUE_PROMPT
            continue
        record_session(state, label, cwd, backend, result)
        if stopped_because:
            warn("%s stopped at the turn limit — %s" % (label, stopped_because))
        if (stopped_because and result.resume_token and state is not None
                and ref is not None and getattr(args, "wait_on_failure", False)):
            answer = raise_problem(state, ref, cwd, args, "stall",
                                   "%s stopped at the turn limit — %s"
                                   % (label, stopped_because))
            resume, previous = result.resume_token, None
            next_prompt = "The operator replied:\n\n%s\n\n%s" % (answer, CONTINUE_PROMPT)
            continue
        return result


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


def ask_task(questions, ref, cwd, state, label, args):
    """The agent's questions, posted to the task; returns the reply."""
    context = state.read("context.json", {})
    branch = (context.get("git") or {}).get("branch")
    step("Blocked — asking %s" % ref)
    for q in questions:
        info("Q: %s" % q["q"])
    return escalate(state, ref, cwd, args, "questions",
                    format_questions_comment(questions, branch),
                    {"label": label, "questions": questions})


def format_problem_comment(headline, detail=None, branch=None):
    """A stop that is not the agent's question — QA still red, a push refused, a
    stalled call, a failed step — in a form a human can act on from the task."""
    lines = ["\u26a0\ufe0f **%s**" % headline]
    if detail:
        lines += ["", "```", detail.strip()[-1500:], "```"]
    lines += ["", "Fix it or tell me how, then reply on this task — the run picks "
                  "up from your reply."]
    if branch:
        lines += ["", "Branch: `%s`" % branch]
    return "\n".join(lines)


def raise_problem(state, ref, cwd, args, kind, headline, detail=None):
    """Post a problem and wait for the reply, or — outside a full run, where a
    human is at the terminal — stop with it as before. Returns the reply."""
    if not getattr(args, "wait_on_failure", False):
        die("%s%s" % (headline, "\n" + detail if detail else ""), escalate=False)
    branch = ((state.read("context.json", {}).get("git")) or {}).get("branch")
    step("Stopped — asking %s" % ref)
    warn(headline)
    return escalate(state, ref, cwd, args, kind,
                    format_problem_comment(headline, detail, branch),
                    {"headline": headline,
                     "detail": (detail or "").strip()[-1500:] or None})


def render_resume_section(worktree, transcript):
    """What to append so a fresh call can continue work it has no memory of. The
    session is gone — the worktree and this transcript are all that survive."""
    _, stat, _ = git(["diff", "--stat"], cwd=worktree, check=False)
    lines = ["", "---", "", "## Your earlier attempt", "",
             "You worked on this task in this worktree and stopped to ask a question.",
             "You do not remember doing it, but the changes are still here:", "",
             "```", (stat or "").strip() or "(nothing changed yet)", "```", "",
             "### What you asked, and the answer", ""]
    for round_ in transcript:
        for q in round_["questions"]:
            lines.append("- **Q:** %s" % q["q"])
        lines.append("- **A:** %s" % (round_["answer"] or "(no answer given)"))
        lines.append("")
    lines += ["Continue from what is already in the worktree. Do not start over, and",
              "do not undo work you cannot account for — it is yours.", ""]
    return "\n".join(lines)


def call_agent_resumable(build_prompt, cwd, args, label, ref, state, autonomy=None,
                         resume=None):
    """Call the agent, and when it comes back blocked, ask the task and call again
    with the answer. Returns the first result that is work rather than a question.

    A question still pending from an earlier run is waited on first, so a restart
    neither asks it twice nor carries on without its answer. The loop is unbounded:
    a question is never treated as done.
    """
    transcript = []
    pending = state.read("awaiting.json") or {}
    if pending_kind(pending) == "questions" and pending.get("label") == label:
        questions = pending.get("questions") or []
        answer = ask_task(questions, ref, cwd, state, label, args)
        transcript.append({"questions": questions, "answer": answer})
    while True:
        outcome = call_agent(build_prompt(transcript), cwd, args, label,
                             autonomy=autonomy, state=state, ref=ref, resume=resume)
        resume = None
        questions = parse_agent_questions(outcome.structured)
        if questions is None:
            return outcome
        answer = ask_task(questions, ref, cwd, state, label, args)
        transcript.append({"questions": questions, "answer": answer})


def phase_implement(args, state=None):
    state = state or State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    context = state.read("context.json")
    if not context:
        die("no context.json — run `prologue` first")
    worktree = context["repo"]["root"]

    step("Implementing")
    attachment_note = "\n".join(
        "- %s%s" % (a["name"], " (image, at %s)" % a["path"] if a["is_image"]
                    else "\n```\n%s\n```" % a["inline"] if a.get("inline")
                    else " (at %s)" % a["path"])
        for a in context["attachments"]) or "(none)"

    def build_prompt(transcript):
        prompt = render_prompt(
            "implement.md",
            context=json.dumps(context["task"], indent=2),
            subtasks=json.dumps(context["subtasks"], indent=2),
            comments=json.dumps(context["comments"], indent=2),
            attachments=attachment_note,
            links="\n".join("- %s" % u for u in context["external_links"]) or "(none)",
            branch=context["git"]["branch"],
        )
        return prompt + render_resume_section(worktree, transcript) if transcript else prompt

    outcome = call_agent_resumable(build_prompt, worktree, args, "implement",
                                   context["task"]["gid"], state)
    result = outcome.structured
    if result is None:
        warn("agent returned no structured block — falling back to raw text summary")
        result = {"summary": outcome.text.strip()[:2000],
                  "files_changed": [], "notes": ""}
    state.write("result.json", result)
    state.mark_done("implement")

    info("summary: %s" % (result.get("summary") or "")[:160])
    info("files: %d" % len(result.get("files_changed") or []))
    return state


# --- qa ---------------------------------------------------------------------

def qa_config(worktree):
    path = os.path.join(worktree, QA_CONFIG)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (IOError, OSError):
        return None
    except ValueError as e:
        die("%s is not valid JSON (%s)" % (path, e))


def changed_files(worktree, base):
    """Every file the branch touches against its base — committed, staged, unstaged
    and untracked. None when the base cannot be found, which runs every gate."""
    code, merge_base, _ = git(["merge-base", "HEAD", base], cwd=worktree, check=False)
    if code != 0 or not merge_base:
        return None
    _, diff, _ = git(["diff", "--name-only", merge_base], cwd=worktree, check=False)
    _, untracked, _ = git(["ls-files", "--others", "--exclude-standard"],
                          cwd=worktree, check=False)
    return sorted({f for f in (diff + "\n" + untracked).splitlines() if f.strip()})


def qa_commands(worktree, base):
    config = qa_config(worktree)
    if config is None:
        return None
    changed = changed_files(worktree, base)
    try:
        return select_gates(config, changed)
    except ValueError as e:
        die("%s: %s" % (QA_CONFIG, e))


def run_qa_gate(commands, worktree):
    """Run each command in order. Returns (name, cmd, output) of the first failure,
    or None when the whole gate is green."""
    for name, cmd, subdir in commands:
        cwd = os.path.join(worktree, subdir) if subdir else worktree
        info("%s: %s%s" % (name, cmd, " (in %s)" % subdir if subdir else ""))
        proc = subprocess.run(cmd, cwd=cwd, shell=True, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = proc.stdout.decode("utf-8", "replace")
        if proc.returncode != 0:
            warn("%s failed (exit %d)" % (name, proc.returncode))
            return (name, cmd, output)
        info("%s ok" % name)
    return None


def phase_qa(args, state=None):
    state = state or State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    context = state.read("context.json")
    worktree = context["repo"]["root"]
    ref = context["task"]["gid"]

    step("QA")
    commands = qa_commands(worktree, context["git"].get("base") or "origin/main")
    if commands is None:
        warn("no %s in %s — skipping QA" % (QA_CONFIG, worktree))
        state.mark_done("qa")
        return state
    if not commands:
        info("no gate in %s applies to the files this branch changed" % QA_CONFIG)
        state.mark_done("qa")
        return state

    failure = run_qa_gate(commands, worktree)
    attempt, guidance = 0, None
    while failure:
        if attempt >= MAX_QA_ATTEMPTS:
            name, _, output = failure
            state.write("qa.json", {"passed": False, "stage": name,
                                    "attempts": attempt, "output": output[-8000:]})
            guidance = raise_problem(
                state, ref, worktree, args, "qa",
                "QA gate still failing at %r after %d repair attempt(s) — not shipping"
                % (name, attempt), output)
            attempt = 0
        attempt += 1
        name, cmd, output = failure
        info("repair attempt %d/%d" % (attempt, MAX_QA_ATTEMPTS))
        prompt = render_prompt(
            "qa_fix.md",
            task=json.dumps(context["task"], indent=2),
            stage=name, command=cmd,
            output=output[-8000:],
        )
        if guidance:
            prompt += "\n\n## From the operator\n\n%s\n" % guidance
        call_agent(prompt, worktree, args, "qa-repair-%d" % attempt, state=state, ref=ref)
        failure = run_qa_gate(commands, worktree)

    state.write("qa.json", {"passed": True, "attempts": attempt})
    state.mark_done("qa")
    info("gate green")
    return state


# --- ship -------------------------------------------------------------------

def commit_and_push(context, message, args, state):
    """Commit whatever the worktree holds and push the branch. A push that fails
    is a stop, not a warning: an unpushed branch is a PR that does not show the
    work it claims."""
    worktree = context["repo"]["root"]
    branch = context["git"]["branch"]
    _, dirty, _ = git(["status", "--porcelain"], cwd=worktree)
    if dirty:
        git(["add", "-A"], cwd=worktree)
        git(["commit", "-m", message], cwd=worktree)
        info("committed working tree")
    while True:
        code, _, errout = git(["push", "-u", "origin", branch], cwd=worktree, check=False)
        if code == 0:
            info("pushed %s" % branch)
            return
        raise_problem(state, context["task"]["gid"], worktree, args, "push",
                      "could not push %s" % branch, errout)


def lookup_pr(branch, cwd):
    """The open PR for a branch, when the context lost track of it."""
    code, out, _ = run(["gh", "pr", "list", "--head", branch, "--state", "open",
                        "--json", "url"], cwd=cwd, check=False)
    if code != 0 or not out:
        return None
    try:
        prs = json.loads(out)
    except ValueError:
        return None
    return prs[0].get("url") if prs else None


def phase_ship(args, state=None):
    state = state or State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    context = state.read("context.json")
    result = state.read("result.json", {})
    worktree = context["repo"]["root"]
    ref = context["task"]["gid"]
    branch = context["git"]["branch"]

    step("Shipping")
    commit_and_push(context, "%s :: %s" % (
        context["task"]["id"],
        (result.get("summary") or context["task"]["name"]).splitlines()[0][:70],
    ), args, state)

    pr_url = context["git"].get("pr_url")
    while not pr_url:
        pr_url = lookup_pr(branch, worktree)
        if not pr_url:
            raise_problem(state, ref, worktree, args, "pr",
                          "there is no open PR for %s" % branch)
    if pr_url != context["git"].get("pr_url"):
        context["git"]["pr_url"] = pr_url
        state.write("context.json", context)

    files = result.get("files_changed") or []
    body = "## Task\n%s\n\n## What changed\n%s\n" % (
        context["task"]["url"], result.get("summary") or "(no summary)")
    if files:
        body += "\n## Files\n%s\n" % "\n".join("- `%s`" % f for f in files)
    if result.get("notes"):
        body += "\n## Notes\n%s\n" % result["notes"]
    run(["gh", "pr", "edit", pr_url, "--body", body], cwd=worktree, check=False)
    while True:
        code, _, errout = run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
        if code == 0:
            info("PR marked ready: %s" % pr_url)
            break
        raise_problem(state, ref, worktree, args, "pr",
                      "could not mark %s ready for review" % pr_url, errout)

    repo = context["git"]["main_root"]
    code, _, errout = run([sys.executable, ASANA, "task", "set-status", ref,
                           "In Review"], cwd=repo, check=False)
    info("status → In Review" if code == 0 else "could not set status: %s" % errout)

    comment = mark("🚀 Shipped — %s\n\n%s" % (pr_url, result.get("summary") or ""))
    run([sys.executable, ASANA, "comment", "add", ref, comment],
        cwd=repo, check=False)
    info("posted ship comment")
    state.mark_done("ship")
    return state


# --- revise -----------------------------------------------------------------
#
# Review feedback on a shipped PR, applied in the task's own worktree — in the
# agent's own session when it can still be resumed — then QA'd, pushed and
# answered on the PR. Not part of a full run: it is what happens after one.

def read_feedback(args):
    if args.feedback_file:
        try:
            with open(args.feedback_file, "r") as f:
                return f.read().strip()
        except (IOError, OSError) as e:
            die("cannot read --feedback-file %s (%s)" % (args.feedback_file, e),
                escalate=False)
    return (args.feedback or "").strip()


def phase_revise(args, state=None):
    state = state or State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    context = state.read("context.json")
    if not context:
        die("no context.json — run the task first", escalate=False)
    feedback = read_feedback(args)
    if not feedback:
        die("revise needs the feedback: --feedback or --feedback-file", escalate=False)
    worktree = context["repo"]["root"]
    ref = context["task"]["gid"]
    pr_url = context["git"].get("pr_url")
    if not os.path.isdir(worktree):
        die("the worktree is gone: %s" % worktree)

    step("Fetching the base")
    with repo_lock(context["git"]["main_root"]):
        git(["fetch", "origin"], cwd=worktree, check=False)
    info("origin fetched — %s is current" % (context["git"].get("base") or "origin/main"))

    step("Applying the feedback")
    for line in [l for l in feedback.splitlines() if l.strip()][:6]:
        info("› %s" % line.strip()[:110])
    session = state.read("session.json") or {}
    resume = session.get("token") if session.get("backend") == args.backend else None
    info("resuming the task's own session %s" % resume if resume
         else "no session to resume — a fresh, fully briefed call")

    def build_prompt(transcript):
        prompt = render_prompt(
            "revise.md",
            task=json.dumps(context["task"], indent=2),
            branch=context["git"]["branch"],
            base=context["git"].get("base") or "origin/main",
            pr=pr_url or "(none)",
            feedback=feedback,
        )
        return prompt + render_resume_section(worktree, transcript) if transcript else prompt

    outcome = call_agent_resumable(build_prompt, worktree, args, "revise", ref, state,
                                   resume=resume)
    result = outcome.structured or {"summary": outcome.text.strip()[:2000]}
    info("done: %s" % (result.get("summary") or "(no summary)").splitlines()[0][:140])
    phase_qa(args, state)
    step("Pushing")
    commit_and_push(context, "%s :: address review feedback" % context["task"]["id"],
                    args, state)

    reply = (result.get("reply") or result.get("summary") or "").strip()
    if pr_url:
        step("Replying on the PR")
        body = mark("Addressed review feedback\n\n%s" % (reply or "(no summary)"))
        while True:
            code, _, errout = run(["gh", "pr", "comment", pr_url, "--body", body],
                                  cwd=worktree, check=False)
            if code == 0:
                info("replied on %s" % pr_url)
                break
            raise_problem(state, ref, worktree, args, "pr",
                          "could not reply on %s" % pr_url, errout)
    state.write("revise.json", {"at": time.time(), "summary": result.get("summary"),
                                "reply": reply})
    return state


# --- run / status -----------------------------------------------------------

# Prologue is not in this table: it is idempotent (existing worktree, branch, PR
# and start comment are all detected) and re-running it refreshes the task context,
# so a resumed run always starts by re-reading Asana.
RESUMABLE = ("implement", "qa", "ship")


def acquire_run(state):
    """Claim the task for this process, or stop when another live run has it."""
    other = live_run_pid(state.read("run.json"))
    if other and other != os.getpid():
        die("another run for %s is already going (pid %d). Wait for it, or kill it:\n"
            "  kill %d" % (state.task_id, other, other), escalate=False)
    state.write("run.json", {"pid": os.getpid(), "started": time.time()})


def phase_run(args):
    """Every phase in order. Anything that stops it short of a ready PR is posted
    to the task, and the run waits for a reply and goes again from the top: the
    prologue is idempotent and every later phase is skipped once done."""
    args.wait_on_failure = True
    url = args.task
    state = None
    try:
        while True:
            args.task = url
            try:
                tid = phase_prologue(args)
                state = State(main_repo_root(os.path.abspath(args.repo)), tid)
                acquire_run(state)
                run_remaining(state, args)
                break
            except Failure as failure:
                tid = getattr(args, "task_key", None)
                if not failure.escalate or not tid:
                    raise
                state = State(main_repo_root(os.path.abspath(args.repo)), tid)
                ref = (state.read("context.json", {}).get("task") or {}).get("gid")
                if not ref:
                    ref = asana(["ref", "parse", url], cwd=os.path.abspath(args.repo))
                sys.stderr.write("\nstart-task: %s\n" % failure)
                headline = "The run stopped: %s" % str(failure).splitlines()[0]
                escalate(state, str(ref).strip(), os.path.abspath(args.repo), args,
                         "failure", format_problem_comment(headline, str(failure)),
                         {"headline": headline, "detail": str(failure)[-1500:]})
    finally:
        if state is not None and live_run_pid(state.read("run.json")) == os.getpid():
            state.remove("run.json")
    args.task = tid
    state.remove("awaiting.json")
    step("Done")
    info("task %s shipped" % tid)
    report_session(state)


def run_remaining(state, args):
    done = state.phases_done()
    problems = checkpoint_problems(state.read("context.json", {}))
    if problems and done:
        for problem in problems:
            warn(problem)
        warn("recorded progress no longer matches the filesystem — running every "
             "phase rather than trusting it")
        done = set()

    for phase in RESUMABLE:
        if phase in done:
            info("%s already done — skipping (--phase %s to redo)" % (phase, phase))
    for phase in phases_to_run(RESUMABLE, done):
        state = PHASE_HANDLERS[phase](args, state) or state


def phase_status(args):
    state = State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    done = state.phases_done()
    context = state.read("context.json", {})
    step("start-task %s" % args.task)
    for phase in PHASES:
        info("[%s] %s" % ("x" if phase in done else " ", phase))
    if context:
        info("")
        info("branch:   %s" % context.get("git", {}).get("branch"))
        info("worktree: %s" % context.get("git", {}).get("worktree"))
        info("PR:       %s" % context.get("git", {}).get("pr_url"))

    info("")
    record = state.read("run.json")
    pid = live_run_pid(record)
    if pid:
        info("running:  pid %d (kill %d to stop it)" % (pid, pid))
    elif record:
        warn("a run recorded pid %s but that process is gone — it crashed or was killed"
             % record.get("pid"))
    else:
        info("running:  no")

    report_session(state)

    awaiting = state.read("awaiting.json")
    if awaiting:
        warn("waiting on a reply in the task since %s (%s):"
             % (awaiting.get("asked_at"), awaiting.get("kind") or "questions"))
        if awaiting.get("headline"):
            info("  %s" % awaiting["headline"])
        for q in awaiting.get("questions") or []:
            info("  Q: %s" % q.get("q"))

    outcome = state.read(OUTCOME_FILE)
    if outcome:
        info("last outcome: %s%s" % (outcome.get("status"),
                                     " — %s" % outcome["reason"].splitlines()[0]
                                     if outcome.get("reason") else ""))

    for problem in checkpoint_problems(context):
        warn(problem)


# --- cli --------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="cortex start-task",
        description="Run the start-task lifecycle as an explicit program, "
                    "with every model call behind a provider-agnostic seam. "
                    "Given a task, runs every phase in order; --phase runs one.")
    parser.add_argument("task", nargs="?",
                        help="task URL, or the task id (e.g. MT251-47) once the "
                             "prologue has resolved one")
    parser.add_argument("--phase", default=None, choices=PHASES,
                        help="run this phase alone instead of all of them")
    parser.add_argument("--status", action="store_true",
                        help="report phase progress and do no work")
    parser.add_argument("--backends", action="store_true",
                        help="list providers and whether they are usable here")

    parser.add_argument("--repo", default=os.getcwd(),
                        help="target repository (default: cwd)")
    parser.add_argument("--base", default=None,
                        help="base branch (default: origin/main)")
    parser.add_argument("--no-worktree", action="store_true",
                        help="branch in the current directory instead of a worktree")
    parser.add_argument("--strict", action="store_true",
                        help="make Estimate and sprint membership blocking")
    parser.add_argument("--ignore-deps", action="store_true",
                        help="warn instead of blocking on incomplete dependencies")
    parser.add_argument("--no-wait", action="store_true",
                        help="post a question or problem to the task and exit (code "
                             "%d) instead of waiting; a rerun picks the reply up"
                             % EXIT_AWAITING)
    parser.add_argument("--feedback", default=None,
                        help="revise: the review feedback to apply")
    parser.add_argument("--feedback-file", default=None,
                        help="revise: read the feedback from this file")
    parser.add_argument("--result-file", default=None,
                        help="also write the run's outcome JSON here")

    parser.add_argument("--backend", default=DEFAULT_BACKEND,
                        choices=backend_names(),
                        help="agent provider (default: %(default)s)")
    parser.add_argument("--model", default=None,
                        help="model override; backend default when unset")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        help="turn ceiling per call (default: %(default)s)")
    parser.add_argument("--no-project-context", action="store_true",
                        help="do not load the repo's CLAUDE.md / AGENTS.md")
    parser.add_argument("--agent-cmd", default=None,
                        help="override the backend's command wholesale, where it "
                             "has one (escape hatch for a stalled permission mode)")
    parser.add_argument("--autonomy", default="full",
                        choices=("read-only", "edit", "full"),
                        help="what the agent may do (default: %(default)s)")
    return parser


def phase_backends(args):
    step("Backends")
    for name, usable, reason in available_backends():
        marker = "x" if usable else " "
        default = "  (default)" if name == DEFAULT_BACKEND else ""
        info("[%s] %-12s%s%s" % (marker, name, default,
                                 "" if usable else "  — %s" % reason))


PHASE_HANDLERS = {
    "prologue": phase_prologue,
    "implement": phase_implement,
    "qa": phase_qa,
    "ship": phase_ship,
    "revise": phase_revise,
}


def add_usage(total, usage, label):
    """A task's usage total with one more call in it. Pure."""
    total = dict(total or {})
    for key in USAGE_KEYS:
        total[key] = int(total.get(key) or 0) + int(usage.get(key) or 0)
    total["cost_usd"] = round(float(total.get("cost_usd") or 0) + float(usage.get("cost_usd") or 0), 6)
    total["calls"] = int(total.get("calls") or 0) + 1
    by = dict(total.get("by_call") or {})
    kind = "qa-repair" if label.startswith("qa-repair") else label
    by[kind] = int(by.get(kind) or 0) + sum(int(usage.get(k) or 0) for k in USAGE_KEYS)
    total["by_call"] = by
    return total


def record_usage(state, label, usage):
    """Add a call's tokens to the task's total as soon as the call is back, so
    a run stopped part-way still counts what it used."""
    if state is None or not usage:
        return
    state.write(USAGE_FILE, add_usage(state.read(USAGE_FILE), usage, label))


def task_state(args):
    """The task's state, when the run got far enough to have one."""
    tid = getattr(args, "task_key", None) or args.task
    try:
        state = State(main_repo_root(os.path.abspath(args.repo)), tid)
    except Failure:
        return None
    return state if os.path.isdir(state.dir) else None


def record_work(args, seconds):
    """Add this run's working time to the task's total. Every run of a task adds
    its own, so a resumed or revised task sums what each run did."""
    state = task_state(args)
    if state is None or seconds <= 0:
        return
    timing = state.read(TIMING_FILE) or {}
    timing["worked_seconds"] = round((timing.get("worked_seconds") or 0) + seconds, 1)
    timing["runs"] = (timing.get("runs") or 0) + 1
    state.write(TIMING_FILE, timing)


def write_outcome(args, status, reason=None):
    """Record how the run ended in the task's state and, when asked, at
    --result-file. Whatever launched the run reads this, never the console."""
    tid = getattr(args, "task_key", None) or args.task
    state = task_state(args)
    outcome = build_outcome(status, tid,
                            state.read("context.json") if state else None,
                            state.read("session.json") if state else None,
                            reason)
    if state:
        state.write(OUTCOME_FILE, outcome)
    if args.result_file:
        with open(args.result_file, "w") as f:
            json.dump(outcome, f, indent=2)
            f.write("\n")


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.backends:
        phase_backends(args)
        return EXIT_OK
    if args.task is None:
        parser.error("a task URL or id is required")
    if args.status:
        phase_status(args)
        return EXIT_OK
    # A stop from outside unwinds like Ctrl-C, so the time worked is still kept.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
    started = time.monotonic()
    try:
        return run_task(args)
    finally:
        record_work(args, time.monotonic() - started - WAITED[0])


def run_task(args):
    try:
        if args.phase == "revise":
            args.wait_on_failure = True
            state = State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
            acquire_run(state)
            try:
                phase_revise(args, state)
            finally:
                state.remove("run.json")
            report_session(state)
            status = "revised"
        elif args.phase:
            # Handlers return the state they worked in; the prologue returns a task
            # id and has no session to report.
            outcome = PHASE_HANDLERS[args.phase](args)
            if isinstance(outcome, State):
                report_session(outcome)
            status = "done"
        else:
            phase_run(args)
            status = "shipped"
    except Awaiting as waiting:
        info(str(waiting))
        write_outcome(args, "awaiting", str(waiting))
        return EXIT_AWAITING
    except Failure as failure:
        sys.stderr.write("\nstart-task: %s\n" % failure)
        write_outcome(args, "failed", str(failure))
        return EXIT_FAILED
    write_outcome(args, status)
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        # Every phase records itself as it completes, so stopping here costs only
        # the phase in flight. Say so, rather than dumping a traceback.
        sys.stderr.write("\n\nstart-task: interrupted — finished phases are saved.\n"
                         "  progress:  start-task <task-id> --status\n"
                         "  continue:  start-task <task-id>\n")
        sys.exit(130)
