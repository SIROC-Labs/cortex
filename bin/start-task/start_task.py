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
import json
import os
import re
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

HERE = os.path.dirname(os.path.abspath(__file__))
ASANA = os.path.join(HERE, "asana.py")
PROMPTS = os.path.join(HERE, "prompts")
STATE_DIRNAME = ".start-task"
QA_CONFIG = ".start-task.json"

# Lifecycle states meaning "not yet started" — a task in one of these is a candidate
# to start. Mirrors readiness.py's NOT_STARTED_NAMES (the neutral workflow profile).
NOT_STARTED = {
    "requirements", "sizing", "refinement",
    "unassigned", "scheduled", "assigned",
}

PHASES = ("prologue", "implement", "qa", "ship")

# Turn ceiling applied to every model call, so a wedged run stops grinding.
DEFAULT_MAX_TURNS = 60

MAX_QA_ATTEMPTS = 2
INLINE_ATTACHMENT_MAX_BYTES = 256 * 1024


# --- output -----------------------------------------------------------------

def info(msg):
    sys.stdout.write("  %s\n" % msg)
    sys.stdout.flush()


def step(msg):
    sys.stdout.write("\n\033[1m%s\033[0m\n" % msg)
    sys.stdout.flush()


def warn(msg):
    sys.stdout.write("  ! %s\n" % msg)
    sys.stdout.flush()


def die(msg, code=1):
    sys.stderr.write("\nstart-task: %s\n" % msg)
    sys.exit(code)


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


def evaluate_gate(task, dependencies, current_user_gid, strict=False, ignore_deps=False):
    """Decide whether a task may be started. Pure: no network, no side effects.

    Returns {blocking: [...], warnings: [...], self_assign: bool}. The caller acts
    on `self_assign` (an unassigned task is claimed, not rejected) and refuses to
    proceed when `blocking` is non-empty.
    """
    blocking = []
    warnings = []
    self_assign = False

    status = (task.get("status") or "").strip().lower()
    if not status:
        blocking.append("no status set — expected one of: %s"
                        % ", ".join(sorted(NOT_STARTED)))
    elif status not in NOT_STARTED:
        blocking.append("status is %r — not a not-yet-started state" % task.get("status"))

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
        self.dir = os.path.join(main_root, STATE_DIRNAME, task_id)
        self.main_root = main_root
        self.task_id = task_id

    def ensure(self):
        os.makedirs(os.path.join(self.dir, "attachments"), exist_ok=True)

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


def resolve_base(repo, explicit):
    """Base ref, read from the remote — the local base branch is never checked out."""
    if explicit:
        return explicit if "/" in explicit else "origin/" + explicit
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
    info("%s — %s" % (tid, task.get("name")))
    info("status: %s · assignee: %s · estimate: %s"
         % (task.get("status"), task.get("assignee") or "none",
            (task.get("fields") or {}).get("Estimate") or "none"))

    step("Preconditions")
    gate = evaluate_gate(task, deps, (me or {}).get("gid"), strict=args.strict,
                         ignore_deps=args.ignore_deps)
    for w in gate["warnings"]:
        warn(w)
    if gate["blocking"]:
        for b in gate["blocking"]:
            sys.stderr.write("  ✗ %s\n" % b)
        die("preconditions not met — resolve them in Asana and re-run")
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

    state = State(main_root, tid)
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
    branch = "%s/%s" % (tid, slugify(task.get("name")))
    branches, existing_pr = find_existing_work(repo, tid)
    base = resolve_base(repo, args.base)

    repo_name = os.path.basename(main_root.rstrip("/"))
    worktree = os.path.abspath(
        os.path.join(main_root, "..", "%s-%s" % (repo_name, tid)))

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

    step("Updating Asana")
    code, _, errout = run([sys.executable, ASANA, "task", "set-status", ref,
                           "In Progress"], cwd=repo, check=False)
    info("status → In Progress" if code == 0
         else "could not set status: %s" % errout)

    marker = "🏁 Starting work — branch: `%s`" % branch
    if any(marker in (c.get("text") or "") for c in comments):
        info("start comment already present")
    else:
        comment = marker + ("\nPR: %s" % pr_url if pr_url else "")
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


# --- implement --------------------------------------------------------------

# --- asking the task manager ------------------------------------------------
#
# An agent that cannot proceed ends its turn with a questions block instead of a
# summary. The orchestrator posts those to the task, waits for a human to reply
# there, and calls the agent again with the answer. The agent seam knows none of
# this: a backend is handed a prompt and returns text, exactly as before.

POLL_START = 30
POLL_CAP = 120


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
    """The first comment that answers the question: posted after `watermark`, with
    something in it.

    There is deliberately no author filter. The run comments with the operator's
    own token, so "ignore our own comments" would discard the very reply it waits
    for. The watermark alone excludes the question comment, because the watermark
    IS that comment's created_at — minted by the task manager, so it needs no
    agreement with the local clock.
    """
    for comment in comments or []:
        created = comment.get("created_at") or ""
        if not created or created <= watermark:
            continue
        if not (comment.get("text") or "").strip():
            continue
        return comment
    return None


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


