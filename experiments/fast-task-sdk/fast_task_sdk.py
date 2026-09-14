#!/usr/bin/env python3
#
# fast_task_sdk.py — fast-task with the model call behind a provider-agnostic seam.
#
# Same premise as the sibling `fast-task` experiment: control flow is Python, and a
# model is invoked only to implement the task and to repair a failing QA gate. The
# difference is the seam — every model call goes through `agent/`, which exposes
# AgentRequest / AgentResult / AgentBackend and nothing else. No vendor name and no
# SDK import appears outside `agent/<backend>.py`.
#
# That buys two things the subprocess version cannot have: real telemetry (cost,
# tokens and turns per call, totalled per run) and a swappable provider.
#
# See DESIGN.md for the rationale and the phase contract.
#
#   fast_task_sdk.py run       <task-url>   # all four phases
#   fast_task_sdk.py prologue  <task-url>   # zero model calls
#   fast_task_sdk.py implement <task-id>
#   fast_task_sdk.py qa        <task-id>
#   fast_task_sdk.py ship      <task-id>
#   fast_task_sdk.py status    <task-id>
#   fast_task_sdk.py backends              # which providers are usable here
#
# Dependencies: Python 3 stdlib, git, gh, asana.py (sibling), and whatever the
# selected backend needs (claude-agent-sdk for the default).

import argparse
import json
import os
import re
import subprocess
import sys
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
STATE_DIRNAME = ".fast-task"
QA_CONFIG = ".fast-task.json"

# Lifecycle states meaning "not yet started" — a task in one of these is a candidate
# to start. Mirrors readiness.py's NOT_STARTED_NAMES (the neutral workflow profile).
NOT_STARTED = {
    "requirements", "sizing", "refinement",
    "unassigned", "scheduled", "assigned",
}

PHASES = ("prologue", "implement", "qa", "ship")

# Ceilings applied to every model call. Turn limits keep a wedged run from
# grinding; the budget is a hard stop the SDK backend enforces server-side.
DEFAULT_MAX_TURNS = 60
DEFAULT_BUDGET_USD = None

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
    sys.stderr.write("\nfast-task: %s\n" % msg)
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


def evaluate_gate(task, dependencies, current_user_gid, strict=False):
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
        blocking.append("blocked by %d incomplete dependency/ies: %s"
                        % (len(incomplete), names))

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
    gate = evaluate_gate(task, deps, (me or {}).get("gid"), strict=args.strict)
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
    info("next: fast_task.py implement %s" % tid)
    return tid


# --- implement --------------------------------------------------------------

def call_agent(prompt, cwd, args, label, state=None, autonomy=None):
    """One model call, through the seam. Returns an AgentResult.

    Every call is recorded in the run's cost ledger, so `status` can report what a
    task actually cost across resumed phases and separate invocations.
    """
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
        max_budget_usd=args.budget,
        load_project_context=not args.no_project_context,
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
    if state is not None:
        record_cost(state, label, result)
    if not result.ok:
        die("%s failed: %s" % (label, result.error or "unknown error"))
    return result


def record_cost(state, label, result):
    """Append one call to the run's ledger."""
    ledger = state.read("cost.json", {"calls": []})
    ledger["calls"].append({
        "label": label, "backend": result.backend, "model": result.model,
        "cost_usd": result.cost_usd, "turns": result.turns,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "cached_tokens": result.cached_tokens, "duration_s": result.duration_s,
        "ok": result.ok,
    })
    state.write("cost.json", ledger)


def cost_total(state):
    """(calls, total_usd_or_None, total_seconds). The total is None when any call
    could not report a cost — a partial sum would read as the whole bill."""
    calls = state.read("cost.json", {}).get("calls", [])
    costs = [c.get("cost_usd") for c in calls]
    total = sum(c for c in costs if c is not None) if calls else 0.0
    if any(c is None for c in costs):
        total = None
    seconds = sum(c.get("duration_s") or 0.0 for c in calls)
    return len(calls), total, seconds


