#!/usr/bin/env python3
#
# readiness.py — NEUTRAL seam script: the sprint-readiness verdict.
#
# This is siroc's gate POLICY (the neutral workflow profile), encoded once and
# enforced in code rather than re-derived by an agent reasoning over task JSON.
# It is a SEAM-level script (like resolve_provider.py): it lives in the neutral
# task-manager interface, NOT in any provider's tm.py. Providers are task-manager
# mechanics; they do not own siroc's gate.
#
# Separation of concerns:
#   - POLICY (this file): the 4 checks + how their results combine into `ready`
#     (per start-task/references/validation-rules.md + references/workflow/lifecycle.md).
#   - DATA (provider tm.py): readiness.py composes the resolved provider's
#     primitives — `tm.py task get <ref>` (status, fields incl. Estimate, board
#     membership) and `tm.py board resolve <key> active-sprint` (the active sprint).
#     It does NOT re-implement fetching.
#
# Usage:
#   readiness.py check [--url <task-url-or-ref>] <task-ref>
#
# The verdict is emitted as JSON on stdout. Exit 0 when the verdict was produced
# (whether or not the task is `ready`); non-zero only on a HARD error (could not
# resolve the provider, could not fetch the data, bad args). Sprint-readiness
# failures are NOT errors — they are conveyed in the verdict.
#
# The verdict-shaping logic (evaluate_readiness) is a PURE function: no network,
# no provider calls — unit-testable on mock inputs offline. Live fetch
# (resolve_provider + tm.py) is composed only by main(); it is user-validated,
# not exercised in offline verification.
#
# Dependencies: Python 3 stdlib + the resolved provider's tm.py (invoked, not
# imported) + resolve_provider/cache_util (siblings). Network only via tm.py.

import glob
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import cache_util  # noqa: E402

PROG = "readiness.py"

# Not-yet-started lifecycle states (../../../references/workflow/lifecycle.md): a task
# in one of these is a candidate to start. The gate only asks "is this startable?" —
# the original `Product Status == "Assigned"` check, generalized to the neutral
# not-yet-started set. ANY other status (active, near-complete like "Ready", or closed)
# is simply NOT startable; the gate does not sub-classify it. Matching is by neutral
# status NAME (Asana) or Jira's statusCategory key (instance-stable). Case-insensitive.
NOT_STARTED_NAMES = {
    "requirements", "sizing", "refinement",
    "unassigned", "scheduled", "assigned",
}
# The Jira statusCategory key that means not-yet-started.
JIRA_NOT_STARTED_CATEGORY = "new"


def err(msg):
    sys.stderr.write(msg + "\n")


def die(code, msg=None):
    if msg is not None:
        err(msg)
    sys.exit(code)


# --- pure policy (no network, no provider calls) ----------------------------

# Normalize the active sprint's identifying name from either provider's shape.
# Asana active_sprint: {"gid","name","due_on"}; Jira: {"id","name","state","endDate"}.
# Returns the name string, or None when there is no active sprint.
def _active_sprint_name(active_sprint):
    if not isinstance(active_sprint, dict):
        return None
    name = active_sprint.get("name")
    if isinstance(name, str) and name:
        return name
    return None


# Collect the sprint/board names a task belongs to, tolerant of both projections:
#   Asana board: [{"project","section"}, ...]  -> project names
#   Jira board:  {"project","sprint"}          -> the sprint name
# Returns a list of non-empty membership names (lowercased for comparison upstream).
def _task_membership_names(task):
    out = []
    board = task.get("board") if isinstance(task, dict) else None
    if isinstance(board, list):
        # Asana shape: each membership is a {project, section}.
        for m in board:
            if isinstance(m, dict):
                p = m.get("project")
                if isinstance(p, str) and p:
                    out.append(p)
    elif isinstance(board, dict):
        # Jira shape: a single {project, sprint}; membership is by sprint.
        s = board.get("sprint")
        if isinstance(s, str) and s:
            out.append(s)
    return out


