#!/usr/bin/env python3
#
# tm.py — per-provider task-manager CLI for the Jira provider.
#
# One CLI per provider, dispatched by family + verb: `tm.py <family> <verb> [args]`.
# Families namespace operation groups so future ops (fields, tasks, attachments) can
# be added without colliding. The first family is `board`.
#
# Board family — code-enforced board-cache resolution. The cache lifecycle documented
# in ../references/boards.md is implemented here so the provider MUST go through it:
# cache-first reads, active-sprint auto-refresh only when stale, and live discovery
# (via `acli`) only on a genuine miss (which then writes back). This removes the
# failure mode where an agent bypasses a valid cache and does live `acli board
# search`/`list-sprints` discovery, landing on a stale sprint.
#
# This mirrors the Asana provider's board contract (same CLI + exit codes), but the
# transport is the `acli` Atlassian CLI rather than urllib — `acli` is how the Jira
# provider talks to Jira (see ../references/acli.md / ../SKILL.md), and it handles
# OAuth out of band.
#
# Usage:
#   tm.py board key
#   tm.py board read     <key>
#   tm.py board resolve  <key> <active-sprint|backlog>
#   tm.py board discover <key>
#   tm.py board refresh  <key>
#   tm.py board write    <key> <json>
#
# Fields family — code-enforced field DISCOVERY + neutral-name->Jira-id mapping. The
# rules in ../references/fields.md (neutral field -> Jira field, native vs custom,
# customfield ids discovered at runtime) and ../references/acli.md (the
# `workitem view --fields "*all" --json` discovery call) are implemented here so the
# agent no longer ingests the full `fields` map and maps by hand on every call. The
# discovered map is cached in the SAME per-repo cache file under a "fields" section
# keyed by project key. Fields change rarely, so there is no date-staleness — list/
# resolve discover-on-miss and write back; force a refresh with `fields discover`.
# This batch is the READ/mapping side only; setting a field value is a later batch.
#
#   tm.py fields list     <project-ref>
#   tm.py fields resolve  <project-ref> <CanonicalName>
#   tm.py fields discover <project-ref>
#
# <project-ref> for Jira is a project key (e.g. TP) or a representative issue key
# (e.g. TP-687). Discovery views a representative issue; a bare project key with no
# cached representative issue cannot self-discover — pass an issue key the first time
# (or run `fields discover <ISSUE-KEY>`), per ../references/fields.md.
#
# Task family — task WRITES (create / set-field / attach) with HONEST partial
# support. Primary transport is `acli`. `acli` reaches: create (workitem create),
# and edit of assignee / labels / type on an existing issue. It CANNOT reach
# priority / story points (Sizing) / time tracking (Estimate) / sprint / parent /
# customfields on an existing issue, and CANNOT upload attachments — those need the
# Atlassian MCP `editJiraIssue` tool, which is AGENT-invoked, not shell-callable.
# For those, the script exits non-zero with a clear "needs Atlassian MCP
# editJiraIssue fallback (agent-handled)" signal — never a silent no-op. The
# invoking skill owns performing the MCP fallback when it sees that signal.
#
#   tm.py task get           <task-ref>
#   tm.py task create        <project-ref> --title T [--description D] [--assignee A] [--type T]
#   tm.py task set-field     <task-ref> <CanonicalName> <value>
#   tm.py task attach        <task-ref> <file-path>
#   tm.py task set-status    <task-ref> <status-name>
#   tm.py task add-dependency <task-ref> <depends-on-ref>
#   tm.py task set-parent    <task-ref> <parent-ref>
#   tm.py task add-to-board  <task-ref> <board-ref>
#
# set-status resolves the neutral lifecycle name to a target status by
# statusCategory (../references/statuses.md): it determines the target category,
# lists the issue's available transitions (`acli jira workitem transition --list`),
# picks the transition whose to.statusCategory.key matches (preferring a name match
# within the category), then `acli jira workitem transition --status "<name>"`. No
# transition reaches the target category -> exit 1. add-dependency creates a Jira
# issue link ("Blocks" default) via `acli jira workitem link` IF that command is
# available, else exits 1 with the MCP/REST issueLink partial-support signal.
# set-parent (existing issue) and add-to-board (sprint) are NOT acli capabilities
# and exit 1 with the MCP/operator partial-support signal (consistent with
# fields.md / boards.md).
#
# `task get` runs `acli jira workitem view <KEY> --fields "*all" --json` and prints
# a COMPACT neutral projection (NOT the raw `*all` blob) — {ref,name,description,
# assignee,status,board,fields} — to save tokens. Native fields map by their stable
# Jira ids; customfield-backed canonical fields (Sizing/Platform) map via best-effort
# `acli jira field list` metadata. For unusual long-tail needs, the raw `*all` recipe
# in ../references/acli.md is still available.
#
# <project-ref> for create is a Jira project key; <task-ref> is an issue key.
#
# Ref family — find_task(ref) for the Jira provider AND the recognition probe used by
# the neutral seam's provider detection. `ref parse <url-or-ref>` extracts the issue
# key via regex `[A-Z][A-Z0-9_]+-\d+` (first match) from a *.atlassian.net URL or a
# bare key (per ../references/acli.md URL & Key Extraction), prints ONLY the canonical
# key to stdout, and exits 0. Input that is not recognizable as a Jira issue reference
# (e.g. an app.asana.com URL, a bare numeric id, garbage) exits 2 ("not mine") — no
# output. This lets resolve_provider probe each installed provider with the same input.
#
#   tm.py ref parse <url-or-ref>
#
# Comment family — post and read issue comments via acli. `comment add` authors the
# body as Markdown (acli wraps it to ADF) via `acli jira workitem comment create`.
# `comment list` runs `acli jira workitem comment list --json` — which returns an
# OBJECT {comments,total,…}; we read `.comments` and return the compact
# [{author, text, created_at}] shape.
#
#   tm.py comment add  <task-ref> (<body> | --body-file <path>)
#   tm.py comment list <task-ref>
#
# <key> comes from `tm.py board key` (git remote -> sanitized; fallback to repo
# basename). It is the SAME repo->key derivation Asana uses — the cache key is the
# git-repo identity, shared across providers in one ~/.cortex namespace. Callers
# derive it once and pass it to every other command.
#
# Auth: Jira auth is OAuth managed by `acli` — there is NO token env var and no
# secret in this provider. Before any API command (discover/refresh) we verify
# `acli jira auth status` reports authenticated; if not, we exit 1 with the
# instruction to run `acli jira auth login` (cannot be automated).
#
# Exit codes (identical contract to the Asana provider's board family):
#   0  success / cache present & fresh
#   1  argument error, auth failure, or `acli`/parse failure
#   2  cache missing, or cache present but not a Jira cache (foreign/unmarked) — miss
#   3  cache present but stale (active_sprint endDate past, or state != "active")
#   4  bootstrap needed (miss with no project_key/board_id cached — agent must
#      resolve the Jira project key + scrum board, write them, then discover)
#
# Dependencies: Python 3 stdlib + git + `acli`. No interactive prompts. No secrets.

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "task-manager", "scripts"))
import cache_util