def report_cost(state):
    calls, total, seconds = cost_total(state)
    if not calls:
        return
    info("%d model call(s) · %s · %.1fs total"
         % (calls, "$%.4f" % total if total is not None else "cost not reported",
            seconds))


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

    prompt = render_prompt(
        "implement.md",
        context=json.dumps(context["task"], indent=2),
        subtasks=json.dumps(context["subtasks"], indent=2),
        comments=json.dumps(context["comments"], indent=2),
        attachments=attachment_note,
        links="\n".join("- %s" % u for u in context["external_links"]) or "(none)",
        branch=context["git"]["branch"],
    )
    outcome = call_agent(prompt, worktree, args, "implement", state)
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
        call_agent(prompt, worktree, args,
                   "qa-repair-%d" % attempt, state)
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

def phase_run(args):
    tid = phase_prologue(args)
    args.task = tid
    state = State(main_repo_root(os.path.abspath(args.repo)), tid)
    state = phase_implement(args, state)
    state = phase_qa(args, state)
    phase_ship(args, state)
    step("Done")
    info("task %s shipped" % tid)
    report_cost(state)


def phase_status(args):
    state = State.find(main_repo_root(os.path.abspath(args.repo)), args.task)
    done = state.phases_done()
    context = state.read("context.json", {})
    step("fast-task %s" % args.task)
    for phase in PHASES:
        info("[%s] %s" % ("x" if phase in done else " ", phase))
    calls, total, seconds = cost_total(state)
    if calls:
        info("")
        info("%d model call(s) · %s · %.1fs"
             % (calls, "$%.4f" % total if total is not None
                else "cost not reported", seconds))
        for call in state.read("cost.json", {}).get("calls", []):
            info("  %-16s %-12s %s"
                 % (call.get("label"), call.get("backend"),
                    "$%.4f" % call["cost_usd"] if call.get("cost_usd") is not None
                    else "cost n/a"))
    if context:
        info("")
        info("branch:   %s" % context.get("git", {}).get("branch"))
        info("worktree: %s" % context.get("git", {}).get("worktree"))
        info("PR:       %s" % context.get("git", {}).get("pr_url"))


# --- cli --------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="fast_task_sdk.py",
        description="Run the start-task lifecycle as an explicit program, "
                    "with every model call behind a provider-agnostic seam.")
    parser.add_argument("--repo", default=os.getcwd(),
                        help="target repository (default: cwd)")
    parser.add_argument("--backend", default=DEFAULT_BACKEND,
                        choices=backend_names(),
                        help="agent provider (default: %(default)s)")
    parser.add_argument("--model", default=None,
                        help="model override; backend default when unset")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        help="turn ceiling per call (default: %(default)s)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD,
                        help="hard USD ceiling per call, where the backend supports it")
    parser.add_argument("--no-project-context", action="store_true",
                        help="do not load the repo's CLAUDE.md / AGENTS.md")
    parser.add_argument("--autonomy", default="full",
                        choices=("read-only", "edit", "full"),
                        help="what the agent may do (default: %(default)s)")
    sub = parser.add_subparsers(dest="phase", required=True)

    for name, help_text in (
        ("run", "prologue + implement + qa + ship"),
        ("prologue", "fetch, gate, branch, draft PR (no LLM)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("task", help="task URL or ref")
        p.add_argument("--base", default=None, help="base branch (default: origin/main)")
        p.add_argument("--no-worktree", action="store_true",
                       help="branch in the current directory instead of a worktree")
        p.add_argument("--strict", action="store_true",
                       help="make Estimate and sprint membership blocking")

    for name, help_text in (
        ("implement", "the implementation LLM call"),
        ("qa", "run the lint/build/test gate"),
        ("ship", "promote the PR and update Asana"),
        ("status", "show phase progress"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("task", help="task id (e.g. MT251-47)")

    sub.add_parser("backends", help="list providers and whether they are usable")
    return parser


def phase_backends(args):
    step("Backends")
    for name, usable, reason in available_backends():
        marker = "x" if usable else " "
        default = "  (default)" if name == DEFAULT_BACKEND else ""
        info("[%s] %-12s%s%s" % (marker, name, default,
                                 "" if usable else "  — %s" % reason))


HANDLERS = {
    "backends": phase_backends,
    "run": phase_run,
    "prologue": phase_prologue,
    "implement": phase_implement,
    "qa": phase_qa,
    "ship": phase_ship,
    "status": phase_status,
}


def main(argv):
    args = build_parser().parse_args(argv)
    HANDLERS[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