# Is the task in a not-yet-started (startable) state? Tolerant of both projection shapes:
#   Asana status: a string ("Assigned", "Ready", ...) matched against NOT_STARTED_NAMES
#   Jira status:  {"name","category"} -> not-yet-started iff statusCategory == "new"
# Returns (is_not_started: bool, detail: str|None). Anything not not-yet-started is just
# "not startable" — the gate does not distinguish started / near-complete / closed.
def _is_not_started(status):
    # Jira shape: prefer the category (instance-stable), fall back to the name.
    if isinstance(status, dict):
        category = status.get("category")
        name = status.get("name")
        if isinstance(category, str) and category:
            return category.strip().lower() == JIRA_NOT_STARTED_CATEGORY, (name or category)
        status_name = name
    else:
        status_name = status

    if not isinstance(status_name, str) or not status_name:
        return False, status_name

    return status_name.strip().lower() in NOT_STARTED_NAMES, status_name


# Detect a native/issue key or project-ID field on the task.
# - When the provider has a native key (e.g. Jira), this check is SKIPPED entirely
#   (the key always exists); the caller passes provider_has_native_key=True.
# - Otherwise (e.g. Asana) look for an ID-pattern value (XXX-123) among the task's
#   canonical fields — the field NAME varies per project (per validation-rules
#   Check 4), so match by value pattern, not field name.
import re as _re
_ID_PATTERN = _re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def _has_id_field(task):
    # Preferred: the provider surfaces the human key as a top-level read-only
    # task_id (Asana from a custom_id/text field, Jira from the issue key). The
    # ID field is NOT a canonical field, so it never appears under `fields`.
    tid = task.get("task_id") if isinstance(task, dict) else None
    if isinstance(tid, str) and tid.strip():
        return True
    fields = task.get("fields") if isinstance(task, dict) else None
    if isinstance(fields, dict):
        for v in fields.values():
            if isinstance(v, str) and _ID_PATTERN.match(v.strip()):
                return True
    # Some providers surface the key on the projection's ref itself.
    ref = task.get("ref") if isinstance(task, dict) else None
    if isinstance(ref, str) and _ID_PATTERN.match(ref.strip()):
        return True
    return False


# PURE verdict function. Given a task projection, the active sprint, and whether the
# provider supplies a native key, apply siroc's neutral gate policy and return the
# verdict dict. No I/O — unit-testable on mocks.
#
# Verdict shape:
#   {"ready": bool, "checks": [ {name,result,blocking,...}, ... ]}
#
# `ready` = active_sprint pass AND estimate pass AND status is not-yet-started.
# The status check is binary (startable or not); the key check is non-blocking.
def evaluate_readiness(task, active_sprint, provider_has_native_key):
    if not isinstance(task, dict):
        task = {}

    # Check 1: active sprint membership (blocking, non-negotiable).
    sprint_name = _active_sprint_name(active_sprint)
    memberships = _task_membership_names(task)
    if sprint_name is None:
        active_pass = False
        active_detail = "no active sprint resolved"
    else:
        lowered = {m.strip().lower() for m in memberships}
        active_pass = sprint_name.strip().lower() in lowered
        if active_pass:
            active_detail = sprint_name
        else:
            active_detail = "not in active sprint '%s' (memberships: %s)" % (
                sprint_name, memberships or "none")
    active_check = {
        "name": "active_sprint",
        "result": "pass" if active_pass else "fail",
        "blocking": True,
        "detail": active_detail,
    }

    # Check 2: estimate present (blocking).
    fields = task.get("fields") if isinstance(task.get("fields"), dict) else {}
    estimate = fields.get("Estimate")
    estimate_pass = estimate is not None and str(estimate).strip() != ""
    estimate_check = {
        "name": "estimate",
        "result": "pass" if estimate_pass else "fail",
        "blocking": True,
        "detail": estimate if estimate_pass else "not set",
    }

    # Check 3: status (blocking). Binary, like the original gate: a not-yet-started
    # status passes; anything else (active / near-complete / closed) is not startable.
    not_started, status_detail = _is_not_started(task.get("status"))
    status_check = {
        "name": "status",
        "result": "pass" if not_started else "fail",
        "blocking": True,
        "detail": (status_detail if status_detail else "no status")
        + ("" if not_started else " — not a not-yet-started state"),
    }

    # Check 4: task key / ID field (non-blocking; provider-conditional).
    if provider_has_native_key:
        key_check = {
            "name": "task_key",
            "result": "skip",
            "blocking": False,
            "detail": "provider supplies a native task key",
        }
    else:
        key_present = _has_id_field(task)
        key_check = {
            "name": "task_key",
            "result": "pass" if key_present else "fail",
            "blocking": False,
            "detail": "present" if key_present else "no ID-pattern (XXX-123) field set",
        }

    ready = active_pass and estimate_pass and not_started

    return {
        "ready": ready,
        "checks": [active_check, estimate_check, status_check, key_check],
    }