PROG = "tm.py"
PROVIDER = "jira"


def err(msg):
    sys.stderr.write(msg + "\n")


def die(code, msg=None):
    if msg is not None:
        err(msg)
    sys.exit(code)


# --- acli transport ---------------------------------------------------------

# Verify acli reports an authenticated Jira session. There is no token to resolve
# (OAuth is managed by acli out of band) — we only gate on auth status. On any
# failure exit 1 with the (non-automatable) remediation. We never echo acli's
# stdout, which can contain account/site info beyond what we need.
def ensure_authenticated():
    try:
        proc = subprocess.run(
            ["acli", "jira", "auth", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        die(1, "%s: `acli` not found on PATH — install the Atlassian CLI and run `acli jira auth login`" % PROG)
    except Exception as e:
        die(1, "%s: failed to run `acli jira auth status` (%s)" % (PROG, e))
    out = proc.stdout.decode("utf-8", "replace")
    # acli reports a checkmark + "Authenticated" when a session is active.
    if proc.returncode != 0 or "Authenticated" not in out:
        die(1, "%s: Jira is not authenticated — run `acli jira auth login` (interactive; cannot be automated), then retry" % PROG)


# Run an acli command expected to emit JSON. On non-zero exit or unparseable
# output, exit 1 (never treat a failure as "no sprint" / "no board"). Returns the
# parsed JSON object.
def acli_json(args):
    try:
        proc = subprocess.run(
            ["acli"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        die(1, "%s: `acli` not found on PATH" % PROG)
    except Exception as e:
        die(1, "%s: failed to run `acli %s` (%s)" % (PROG, " ".join(args), e))
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        die(1, "%s: `acli %s` failed (exit %s)%s" % (
            PROG, " ".join(args), proc.returncode,
            (": " + detail) if detail else "",
        ))
    body = proc.stdout.decode("utf-8", "replace")
    try:
        return json.loads(body)
    except Exception:
        die(1, "%s: `acli %s` returned invalid JSON" % (PROG, " ".join(args)))


# Run an acli command for its side effect (create/edit/etc.), not for JSON output.
# On non-zero exit, exit 1 with the acli stderr. Returns the decoded stdout (may be
# empty or human-readable text). Used by the task family's write paths.
def acli_run(args):
    try:
        proc = subprocess.run(
            ["acli"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        die(1, "%s: `acli` not found on PATH" % PROG)
    except Exception as e:
        die(1, "%s: failed to run `acli %s` (%s)" % (PROG, " ".join(args), e))
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        die(1, "%s: `acli %s` failed (exit %s)%s" % (
            PROG, " ".join(args), proc.returncode,
            (": " + detail) if detail else "",
        ))
    return proc.stdout.decode("utf-8", "replace")


# --- cache field accessors --------------------------------------------------

def project_key_from(key):
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        return ""
    v = cache.get("project_key")
    if isinstance(v, str) and v:
        return v
    return ""


def board_id_from(key):
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        return ""
    v = cache.get("board_id")
    # board id may be cached as a string or a number — normalize to string.
    if isinstance(v, str) and v:
        return v
    if isinstance(v, int):
        return str(v)
    return ""


# Staleness for a cached Jira active sprint. Jira sprints carry `state`
# (active/closed/future) and `endDate` (an ISO datetime). The sprint is stale when
# its endDate's date-part is past (reusing the neutral date-staleness helper on
# endDate[:10]) OR its state is no longer "active". A null/absent active_sprint is
# NOT "stale" here — that is the re-discover case handled by resolve.
def sprint_is_stale(active_sprint):
    if not isinstance(active_sprint, dict):
        return False
    state = active_sprint.get("state")
    if isinstance(state, str) and state != "active":
        return True
    end_date = active_sprint.get("endDate")
    date_part = ""
    if isinstance(end_date, str) and len(end_date) >= 10:
        date_part = end_date[:10]
    return cache_util.is_date_stale(date_part)


# --- discovery helpers ------------------------------------------------------

# Extract the single active sprint from `board list-sprints --state active`, which
# is wrapped in {"sprints": [...]}. Per the neutral active-sprint policy, when more
# than one qualifies the latest-ending one wins (compare endDate). Returns a
# compact {id,name,state,endDate} or None when there is no active sprint.
def select_active_sprint(payload):
    sprints = []
    if isinstance(payload, dict):
        v = payload.get("sprints")
        if isinstance(v, list):
            sprints = v
    candidates = [s for s in sprints if isinstance(s, dict)]
    if not candidates:
        return None

    def end_key(s):
        e = s.get("endDate")
        return e if isinstance(e, str) else ""

    candidates.sort(key=end_key)
    winner = candidates[-1]
    return {
        "id": winner.get("id"),
        "name": winner.get("name"),
        "state": winner.get("state"),
        "endDate": winner.get("endDate"),
    }


# Resolve the scrum board id for a project. `board search` is wrapped in
# {"values": [...]}; take the first match (per ../references/boards.md). Returns
# the id as a string, or "" when no board is found.
def select_board_id(payload):
    values = []
    if isinstance(payload, dict):
        v = payload.get("values")
        if isinstance(v, list):
            values = v
    for b in values:
        if isinstance(b, dict) and b.get("id") is not None:
            return str(b.get("id"))
    return ""


# --- board family commands --------------------------------------------------

# Print the project key per the shared repo->key derivation (same as Asana).
def board_key(args):
    sys.stdout.write(cache_util.project_key() + "\n")


# Read cache. Exit 0 fresh, 2 miss, 3 stale. Prints cache JSON to stdout when
# present and ours.
#
# Provider-marker asymmetry vs Asana: Asana treats an UNMARKED cache as its own
# (legacy caches are Asana and self-heal). Jira does the opposite — an unmarked
# cache is Asana's, not Jira's, so for the Jira provider both a foreign marker AND
# a missing marker are a miss (exit 2). provider_matches(obj, "jira") returns True
# for a missing marker (its legacy-self-heal rule is generic), so we must check the
# marker explicitly here: only an EXPLICIT "jira" marker counts as a Jira cache.
def board_read(args):
    if not args:
        die(1, "usage: %s board read <key>" % PROG)
    key = args[0]
    if not os.path.isfile(cache_util.cache_path(key)):
        sys.exit(2)
    cache = cache_util.read_cache(key)
    if cache_util.cache_provider(cache) != PROVIDER:
        # Foreign marker OR no marker -> not a Jira cache. Unlike Asana, Jira does
        # not adopt unmarked caches (those are Asana's legacy caches).
        sys.exit(2)
    sys.stdout.write(json.dumps(cache, indent=2) + "\n")
    active = cache.get("active_sprint") if isinstance(cache, dict) else None
    if sprint_is_stale(active):
        sys.exit(3)
    sys.exit(0)


# Validate and write a cache JSON blob, stamping provider:"jira". Used by
# bootstrap to store project_key/board_id before discover.
def board_write(args):
    if len(args) < 2:
        die(1, "usage: %s board write <key> <json>" % PROG)
    key = args[0]
    raw = args[1]
    try:
        obj = json.loads(raw)
    except Exception:
        die(1, "%s: board write: <json> is not valid JSON" % PROG)
    if isinstance(obj, dict):
        obj["provider"] = PROVIDER
    cache_util.write_cache(key, obj)
    sys.stdout.write(json.dumps(cache_util.read_cache(key), indent=2) + "\n")


# Run full discovery against Jira via acli and write the cache. Requires a cached
# Jira config (project_key). The board id is resolved if not already cached.
def board_discover(args):
    if not args:
        die(1, "usage: %s board discover <key>" % PROG)
    key = args[0]
    proj = project_key_from(key)
    if not proj:
        die(4, "%s: board discover requires a cached Jira project_key — run bootstrap first (board write <key> <json>)" % PROG)
    ensure_authenticated()

    board_id = board_id_from(key)
    if not board_id:
        search = acli_json(["jira", "board", "search", "--project", proj, "--type", "scrum", "--json"])
        board_id = select_board_id(search)
        if not board_id:
            die(1, "%s: no scrum board found for project '%s' via `acli jira board search`" % (PROG, proj))

    sprints = acli_json(["jira", "board", "list-sprints", "--id", board_id, "--state", "active", "--json"])
    active_sprint = select_active_sprint(sprints)

    new_json = {
        "provider": PROVIDER,
        "project_key": proj,
        "board_id": board_id,
        "active_sprint": active_sprint,
        "cached_at": cache_util.now_iso(),
    }
    cache_util.write_cache(key, new_json)
    sys.stdout.write(json.dumps(cache_util.read_cache(key), indent=2) + "\n")


# Re-run the active-sprint lookup against Jira and write it back, preserving the
# rest of the cache (project_key, board_id). Used by `board refresh` and the stale
# path of `board resolve`.
def board_refresh(args):
    if not args:
        die(1, "usage: %s board refresh <key>" % PROG)
    key = args[0]
    if not os.path.isfile(cache_util.cache_path(key)):
        die(2, "%s: board refresh: no cache for key '%s'" % (PROG, key))
    proj = project_key_from(key)
    board_id = board_id_from(key)
    if not proj or not board_id:
        die(4, "%s: board refresh requires a cached project_key and board_id" % PROG)
    ensure_authenticated()

    sprints = acli_json(["jira", "board", "list-sprints", "--id", board_id, "--state", "active", "--json"])
    active_sprint = select_active_sprint(sprints)

    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        cache = {}
    cache["provider"] = PROVIDER
    cache["active_sprint"] = active_sprint
    cache["cached_at"] = cache_util.now_iso()
    cache_util.write_cache(key, cache)
    sys.stdout.write(json.dumps(cache_util.read_cache(key), indent=2) + "\n")


# High-level provider entry point. intent in {active-sprint, backlog}.
#
# Backlog divergence from Asana: Asana has multiple named backlog boards; Jira has
# ONE board whose backlog is "issues in no sprint". So `board resolve <key> backlog`
# returns a single faithful descriptor {board_id, kind:"backlog"} — the actual
# issues are queried elsewhere via JQL (`sprint is EMPTY` / not `in openSprints()`),
# per ../references/boards.md. There is no list of backlog boards to cache.
def board_resolve(args):
    if len(args) < 2:
        die(1, "usage: %s board resolve <key> <active-sprint|backlog>" % PROG)
    key = args[0]
    intent = args[1]
    if intent not in ("active-sprint", "backlog"):
        die(1, "%s: board resolve: intent must be 'active-sprint' or 'backlog'" % PROG)

    if not os.path.isfile(cache_util.cache_path(key)):
        # Miss. The Jira project key + scrum board id are NOT derivable from the
        # git remote — they are judgment / first-use. Bootstrap.
        die(4, "%s: bootstrap needed: no cache for '%s' — resolve the Jira project key + scrum board (e.g. from the task URL the operator is working on, per references/boards.md), '%s board write <key> <json>' them, then '%s board discover <key>'" % (PROG, key, PROG, PROG))

    cache = cache_util.read_cache(key)
    # A non-Jira (foreign OR unmarked) cache cannot satisfy a Jira resolve —
    # bootstrap as if missing. (Unmarked caches are Asana's; see board_read.)
    if cache_util.cache_provider(cache) != PROVIDER:
        die(4, "%s: bootstrap needed: cache for '%s' is not a Jira cache — write Jira config (project_key + board_id) then discover" % (PROG, key))

    active = cache.get("active_sprint") if isinstance(cache, dict) else None
    stale = sprint_is_stale(active)

    if stale:
        # Sprint auto-refresh (calls acli), then return from the refreshed cache.
        _capture_stdout(board_refresh, [key])
        cache = cache_util.read_cache(key)
        active = cache.get("active_sprint") if isinstance(cache, dict) else None

    if intent == "active-sprint":
        if active is None and not stale:
            # Cache present but no active sprint recorded — re-discover before
            # concluding there is none (never return a never-populated/stale null
            # as authoritative). If no project/board config to discover with,
            # bootstrap.
            proj = project_key_from(key)
            board_id = board_id_from(key)
            if not proj or not board_id:
                die(4, "%s: bootstrap needed: cache for '%s' has no active_sprint and no project_key/board_id — write Jira config then discover" % (PROG, key))
            _capture_stdout(board_refresh, [key])
            cache = cache_util.read_cache(key)
            active = cache.get("active_sprint") if isinstance(cache, dict) else None
        sys.stdout.write(json.dumps(active) + "\n")
    elif intent == "backlog":
        board_id = board_id_from(key)
        sys.stdout.write(json.dumps({"board_id": board_id, "kind": "backlog"}) + "\n")


# Run a command function while suppressing its stdout (used for the internal
# refresh during resolve, mirroring `board_refresh "$key" >/dev/null`).
def _capture_stdout(fn, args):
    import io
    saved = sys.stdout
    sys.stdout = io.StringIO()
    try:
        fn(args)
    finally:
        sys.stdout = saved


# --- fields family ----------------------------------------------------------

# Neutral field -> Jira realization, per ../references/fields.md.
#
# NATIVE fields have stable, instance-independent Jira ids and are always recorded:
#   Type/Category -> issuetype, Priority -> priority, Labels -> labels,
#   Estimate -> timetracking, Parent/Epic -> parent, Assignee -> assignee.
# (Product Status -> `status`, moved by transitions, is included as a native field
# so callers can see it exists, though it is set via transition, not set_field.)
#
# CUSTOMFIELD-backed fields (Sizing = story points, Platform) live at a
# `customfield_NNNNN` id that is instance-specific and discovered at runtime. The
# `workitem view --fields "*all"` payload is keyed by id only (no field names), so
# resolving "Sizing"/"Platform" -> a customfield id requires field METADATA
# (id<->name), obtained from `acli jira field list --json` when that command is
# available. When metadata is unavailable, these are recorded as undetermined
# (present:false) and skipped gracefully — never guessed.
NATIVE_FIELDS = [
    ("Category", "issuetype", "issuetype"),
    ("Type", "issuetype", "issuetype"),
    ("Priority", "priority", "priority"),
    ("Labels", "labels", "labels"),
    ("Estimate", "timetracking", "timetracking"),
    ("Parent", "parent", "parent"),
    ("Assignee", "assignee", "assignee"),
    ("Product Status", "status", "status"),
]

# Fuzzy, case-insensitive name patterns for the customfield-backed neutral fields,
# matched against field metadata names from `acli jira field list`.
CUSTOMFIELD_PATTERNS = [
    ("Sizing", ["story points", "story point", "points", "sizing", "size"]),
    ("Platform", ["platform"]),
]


# Extract a normalized issue/project ref. For discovery we need a representative
# ISSUE key (contains a dash). A bare project key has no issue to view — callers
# must pass an issue key the first time. Returns the ref as-is (validation of the
# issue-vs-project distinction happens at discovery time).
def normalize_ref(ref):
    return ref.strip() if isinstance(ref, str) else ref


# Best-effort field metadata (id<->name) via `acli jira field list --json`. Returns
# a list of {id,name} dicts, or [] when the command is unavailable / unparseable.
# Unlike acli_json this never exits — missing metadata is a graceful skip, not an
# error (Sizing/Platform are then recorded undetermined).
def fetch_field_metadata():
    try:
        proc = subprocess.run(
            ["acli", "jira", "field", "list", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception:
        return []
    fields = payload
    if isinstance(payload, dict):
        for k in ("fields", "values"):
            v = payload.get(k)
            if isinstance(v, list):
                fields = v
                break
    out = []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                out.append({"id": f.get("id"), "name": f.get("name")})
    return out


# Match a customfield-backed neutral field to a Jira field id by scanning metadata
# names with the fuzzy patterns. Returns the id string, or None if no metadata name
# matches (undetermined — skip gracefully).
def match_customfield(canonical, metadata):
    patterns = None
    for name, pats in CUSTOMFIELD_PATTERNS:
        if name == canonical:
            patterns = pats
            break
    if not patterns:
        return None
    for f in metadata:
        fname = f.get("name")
        if not isinstance(fname, str):
            continue
        low = fname.lower()
        for pat in patterns:
            if pat in low:
                fid = f.get("id")
                if isinstance(fid, str) and fid:
                    return fid
    return None


# Build the neutral fields map for a Jira issue. `present_ids` is the set of Jira
# field ids that appeared (non-null) on the representative issue's `fields` map;
# native fields are recorded regardless (they are stable), but flagged present iff
# they appeared. Customfield-backed fields are resolved from metadata when
# available.
def build_fields_map(present_ids, metadata):
    out = {}
    for canonical, jira_id, kind in NATIVE_FIELDS:
        if canonical in out:
            continue
        out[canonical] = {
            "id": jira_id,
            "type": kind,
            "native": True,
            "present": jira_id in present_ids,
        }
    for canonical, _pats in CUSTOMFIELD_PATTERNS:
        cf_id = match_customfield(canonical, metadata)
        if cf_id:
            out[canonical] = {
                "id": cf_id,
                "type": "customfield",
                "native": False,
                "present": cf_id in present_ids,
            }
        else:
            out[canonical] = {
                "id": None,
                "type": "customfield",
                "native": False,
                "present": False,
            }
    return out


# View a representative issue and return the set of Jira field ids that carry a
# non-null value on it. Used to flag which fields the project actually populates.
def fetch_present_ids(issue_key):
    payload = acli_json(["jira", "workitem", "view", issue_key, "--fields", "*all", "--json"])
    present = set()
    fields = payload.get("fields") if isinstance(payload, dict) else None
    if isinstance(fields, dict):
        for k, v in fields.items():
            if v is not None:
                present.add(k)
    return present


# Fetch and build the neutral fields map for a Jira project, viewing a
# representative issue. `ref` MUST be an issue key (contains a dash); a bare project
# key has no issue to view. Network/acli call; exits 1 on transport/parse failure,
# 1 on a non-issue ref.
def discover_fields_map(ref):
    ensure_authenticated()
    if not (isinstance(ref, str) and "-" in ref):
        die(1, "%s: fields discovery needs a representative ISSUE key (e.g. TP-687), got '%s' — pass an issue key per ../references/fields.md" % (PROG, ref))
    present_ids = fetch_present_ids(ref)
    metadata = fetch_field_metadata()
    return build_fields_map(present_ids, metadata)


# The cache is keyed by the Jira PROJECT key (prefix before the dash for an issue
# key, else the ref itself), so all issues in a project share one fields entry.
def project_ref_key(ref):
    if isinstance(ref, str) and "-" in ref:
        return ref.split("-", 1)[0]
    return ref


# Read the cached fields map for a project ref, or None if absent.
def cached_fields_map(key, project_ref):
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        return None
    if cache_util.cache_provider(cache) != PROVIDER:
        return None
    fields = cache.get("fields")
    if not isinstance(fields, dict):
        return None
    fm = fields.get(project_ref)
    if isinstance(fm, dict):
        return fm
    return None


# Write the fields map for a project ref into the cache, preserving the rest and
# stamping the provider marker.
def write_fields_map(key, project_ref, fields_map):
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        cache = {}
    cache["provider"] = PROVIDER
    fields = cache.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    fields[project_ref] = fields_map
    cache["fields"] = fields
    cache_util.write_cache(key, cache)


# Force a fresh discovery from Jira and write it to cache; print the map.
def fields_discover(args):
    if not args:
        die(1, "usage: %s fields discover <project-ref>" % PROG)
    key = cache_util.project_key()
    ref = normalize_ref(args[0])
    project_ref = project_ref_key(ref)
    fields_map = discover_fields_map(ref)
    write_fields_map(key, project_ref, fields_map)
    sys.stdout.write(json.dumps(fields_map, indent=2) + "\n")


# Return the neutral fields map for a project. Cache-first; on a miss, discover from
# Jira and write back. Exit 0.
def fields_list(args):
    if not args:
        die(1, "usage: %s fields list <project-ref>" % PROG)
    key = cache_util.project_key()
    ref = normalize_ref(args[0])
    project_ref = project_ref_key(ref)
    fields_map = cached_fields_map(key, project_ref)
    if fields_map is None:
        fields_map = discover_fields_map(ref)
        write_fields_map(key, project_ref, fields_map)
    sys.stdout.write(json.dumps(fields_map, indent=2) + "\n")
    sys.exit(0)


# Return a single neutral field's descriptor for a project. Cache-first; on a miss,
# discover and write back, then look up. Exit 0 and print the field if it exists;
# exit 2 (empty stdout) if that field is not present/determined — skip gracefully.
def fields_resolve(args):
    if len(args) < 2:
        die(1, "usage: %s fields resolve <project-ref> <CanonicalName>" % PROG)
    key = cache_util.project_key()
    ref = normalize_ref(args[0])
    name = args[1]
    project_ref = project_ref_key(ref)
    fields_map = cached_fields_map(key, project_ref)
    if fields_map is None:
        fields_map = discover_fields_map(ref)
        write_fields_map(key, project_ref, fields_map)
    entry = fields_map.get(name) if isinstance(fields_map, dict) else None
    if not isinstance(entry, dict):
        sys.exit(2)
    # A customfield-backed field with no resolved id is undetermined on this
    # instance — treat as a graceful miss for the write path.
    if entry.get("id") is None:
        sys.exit(2)
    sys.stdout.write(json.dumps(entry, indent=2) + "\n")
    sys.exit(0)


# --- task family ------------------------------------------------------------

# Pure: normalize a flexible Estimate input into Jira's time-tracking shorthand
# ("1w 2d 3h 4m") for timetracking.originalEstimate. Accepts the same forms the
# Asana provider tolerates — minutes, decimal hours (1.5 / 1.5h), hh:mm (01:30),
# 1h30m — converts to a total minute count, then renders weeks/days/hours/minutes.
# Jira's defaults: 1d = 8h, 1w = 5d (40h). Genuinely unparseable input raises
# ValueError (the caller errors) — never a silent wrong value. No network —
# unit-testable.
def normalize_estimate_to_jira(value):
    minutes = _estimate_to_minutes(value)
    if minutes <= 0:
        return "0m"
    HOURS_PER_DAY = 8
    DAYS_PER_WEEK = 5
    MIN_PER_HOUR = 60
    MIN_PER_DAY = HOURS_PER_DAY * MIN_PER_HOUR
    MIN_PER_WEEK = DAYS_PER_WEEK * MIN_PER_DAY
    weeks, rem = divmod(minutes, MIN_PER_WEEK)
    days, rem = divmod(rem, MIN_PER_DAY)
    hours, mins = divmod(rem, MIN_PER_HOUR)
    parts = []
    if weeks:
        parts.append("%dw" % weeks)
    if days:
        parts.append("%dd" % days)
    if hours:
        parts.append("%dh" % hours)
    if mins:
        parts.append("%dm" % mins)
    return " ".join(parts)


# Pure: flexible Estimate input -> integer minutes. Shared by the Jira shorthand
# normalizer. Same accepted forms as the Asana provider's parse_estimate_to_minutes:
# plain integer = minutes; dotted number / "<n>h" = decimal hours; hh:mm; 1h30m.
def _estimate_to_minutes(value):
    if isinstance(value, bool):
        raise ValueError("Estimate cannot be a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value * 60))
    if not isinstance(value, str):
        raise ValueError("Estimate must be a number or string (got %r)" % type(value).__name__)
    s = value.strip().lower()
    if not s:
        raise ValueError("Estimate is empty")
    m = re.fullmatch(r"(\d+):([0-5]?\d)", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", s)
    if m and (m.group(1) is not None or m.group(2) is not None):
        hours = int(m.group(1)) if m.group(1) is not None else 0
        minutes = int(m.group(2)) if m.group(2) is not None else 0
        return hours * 60 + minutes
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*h", s)
    if m:
        return int(round(float(m.group(1)) * 60))
    if re.fullmatch(r"\d+", s):
        return int(s)
    if re.fullmatch(r"\d+\.\d+", s):
        return int(round(float(s) * 60))
    raise ValueError(
        "cannot parse Estimate '%s' — expected minutes (90), decimal hours (1.5 / 1.5h), "
        "hh:mm (01:30), or 1h 30m" % value)

# Jira fields reachable by `acli edit` on an EXISTING issue (per references/
# fields.md / acli.md). Anything outside this set — priority, story points
# (Sizing), time tracking (Estimate), sprint, parent, custom fields — cannot be set
# by acli and must go through the Atlassian MCP `editJiraIssue` tool (agent-handled;
# not shell-callable). The canonical-name -> acli-edit-flag map for the reachable
# ones:
ACLI_EDIT_FLAGS = {
    "Assignee": "--assignee",
    "Labels": "--labels",
    "Category": "--type",
    "Type": "--type",
}
# Summary/Description are reachable too but are not part of the canonical field set
# resolved by `fields` — they are set at create time. We keep set-field focused on
# the canonical fields; summary/description edits are a separate concern.

# The operator/agent-actionable fallback message for writes acli cannot perform.
# The script CANNOT call the Atlassian MCP itself (acli's OAuth is not exposed to
# the script, and the MCP tool is agent-invoked) — so we exit non-zero with a clear
# signal that the invoking skill must perform the MCP `editJiraIssue` fallback.
# Never a silent no-op.
def _mcp_fallback(op_desc):
    die(1, "%s: %s is not reachable via acli — needs Atlassian MCP `editJiraIssue` fallback (agent-handled, not shell-callable). The invoking workflow must perform this write via the MCP tool (or REST)." % (PROG, op_desc))


# Reduce an ADF (Atlassian Document Format) description to plain text, or pass a
# string through. ADF is a nested {type,content,text} tree — we concatenate the
# leaf `text` nodes, separating top-level blocks with newlines. Best-effort: an
# unrecognized shape returns None.
def _adf_to_text(node):
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    parts = []

    def walk(n):
        if isinstance(n, dict):
            t = n.get("text")
            if isinstance(t, str):
                parts.append(t)
            content = n.get("content")
            if isinstance(content, list):
                for c in content:
                    walk(c)
            if n.get("type") in ("paragraph", "heading"):
                parts.append("\n")

    walk(node)
    text = "".join(parts).strip()
    return text if text else None


# Extract the human-readable value of a Jira native field's raw value. Jira native
# fields are heterogeneous: assignee is an object (displayName), status is an object
# (name), issuetype is an object (name), priority is an object (name), labels is a
# list, timetracking is an object. Returns a scalar (str/list) or None.
def _native_value(jira_id, value):
    if value is None:
        return None
    if jira_id == "assignee":
        if isinstance(value, dict):
            return value.get("displayName") or value.get("name") or value.get("emailAddress")
        return value
    if jira_id in ("status", "issuetype", "priority", "parent"):
        if isinstance(value, dict):
            return value.get("name") or value.get("key")
        return value
    if jira_id == "labels":
        if isinstance(value, list):
            return value
        return value
    if jira_id == "timetracking":
        if isinstance(value, dict):
            return value.get("originalEstimate") or value.get("timeoriginalestimate")
        return value
    return value


# Pure projection: raw acli `workitem view --json` dict (a top-level object with a
# `key` and a `fields` map) -> the compact neutral shape. `metadata` is the optional
# `acli jira field list` id<->name list, used ONLY to map customfield-backed
# canonical fields (Sizing/Platform) — native fields map by their fixed ids. No
# network — unit-testable on a mock payload.
#
# - ref         : the issue key
# - task_id     : the human-readable task key — for Jira this IS the issue key (same
#                 value as ref); surfaced as a top-level read-only attribute for
#                 branch/PR naming. Native to Jira; no custom field needed.
# - name        : summary
# - description : the description (ADF reduced to text, or a string passed through)
# - assignee    : assignee display name, or None
# - status      : {name, category} from the status field (or None)
# - board       : {project, sprint} compact membership (best-effort)
# - fields      : canonical fields mapped from native ids + customfields, as
#                 {<CanonicalName>: <value>}; includes issuetype as Category.
def project_task(raw, metadata=None):
    if not isinstance(raw, dict):
        raw = {}
    fields_map = raw.get("fields")
    if not isinstance(fields_map, dict):
        fields_map = {}

    ref = raw.get("key")

    name = fields_map.get("summary")

    description = _adf_to_text(fields_map.get("description"))

    assignee = _native_value("assignee", fields_map.get("assignee"))

    status = None
    status_raw = fields_map.get("status")
    if isinstance(status_raw, dict):
        cat = status_raw.get("statusCategory")
        category = None
        if isinstance(cat, dict):
            category = cat.get("key") or cat.get("name")
        status = {"name": status_raw.get("name"), "category": category}
    elif status_raw is not None:
        status = {"name": status_raw, "category": None}

    project_name = None
    project_raw = fields_map.get("project")
    if isinstance(project_raw, dict):
        project_name = project_raw.get("name") or project_raw.get("key")
    sprint_name = None
    sprint_raw = fields_map.get("sprint")
    if isinstance(sprint_raw, dict):
        sprint_name = sprint_raw.get("name")
    elif isinstance(sprint_raw, list) and sprint_raw:
        last = sprint_raw[-1]
        if isinstance(last, dict):
            sprint_name = last.get("name")
    board = {"project": project_name, "sprint": sprint_name}

    out_fields = {}
    # Native canonical fields map by their fixed Jira ids (skip status/parent which
    # are surfaced separately or not value-bearing here). Category := issuetype.
    native_canonical = [
        ("Category", "issuetype"),
        ("Priority", "priority"),
        ("Labels", "labels"),
        ("Estimate", "timetracking"),
        ("Assignee", "assignee"),
    ]
    for canonical, jira_id in native_canonical:
        if canonical in out_fields:
            continue
        val = _native_value(jira_id, fields_map.get(jira_id))
        if val is not None:
            out_fields[canonical] = val

    # Customfield-backed canonical fields resolve their id from metadata, then read
    # the value at that id from the fields map.
    meta = metadata if isinstance(metadata, list) else []
    for canonical, _pats in CUSTOMFIELD_PATTERNS:
        if canonical in out_fields:
            continue
        cf_id = match_customfield(canonical, meta)
        if not cf_id:
            continue
        val = fields_map.get(cf_id)
        if val is None:
            continue
        if isinstance(val, dict):
            val = val.get("value") or val.get("name")
        out_fields[canonical] = val

    out = {
        "ref": ref,
        "name": name,
        "description": description,
        "assignee": assignee,
        "status": status,
        "board": board,
        "fields": out_fields,
    }
    # Jira's human key IS its issue key — surface it top-level (read-only) for
    # branch/PR naming, mirroring the Asana provider's task_id.
    if ref is not None:
        out["task_id"] = ref
    return out


# Fetch an issue and print the compact neutral projection (NOT the raw `*all` blob).
# <task-ref> is a Jira issue key. acli call; exits 1 on transport/parse failure.
def task_get(args):
    if not args:
        die(1, "usage: %s task get <task-ref>" % PROG)
    issue_key = args[0]
    ensure_authenticated()
    raw = acli_json(["jira", "workitem", "view", issue_key, "--fields", "*all", "--json"])
    metadata = fetch_field_metadata()
    sys.stdout.write(json.dumps(project_task(raw, metadata), indent=2) + "\n")
    sys.exit(0)


# Create an issue and (implicitly) place it. <project-ref> is a Jira project key.
# Maps the neutral surface onto `acli jira workitem create`: --title -> --summary,
# --description -> --description, --assignee -> --assignee. Jira requires an issue
# type, which the neutral surface does not carry — accept an optional --type
# (default "Task"). Fields acli create cannot set as flags (priority/timetracking/
# sprint/customfields) are NOT part of this neutral surface and are handled via the
# create `--from-json` path or post-create MCP fallback. Prints acli's create output.
def task_create(args):
    if not args:
        die(1, "usage: %s task create <project-ref> --title T [--description D] [--assignee A] [--type T]" % PROG)
    project_ref = args[0]
    opts = args[1:]
    title = None
    description = None
    assignee = None
    issue_type = "Task"
    i = 0
    while i < len(opts):
        flag = opts[i]
        if flag in ("--title", "--description", "--assignee", "--type"):
            if i + 1 >= len(opts):
                die(1, "%s: task create: %s requires a value" % (PROG, flag))
            value = opts[i + 1]
            if flag == "--title":
                title = value
            elif flag == "--description":
                description = value
            elif flag == "--assignee":
                assignee = value
            else:
                issue_type = value
            i += 2
        else:
            die(1, "%s: task create: unknown argument '%s'" % (PROG, flag))
    if not title:
        die(1, "%s: task create requires --title" % PROG)

    ensure_authenticated()
    cmd = ["jira", "workitem", "create", "--project", project_ref,
           "--type", issue_type, "--summary", title]
    if description is not None:
        cmd += ["--description", description]
    if assignee is not None:
        cmd += ["--assignee", assignee]
    out = acli_run(cmd)
    sys.stdout.write(out if out.endswith("\n") or not out else out + "\n")
    sys.exit(0)


# Set a field on an existing issue. <task-ref> is a Jira issue key. acli edit
# reaches only assignee / labels / type (summary/description are set at create
# time). Everything else the canonical field set names — Priority, Sizing (story
# points), Estimate (time tracking), Parent, Platform / any customfield, sprint —
# is NOT reachable by acli edit and signals the MCP `editJiraIssue` fallback
# (exit 1, never silent no-op). Product Status is set via transition, not here.
def task_set_field(args):
    if len(args) < 3:
        die(1, "usage: %s task set-field <task-ref> <CanonicalName> <value>" % PROG)
    issue_key = args[0]
    name = args[1]
    value = args[2]

    if name == "Product Status":
        die(1, "%s: task set-field: 'Product Status' is set via a workflow transition, not set-field — use the status transition path (see references/statuses.md)" % PROG)

    # Estimate (timetracking.originalEstimate) is not reachable by acli edit — it
    # goes through the MCP/REST fallback. Normalize the flexible input into Jira's
    # "1w 2d 3h 4m" shorthand FIRST so the fallback signal carries the exact value
    # the agent should write (and bad input fails here, not silently downstream).
    if name == "Estimate":
        try:
            shorthand = normalize_estimate_to_jira(value)
        except ValueError as e:
            die(1, "%s: task set-field: %s" % (PROG, e))
        _mcp_fallback("set-field 'Estimate' (timetracking.originalEstimate=\"%s\") on existing issue %s" % (shorthand, issue_key))

    flag = ACLI_EDIT_FLAGS.get(name)
    if flag is None:
        # Not reachable by acli edit (priority / sizing / parent / customfield /
        # sprint) — signal the MCP fallback.
        _mcp_fallback("set-field '%s' on existing issue %s" % (name, issue_key))

    ensure_authenticated()
    acli_run(["jira", "workitem", "edit", "--key", issue_key, flag, value, "--yes"])
    sys.stdout.write(json.dumps({"key": issue_key, "field": name, "set": True}) + "\n")
    sys.exit(0)


# Upload an attachment. acli CANNOT upload attachments (per references/acli.md), and
# the script cannot call the Atlassian MCP — so signal the MCP/operator fallback
# (exit 1, never silent no-op).
def task_attach(args):
    if len(args) < 2:
        die(1, "usage: %s task attach <task-ref> <file-path>" % PROG)
    issue_key = args[0]
    _mcp_fallback("upload_attachment to %s" % issue_key)


# Neutral lifecycle name -> target Jira statusCategory key, per
# ../references/statuses.md. Names are case-insensitive. An unknown name maps to
# None (caller errors). The not-started states all collapse onto "new".
NEUTRAL_TO_CATEGORY = {
    "requirements": "new",
    "sizing": "new",
    "refinement": "new",
    "unassigned": "new",
    "scheduled": "new",
    "assigned": "new",
    "in progress": "indeterminate",
    "in review": "indeterminate",
    "ready": "done",
    "done": "done",
    "cancelled": "done",
}


# Pure selection: given a neutral status name and the issue's available transitions
# (each {name?, to:{name, statusCategory:{key}}}), pick the target Jira status NAME
# to pass to `acli ... transition --status`. Strategy (../references/statuses.md):
# resolve the neutral name to a target statusCategory, keep transitions whose
# to.statusCategory.key matches, then prefer one whose target status name best
# matches the neutral intent (case-insensitive substring either direction); else the
# first in-category transition. Returns (status_name, None) on success, or
# (None, reason) when the neutral name is unknown or no transition reaches the
# category. No network — unit-testable on a mock transitions list.
def select_transition_status(neutral_name, transitions):
    if not isinstance(neutral_name, str):
        return (None, "status name is not a string")
    category = NEUTRAL_TO_CATEGORY.get(neutral_name.strip().lower())
    if category is None:
        return (None, "unknown neutral status '%s'" % neutral_name)
    in_category = []
    for t in transitions or []:
        if not isinstance(t, dict):
            continue
        to = t.get("to")
        if not isinstance(to, dict):
            continue
        cat = to.get("statusCategory")
        cat_key = cat.get("key") if isinstance(cat, dict) else None
        if cat_key == category:
            in_category.append(to.get("name"))
    in_category = [n for n in in_category if isinstance(n, str) and n]
    if not in_category:
        return (None, "no available transition reaches statusCategory '%s' for '%s'" % (category, neutral_name))
    low = neutral_name.strip().lower()
    for name in in_category:
        nl = name.lower()
        if low in nl or nl in low:
            return (name, None)
    return (in_category[0], None)


# List the issue's available transitions via acli, normalized to a list of
# {to:{name, statusCategory:{key}}}. acli's transition-list surface returns the
# transitions an issue can move to; shapes vary by build, so we accept either a bare
# list or a {transitions:[…]}/{values:[…]} wrapper, and normalize each entry's
# target status (some builds nest under `to`, some flatten `name`/`statusCategory`).
def fetch_transitions(issue_key):
    payload = acli_json(["jira", "workitem", "transition", "--key", issue_key, "--list", "--json"])
    raw = payload
    if isinstance(payload, dict):
        for k in ("transitions", "values"):
            v = payload.get(k)
            if isinstance(v, list):
                raw = v
                break
    out = []
    if isinstance(raw, list):
        for t in raw:
            if not isinstance(t, dict):
                continue
            to = t.get("to")
            if isinstance(to, dict):
                out.append({"to": {"name": to.get("name"),
                                   "statusCategory": to.get("statusCategory")}})
            else:
                out.append({"to": {"name": t.get("name"),
                                   "statusCategory": t.get("statusCategory")}})
    return out


# Set an issue's status. <task-ref> is a Jira issue key; <status-name> is a neutral
# lifecycle name. Resolves the neutral name -> a target status NAME by statusCategory
# (../references/statuses.md): determine the target category, list the issue's
# available transitions, pick the one whose to.statusCategory.key matches (preferring
# a name match within the category), then `acli jira workitem transition --status
# "<name>" --yes`. No transition reaches the category -> exit 1. Prints the
# resolution {key, status} on success.
def task_set_status(args):
    if len(args) < 2:
        die(1, "usage: %s task set-status <task-ref> <status-name>" % PROG)
    issue_key = args[0]
    status_name = args[1]
    ensure_authenticated()
    transitions = fetch_transitions(issue_key)
    target, reason = select_transition_status(status_name, transitions)
    if target is None:
        die(1, "%s: task set-status: cannot transition %s to '%s' — %s" % (PROG, issue_key, status_name, reason))
    acli_run(["jira", "workitem", "transition", "--key", issue_key, "--status", target, "--yes"])
    sys.stdout.write(json.dumps({"key": issue_key, "status": target}) + "\n")
    sys.exit(0)


# Probe whether this acli build exposes a workitem link command (the issue-link
# transport for add_dependency). Returns True iff `acli jira workitem link --help`
# runs successfully. Best-effort: any failure (no command, acli missing) -> False so
# the caller signals the MCP/REST partial-support fallback.
def _acli_has_link():
    try:
        proc = subprocess.run(
            ["acli", "jira", "workitem", "link", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return False
    return proc.returncode == 0


# Add a dependency (Jira issue link). <task-ref> is blocked by <depends-on-ref>;
# default link type "Blocks". Uses `acli jira workitem link` IF the build exposes it,
# else exits 1 with the MCP/REST issueLink partial-support signal (per
# ../references/acli.md → Issue Links). Never a silent no-op.
def task_add_dependency(args):
    if len(args) < 2:
        die(1, "usage: %s task add-dependency <task-ref> <depends-on-ref>" % PROG)
    task_ref = args[0]
    depends_on = args[1]
    ensure_authenticated()
    if not _acli_has_link():
        die(1, "%s: add-dependency (issue link) is not reachable via this acli build — needs Atlassian MCP / REST `POST /rest/api/3/issueLink` (agent-handled, not shell-callable). Default link type \"Blocks\": inwardIssue=%s (blocked), outwardIssue=%s (blocking)." % (PROG, task_ref, depends_on))
    # "Blocks": outward (blocking) issue is the dependency; inward (blocked) is the task.
    acli_run(["jira", "workitem", "link", "--from", depends_on, "--to", task_ref, "--type", "Blocks"])
    sys.stdout.write(json.dumps({"task": task_ref, "depends_on": depends_on, "type": "Blocks", "linked": True}) + "\n")
    sys.exit(0)


# Set an issue's parent. acli edit CANNOT set parent on an existing issue (per
# ../references/fields.md / acli.md) — signal the MCP/REST fallback (exit 1, never
# silent no-op).
def task_set_parent(args):
    if len(args) < 2:
        die(1, "usage: %s task set-parent <task-ref> <parent-ref>" % PROG)
    issue_key = args[0]
    _mcp_fallback("set-parent of %s on existing issue %s" % (args[1], issue_key))


# Add an issue to a board/sprint. acli has no sprint-add command (per
# ../references/boards.md) — signal the sprint-field/MCP/operator fallback (exit 1,
# never silent no-op).
def task_add_to_board(args):
    if len(args) < 2:
        die(1, "usage: %s task add-to-board <task-ref> <board-ref>" % PROG)
    issue_key = args[0]
    die(1, "%s: add-to-board (add %s to sprint/board %s) is not an acli capability — set the sprint field via `--from-json` at create time, or on an existing issue via Atlassian MCP `editJiraIssue` (`customfield_<sprintId>`) / REST (agent-handled); else prompt the operator to drag it into the sprint in the Jira UI (per ../references/boards.md). Never silent no-op." % (PROG, issue_key, args[1]))


# --- comment family ---------------------------------------------------------

# Post a comment to an issue. <task-ref> is a Jira issue key. The body is authored
# as Markdown (positional arg or --body-file); acli wraps it to ADF. Runs
# `acli jira workitem comment create --key <KEY> (--body <b> | --body-file <path>)`.
def comment_add(args):
    if not args:
        die(1, "usage: %s comment add <task-ref> (<body> | --body-file <path>)" % PROG)
    issue_key = args[0]
    rest = args[1:]
    body = None
    body_file = None
    if rest and rest[0] == "--body-file":
        if len(rest) < 2:
            die(1, "%s: comment add: --body-file requires a path" % PROG)
        body_file = rest[1]
        if not os.path.isfile(body_file):
            die(1, "%s: comment add: --body-file not found: %s" % (PROG, body_file))
    elif rest:
        body = rest[0]
    if body is None and body_file is None:
        die(1, "%s: comment add requires a body (<body> or --body-file <path>)" % PROG)
    if body is not None and not body:
        die(1, "%s: comment add: body is empty" % PROG)

    ensure_authenticated()
    cmd = ["jira", "workitem", "comment", "create", "--key", issue_key]
    if body_file is not None:
        cmd += ["--body-file", body_file]
    else:
        cmd += ["--body", body]
    out = acli_run(cmd)
    sys.stdout.write(out if (not out or out.endswith("\n")) else out + "\n")
    sys.exit(0)


# Compact a single acli comment entry to {author, text, created_at}. acli comment
# entries carry `author` (a name/string or an object with displayName/name), `body`
# (ADF or text), and `created`.
def _compact_comment(entry):
    if not isinstance(entry, dict):
        return {"author": None, "text": None, "created_at": None}
    author = entry.get("author")
    if isinstance(author, dict):
        author = author.get("displayName") or author.get("name") or author.get("emailAddress")
    body = entry.get("body")
    if not isinstance(body, str):
        # ADF or other structured body — pass it through as-is for the caller.
        body = body
    return {
        "author": author,
        "text": body,
        "created_at": entry.get("created"),
    }


# List an issue's comments. <task-ref> is a Jira issue key. `comment list --json`
# returns an OBJECT {comments,total,…}; we read `.comments` (NOT the top-level) and
# print the compact [{author, text, created_at}].
def comment_list(args):
    if not args:
        die(1, "usage: %s comment list <task-ref>" % PROG)
    issue_key = args[0]
    ensure_authenticated()
    payload = acli_json(["jira", "workitem", "comment", "list", "--key", issue_key, "--json"])
    comments = []
    if isinstance(payload, dict):
        v = payload.get("comments")
        if isinstance(v, list):
            comments = v
    out = [_compact_comment(c) for c in comments]
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    sys.exit(0)


# --- ref family -------------------------------------------------------------

# Jira issue-key regex, per ../references/acli.md. First occurrence wins.
_JIRA_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]+-\d+")
# app.asana.com URLs are explicitly another provider's — reject even if some segment
# happened to look key-like.
_ASANA_HOST_RE = re.compile(r"^https?://app\.asana\.com/", re.IGNORECASE)


# Extract the canonical Jira issue key from an input, or None if not recognizable as
# a Jira issue reference. Accepts a *.atlassian.net URL or a bare key; takes the first
# `[A-Z][A-Z0-9_]+-\d+` match. An app.asana.com URL or a bare numeric id returns None.
def jira_extract_ref(raw):
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if _ASANA_HOST_RE.search(s):
        return None
    m = _JIRA_KEY_RE.search(s)
    if m:
        return m.group(0)
    return None


# `ref parse <url-or-ref>`: print the canonical Jira issue key and exit 0 if the input
# is a Jira issue reference; exit 2 (no output) if it is not this provider's.
def ref_parse(args):
    if not args:
        die(1, "usage: %s ref parse <url-or-ref>" % PROG)
    key = jira_extract_ref(args[0])
    if key is None:
        sys.exit(2)
    sys.stdout.write(key + "\n")
    sys.exit(0)


# --- dispatch ---------------------------------------------------------------

BOARD_VERBS = {
    "key": board_key,
    "read": board_read,
    "resolve": board_resolve,
    "discover": board_discover,
    "refresh": board_refresh,
    "write": board_write,
}

FIELDS_VERBS = {
    "list": fields_list,
    "resolve": fields_resolve,
    "discover": fields_discover,
}

TASK_VERBS = {
    "get": task_get,
    "create": task_create,
    "set-field": task_set_field,
    "attach": task_attach,
    "set-status": task_set_status,
    "add-dependency": task_add_dependency,
    "set-parent": task_set_parent,
    "add-to-board": task_add_to_board,
}

COMMENT_VERBS = {
    "add": comment_add,
    "list": comment_list,
}

REF_VERBS = {
    "parse": ref_parse,
}

FAMILIES = {
    "board": BOARD_VERBS,
    "fields": FIELDS_VERBS,
    "task": TASK_VERBS,
    "comment": COMMENT_VERBS,
    "ref": REF_VERBS,
}


def main(argv):
    if not argv:
        die(1, "usage: %s <family> <verb> [args]" % PROG)
    family = argv[0]
    verbs = FAMILIES.get(family)
    if verbs is None:
        die(1, "%s: unknown family: %s" % (PROG, family))
    if len(argv) < 2:
        die(1, "usage: %s %s <verb> [args]" % (PROG, family))
    verb = argv[1]
    rest = argv[2:]
    handler = verbs.get(verb)
    if handler is None:
        die(1, "%s: unknown %s verb: %s" % (PROG, family, verb))
    handler(rest)


if __name__ == "__main__":
    main(sys.argv[1:])