def call_agent(prompt, cwd, args, label, autonomy=None, state=None):
    """One model call, through the seam. Returns an AgentResult."""
    autonomy = autonomy or args.autonomy
    backend = get_backend(args.backend)
    usable, reason = backend.available()
    if not usable:
        die("backend %r is unavailable: %s" % (args.backend, reason))

    request = AgentRequest(
        prompt=prompt,
        cwd=cwd,
        model=args.model,
        allowed_tools=tools_for(autonomy),
        autonomy=autonomy,
        max_turns=args.max_turns,
        load_project_context=not args.no_project_context,
        extra={"argv": args.agent_cmd} if args.agent_cmd else {},
    )
    info("%s: calling %s" % (label, backend.name))
    result = backend.run(request)

    for item in result.unsupported:
        warn("%s ignored %s (not supported by this backend)" % (backend.name, item))
    if result.denied_tools:
        warn("%d tool call(s) were denied: %s — the agent may have done less "
             "than asked; consider --autonomy full or an allowlist"
             % (len(result.denied_tools), ", ".join(sorted(set(result.denied_tools)))))
    info("%s: %s" % (label, result.summary()))
    if not result.ok:
        saved = ""
        if state is not None and result.text:
            saved = "\n  raw output: %s" % state.write_text(
                "%s.failure.log" % label, result.text)
        die("%s failed: %s%s" % (label, failure_detail(result), saved))
    return result



def _elapsed(seconds):
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm%02ds" % (seconds // 60, seconds % 60)
    return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


def ask_task(questions, ref, cwd, state, label):
    """Post the questions to the task and block until someone replies there.

    Unbounded on purpose: an idle wait is one request every two minutes, so the
    run simply sits there. Ctrl-C leaves `awaiting.json` behind, which is what
    tells a later run — or a human — what it was waiting for.
    """
    context = state.read("context.json", {})
    branch = (context.get("git") or {}).get("branch")

    step("Blocked — asking %s" % ref)
    for q in questions:
        info("Q: %s" % q["q"])

    story = asana(["comment", "add", ref, format_questions_comment(questions, branch)],
                  cwd=cwd)
    watermark = (story or {}).get("created_at")
    if not watermark:
        die("posted the question but the task manager returned no timestamp — "
            "cannot tell a reply from the question itself")
    info("posted — waiting for a reply (Ctrl-C to stop; progress is saved)")
    state.write("awaiting.json", {"label": label, "task": ref,
                                  "asked_at": watermark, "questions": questions})

    attempt, waited = 0, 0
    while True:
        attempt += 1
        delay = poll_interval(attempt)
        time.sleep(delay)
        waited += delay
        comments = asana(["comment", "list", ref], cwd=cwd)
        answer = select_answer(comments, watermark)
        if answer:
            info("answer from %s after %s" % (answer.get("author") or "someone",
                                              _elapsed(waited)))
            state.remove("awaiting.json")
            return (answer.get("text") or "").strip()
        if waited % 600 < delay:
            info("still waiting (%s)" % _elapsed(waited))


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


def call_agent_resumable(build_prompt, cwd, args, label, ref, state, autonomy=None):
    """Call the agent, and when it comes back blocked, ask the task and call again
    with the answer. Returns the first result that is work rather than a question.

    The loop is unbounded: `--no-ask` is the way out, not a round cap.
    """
    transcript = []
    while True:
        outcome = call_agent(build_prompt(transcript), cwd, args, label,
                             autonomy=autonomy, state=state)
        questions = parse_agent_questions(outcome.structured)
        if questions is None:
            return outcome
        if args.no_ask:
            warn("agent asked %d question(s) but --no-ask is set — treating as done"
                 % len(questions))
            return outcome
        answer = ask_task(questions, ref, cwd, state, label)
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

def qa_commands(worktree):
    path = os.path.join(worktree, QA_CONFIG)
    try:
        with open(path, "r") as f:
            config = json.load(f)
    except (IOError, OSError):
        return None
    except ValueError as e:
        die("%s is not valid JSON (%s)" % (path, e))
    return [(name, config[name]) for name in ("lint", "build", "test")
            if config.get(name)]