# --- live composition (network via the resolved provider's tm.py) -----------

# Locate the resolved provider's tm.py: sibling ../task-manager-<provider>/scripts/tm.py
# relative to this seam script. Returns the path, or None if not found.
def provider_tm_path(provider):
    skills_dir = os.path.dirname(os.path.dirname(_HERE))  # .../skills
    candidate = os.path.join(
        skills_dir, "task-manager-" + provider, "scripts", "tm.py")
    if os.path.isfile(candidate):
        return candidate
    # Defensive: glob in case of unexpected layout.
    pattern = os.path.join(
        skills_dir, "task-manager-" + provider, "scripts", "tm.py")
    hits = glob.glob(pattern)
    return hits[0] if hits else None


# Resolve the active provider by invoking resolve_provider.py (reuse the seam's
# detection logic verbatim rather than duplicating it). Returns the provider name.
# Exits non-zero (hard error) on conflict / ask-needed / error — readiness needs a
# resolved provider to fetch data.
def resolve_provider(url):
    resolver = os.path.join(_HERE, "resolve_provider.py")
    cmd = [sys.executable, resolver]
    if url:
        cmd += ["--url", url]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode == 0 and out:
        return out
    msg = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode == 4:
        die(4, "%s: provider not resolved — %s" % (PROG, msg))
    if proc.returncode == 3:
        die(3, "%s: provider conflict — %s" % (PROG, msg))
    die(1, "%s: could not resolve provider — %s" % (PROG, msg))


# Run `<tm.py> <args...>` and return parsed JSON stdout. Exits 1 on transport/parse
# failure (a hard error — readiness cannot produce a verdict without the data).
def tm_json(tm_path, args):
    cmd = [sys.executable, tm_path] + args
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()
        die(1, "%s: `tm.py %s` failed (exit %d): %s" % (
            PROG, " ".join(args), proc.returncode, msg))
    try:
        return json.loads(out) if out else None
    except ValueError:
        die(1, "%s: `tm.py %s` did not return JSON: %s" % (PROG, " ".join(args), out))


# Probe whether the provider supplies a native task key. The recognition lives in
# each provider's `ref parse`; rather than re-encode "jira has keys, asana doesn't"
# here, ask the provider to recognize a representative native-key form. A provider
# WITH native keys (Jira: TP-687) recognizes the ID-pattern as its own; a provider
# WITHOUT (Asana: numeric gids) does not. Pure parse (`ref parse` is offline).
def provider_has_native_key(tm_path):
    proc = subprocess.run(
        [sys.executable, tm_path, "ref", "parse", "TP-1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return proc.returncode == 0


def cmd_check(argv):
    url = None
    ref = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--url":
            if i + 1 >= len(argv):
                die(1, "%s: --url requires a value" % PROG)
            url = argv[i + 1]
            i += 2
        elif a.startswith("-"):
            die(1, "%s: unknown option '%s'" % (PROG, a))
        else:
            if ref is None:
                ref = a
            else:
                die(1, "%s: unexpected extra argument '%s'" % (PROG, a))
            i += 1
    if ref is None:
        # Allow the URL to double as the ref when only --url is given.
        ref = url
    if ref is None:
        die(1, "usage: %s check [--url <task-url-or-ref>] <task-ref>" % PROG)

    provider = resolve_provider(url or ref)
    tm_path = provider_tm_path(provider)
    if not tm_path:
        die(1, "%s: resolved provider '%s' but found no tm.py" % (PROG, provider))

    # DATA from provider primitives (this script never re-implements fetching).
    task = tm_json(tm_path, ["task", "get", ref])
    key = cache_util.project_key()
    active_sprint = tm_json(tm_path, ["board", "resolve", key, "active-sprint"])
    has_native_key = provider_has_native_key(tm_path)

    # POLICY via the pure function.
    verdict = evaluate_readiness(task, active_sprint, has_native_key)
    sys.stdout.write(json.dumps(verdict, indent=2) + "\n")
    sys.exit(0)


def main(argv):
    if not argv:
        die(1, "usage: %s check [--url <task-url-or-ref>] <task-ref>" % PROG)
    sub = argv[0]
    if sub == "check":
        cmd_check(argv[1:])
    else:
        die(1, "%s: unknown subcommand '%s' (expected 'check')" % (PROG, sub))


if __name__ == "__main__":
    main(sys.argv[1:])