def run_qa_gate(commands, worktree):
    """Run each command in order. Returns (name, cmd, output) of the first failure,
    or None when the whole gate is green."""
    for name, cmd in commands:
        info("%s: %s" % (name, cmd))
        proc = subprocess.run(cmd, cwd=worktree, shell=True,
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

    step("QA")
    commands = qa_commands(worktree)
    if commands is None:
        warn("no %s in %s — skipping QA" % (QA_CONFIG, worktree))
        state.mark_done("qa")
        return state
    if not commands:
        warn("%s defines no lint/build/test commands — skipping QA" % QA_CONFIG)
        state.mark_done("qa")
        return state

    failure = run_qa_gate(commands, worktree)
    attempt = 0
    while failure and attempt < MAX_QA_ATTEMPTS:
        attempt += 1
        name, cmd, output = failure
        info("repair attempt %d/%d" % (attempt, MAX_QA_ATTEMPTS))
        prompt = render_prompt(
            "qa_fix.md",
            task=json.dumps(context["task"], indent=2),
            stage=name, command=cmd,
            output=output[-8000:],
        )
        call_agent(prompt, worktree, args, "qa-repair-%d" % attempt, state=state)
        failure = run_qa_gate(commands, worktree)

    if failure:
        name, _, output = failure
        state.write("qa.json", {"passed": False, "stage": name,
                                "attempts": attempt, "output": output[-8000:]})
        die("QA gate still failing at %r after %d repair attempt(s) — not shipping"
            % (name, attempt))

    state.write("qa.json", {"passed": True, "attempts": attempt})
    state.mark_done("qa")
    info("gate green")
    return state


# --- ship -------------------------------------------------------------------

def phase_ship(args, state=None):
    state = state or State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    context = state.read("context.json")
    result = state.read("result.json", {})
    worktree = context["repo"]["root"]
    ref = context["task"]["gid"]
    pr_url = context["git"]["pr_url"]

    step("Shipping")
    _, dirty, _ = git(["status", "--porcelain"], cwd=worktree)
    if dirty:
        git(["add", "-A"], cwd=worktree)
        git(["commit", "-m", "%s :: %s" % (
            context["task"]["id"],
            (result.get("summary") or context["task"]["name"]).splitlines()[0][:70],
        )], cwd=worktree)
        info("committed working tree")
    git(["push", "origin", context["git"]["branch"]], cwd=worktree, check=False)

    if pr_url:
        files = result.get("files_changed") or []
        body = "## Task\n%s\n\n## What changed\n%s\n" % (
            context["task"]["url"], result.get("summary") or "(no summary)")
        if files:
            body += "\n## Files\n%s\n" % "\n".join("- `%s`" % f for f in files)
        if result.get("notes"):
            body += "\n## Notes\n%s\n" % result["notes"]
        run(["gh", "pr", "edit", pr_url, "--body", body], cwd=worktree, check=False)
        code, _, errout = run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
        info("PR marked ready: %s" % pr_url if code == 0
             else "could not mark PR ready: %s" % errout)
    else:
        warn("no PR URL in context — skipping PR promotion")

    repo = context["git"]["main_root"]
    code, _, errout = run([sys.executable, ASANA, "task", "set-status", ref,
                           "In Review"], cwd=repo, check=False)
    info("status → In Review" if code == 0 else "could not set status: %s" % errout)

    comment = "🚀 Shipped — %s\n\n%s" % (
        pr_url or context["git"]["branch"], result.get("summary") or "")
    run([sys.executable, ASANA, "comment", "add", ref, comment],
        cwd=repo, check=False)
    info("posted ship comment")
    state.mark_done("ship")
    return state


# --- run / status -----------------------------------------------------------

# Prologue is not in this table: it is idempotent (existing worktree, branch, PR
# and start comment are all detected) and re-running it refreshes the task context,
# so a resumed run always starts by re-reading Asana.
RESUMABLE = ("implement", "qa", "ship")


def phase_run(args):
    tid = phase_prologue(args)
    args.task = tid
    state = State(main_repo_root(os.path.abspath(args.repo)), tid)

    other = live_run_pid(state.read("run.json"))
    if other and other != os.getpid():
        die("another run for %s is already going (pid %d). Wait for it, or kill it:\n"
            "  kill %d" % (tid, other, other))
    state.write("run.json", {"pid": os.getpid(), "started": time.time()})

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

    try:
        for phase in phases_to_run(RESUMABLE, done):
            state = PHASE_HANDLERS[phase](args, state) or state
    finally:
        state.remove("run.json")
    step("Done")
    info("task %s shipped" % tid)


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

    awaiting = state.read("awaiting.json")
    if awaiting:
        warn("waiting on an answer in the task since %s:" % awaiting.get("asked_at"))
        for q in awaiting.get("questions") or []:
            info("  Q: %s" % q.get("q"))

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
    parser.add_argument("--no-ask", action="store_true",
                        help="do not ask the task manager when the agent is blocked; "
                             "treat a questions block as the end of the run")

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
}


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.backends:
        phase_backends(args)
        return 0
    if args.task is None:
        parser.error("a task URL or id is required")
    if args.status:
        phase_status(args)
        return 0
    if args.phase:
        PHASE_HANDLERS[args.phase](args)
        return 0
    phase_run(args)
    return 0


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
