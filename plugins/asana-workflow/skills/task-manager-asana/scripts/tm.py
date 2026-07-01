#!/usr/bin/env python3
#
# tm.py — per-provider task-manager CLI for the Asana provider.
#
# One CLI per provider, dispatched by family + verb: `tm.py <family> <verb> [args]`.
# Families namespace operation groups so future ops (fields, tasks, attachments) can
# be added without colliding. The first family is `board`.
#
# Board family — code-enforced board-cache resolution. The cache lifecycle documented
# in ../references/boards.md is implemented here so the provider MUST go through it:
# cache-first reads, sprint auto-refresh only when stale, and live discovery only on a
# genuine miss (which then writes back). This removes the failure mode where an agent
# bypasses a valid cache and does live discovery, landing on a stale backlog.
#
# Usage:
#   tm.py board key
#   tm.py board read     <key>
#   tm.py board resolve  <key> <active-sprint|backlog>
#   tm.py board discover <key>
#   tm.py board refresh  <key>
#   tm.py board write    <key> <json>
#
# Fields family — code-enforced custom-field DISCOVERY + name->id mapping. The
# rules in ../references/custom-fields.md (canonical field set, fuzzy match-pattern
# table, Assignee-is-native, Estimate unit handling) are implemented here so the agent
# no longer ingests full field JSON and fuzzy-matches by hand on every call. The
# discovered map is cached in the SAME per-repo cache file under a "fields" section
# keyed by project gid. Fields change rarely, so there is no date-staleness — list/
# resolve discover-on-miss and write back; force a refresh with `fields discover`.
# This batch is the READ/mapping side only; setting a field value is a later batch.
#
#   tm.py fields list     <project-gid>
#   tm.py fields resolve  <project-gid> <CanonicalName>
#   tm.py fields discover <project-gid>
#
# <project-gid> is an Asana project GID.
#
# Task family — code-enforced, SANDBOX-SAFE task WRITES (create / set-field /
# attach), all via urllib (NEVER curl: `curl -F` multipart and `curl -d "$(…)"`
# command-substituted bodies intermittently fail under the Bash sandbox's
# restrictive profile — "failed to change group ID"; a single top-level Python
# urllib process avoids it). Reuses the inline transport + token resolver and the
# `fields` resolution logic.
#
#   tm.py task get           <task-ref>
#   tm.py task create        <project-ref> --title T [--description D] [--assignee A]
#                            [--set Name=Value ...] [--wait-key]
#   tm.py task set-field     <task-ref> <CanonicalName> <value>
#   tm.py task set-fields    <task-ref> <Name=Value> [<Name=Value> ...]
#   tm.py task set-notes     <task-ref> (<body> | --body-file <path>)
#   tm.py task attach        <task-ref> <file-path>
#   tm.py task add-dependency <task-ref> <depends-on-ref>
#   tm.py task set-parent    <task-ref> <parent-ref>
#   tm.py task add-to-board  <task-ref> <board-ref>
#   tm.py task set-status    <task-ref> <status-name>
#
# add-dependency/set-parent/add-to-board are single POSTs (addDependencies /
# setParent / addProject), all via urllib. set-status is TWO-AXIS per
# ../../../references/workflow/lifecycle.md: it tries the Product Status custom
# field FIRST (resolve via the `fields` logic; if <status-name> matches an enum
# option, PUT custom_fields), and falls back to a board SECTION move (discover the
# task's project sections; if <status-name> matches a section name, POST
# /sections/<gid>/addTask). Matches neither -> exit 1 with a clear message.
#
# `task get` fetches the task with the documented opt_fields and prints a COMPACT
# neutral projection (NOT the raw API blob) — {ref,name,description,assignee,status,
# board,fields,task_id?} — to save tokens. `task_id` is the human task key, surfaced
# read-only from a custom_id field (by resource_subtype) or, failing that, a text
# field whose value matches the XXX-123 key shape (names vary per project). Custom-field
# names are mapped to canonical names
# via the same `fields` match logic; `status` is the Product Status field's value.
# For unusual long-tail needs, the raw `opt_fields` recipe in ../references/rest.md
# is still available.
#
# <project-ref> is an Asana project GID; <task-ref> is an Asana task GID.
#
# Ref family — find_task(ref) for the Asana provider AND the recognition probe used
# by the neutral seam's provider detection. `ref parse <url-or-ref>` extracts the
# numeric task GID from an Asana URL (per ../references/rest.md URL Formats) or a bare
# numeric id, prints ONLY the canonical ref (the GID) to stdout, and exits 0. Input
# that is not recognizable as an Asana task reference (e.g. an atlassian.net URL, a
# bare Jira key, garbage) exits 2 ("not mine") — no output. This lets resolve_provider
# probe each installed provider with the same input and let the recognizer win.
#
#   tm.py ref parse <url-or-ref>
#
# Comment family — post and read task comments (stories), SANDBOX-SAFE via urllib.
# `comment add` authors the body as Markdown, converts it to Asana HTML, routes it
# through the correct API field (text vs html_text), defends against <br> (which
# Asana silently rejects in rich text), then POSTs /tasks/<gid>/stories.
# `comment list` reads /tasks/<gid>/stories filtered to type=="comment" and returns
# the compact [{author, text, created_at}] shape.
#
#   tm.py comment add  <task-ref> (<body> | --body-file <path>)
#   tm.py comment list <task-ref>
#
# <key> comes from `tm.py board key` (git remote -> sanitized; fallback to repo
# basename). Callers derive it once and pass it to every other command.
#
# Token resolution: the env var named in the cache's `asana_token_env` field if
# present, else $ASANA_PERSONAL_ACCESS_TOKEN. Empty resolved token -> exit 1.
#
# Exit codes:
#   0  success / cache present & fresh
#   1  argument error, empty token, or HTTP/API failure
#   2  cache missing (miss)
#   3  cache present but stale (active_sprint.due_on < today)
#   4  bootstrap needed (miss with no workspace_gid cached — agent must bootstrap)
#
# Dependencies: Python 3 stdlib + git. No interactive prompts. Never prints secrets.

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "task-manager", "scripts"))
import cache_util

PROG = "tm.py"
PROVIDER = "asana"
API_BASE = "https://app.asana.com/api/1.0"
# The human key (PD###-##) is assigned by an Asana Rule a moment AFTER the task is
# added to its project — measured ~0.5s, but asynchronous. `task create` does NOT
# wait by default: the key is resolved lazily by whoever needs it (create-pr
# re-fetches at PR time, by which point it is set). Only `create --wait-key` polls,
# for a tight create-then-immediately-name-branch flow. Bounded so id-less projects
# don't hang.
TASK_ID_POLL_ATTEMPTS = 8
TASK_ID_POLL_INTERVAL = 0.5
# Bump when build_fields_map's entry shape changes so stale caches re-discover.
# v2 adds name/format/precision (needed for Estimate unit handling).
FIELDS_SCHEMA_VERSION = 2
# Board classification patterns (regex strings). A project is a SPRINT if its name
# matches any sprint pattern; a BACKLOG board if it matches any backlog pattern AND no
# sprint pattern. Defaults cover the known siroc conventions; a workspace with a
# different naming scheme overrides them per-project via the cache's optional
# `sprint_patterns` / `backlog_patterns` arrays (see ../references/boards.md). Prefer
# adding config over widening these defaults.
DEFAULT_SPRINT_PATTERNS = [
    r"^ENG \| Sprint \d+\.\d+",   # ENG | Sprint 26.16
    r"^Sprint\b",                  # Sprint Board 26/13, Sprint <anything>
]
DEFAULT_BACKLOG_PATTERNS = [
    r"^ENG \| ",                   # ENG | Bugs & Issues
    r"^PD\d+-\d+",                 # PD26-8 :: Android app
]
# Human task-key shape (e.g. PD268-72, MT251-47). Used to recognize the key when it
# lives in a plain text custom field (not an auto-managed custom_id field).
TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def err(msg):
    sys.stderr.write(msg + "\n")


def die(code, msg=None):
    if msg is not None:
        err(msg)
    sys.exit(code)


# --- Asana transport --------------------------------------------------------

# Resolve the Asana token: env var named in the cache's asana_token_env, else
# ASANA_PERSONAL_ACCESS_TOKEN. Empty -> exit 1. Returns the token value (callers
# use it; never log it).
def resolve_token(key):
    env_name = ""
    cache = cache_util.read_cache(key)
    if cache is not None:
        v = cache.get("asana_token_env")
        if isinstance(v, str) and v:
            env_name = v
    if not env_name:
        env_name = "ASANA_PERSONAL_ACCESS_TOKEN"
    token = os.environ.get(env_name, "")
    if not token:
        die(1, "%s: Asana token is empty (env var '%s' unset or empty)" % (PROG, env_name))
    return token


# HTTP GET against the Asana API. Fails (exit 1) on transport error or non-2xx.
# Returns the parsed JSON body.
def api_get(url, token):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    try:
        resp = urllib.request.urlopen(req)
        status = resp.getcode()
        body = resp.read()
    except urllib.error.HTTPError as e:
        die(1, "%s: Asana API error (HTTP %s) on GET %s" % (PROG, e.code, url))
    except urllib.error.URLError as e:
        die(1, "%s: request failed: GET %s (%s)" % (PROG, url, e.reason))
    except Exception as e:
        die(1, "%s: request failed: GET %s (%s)" % (PROG, url, e))
    if status < 200 or status >= 300:
        die(1, "%s: Asana API error (HTTP %s) on GET %s" % (PROG, status, url))
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        die(1, "%s: Asana API returned invalid JSON on GET %s" % (PROG, url))


# HTTP request with a JSON body (POST/PUT) against the Asana API. `payload` is the
# object that becomes the request body (typically {"data": {...}}). Fails (exit 1)
# on transport error or non-2xx. Returns the parsed JSON body. urllib only — never
# curl: command-substituted `curl -d "$(…)"` bodies fail under the Bash sandbox.
def api_json(url, token, method, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        status = resp.getcode()
        body = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").strip()
        if "cannot_manually_create_or_update_custom_id_field" in detail:
            die(1, "%s: that field is an auto-managed Asana ID field — it is read-only and "
                   "cannot be set via the API (Asana assigns it / it is set in the UI). "
                   "Read it for naming; never write it." % PROG)
        if "duration_format" in detail:
            die(1, "%s: this Estimate field uses Asana's duration format, which this account "
                   "cannot set via the API — set it in the Asana UI (the value is still "
                   "readable for display/readiness)." % PROG)
        die(1, "%s: Asana API error (HTTP %s) on %s %s%s" % (
            PROG, e.code, method, url, (": " + detail) if detail else ""))
    except urllib.error.URLError as e:
        die(1, "%s: request failed: %s %s (%s)" % (PROG, method, url, e.reason))
    except Exception as e:
        die(1, "%s: request failed: %s %s (%s)" % (PROG, method, url, e))
    if status < 200 or status >= 300:
        die(1, "%s: Asana API error (HTTP %s) on %s %s" % (PROG, status, method, url))
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        die(1, "%s: Asana API returned invalid JSON on %s %s" % (PROG, method, url))


# Multipart/form-data POST built entirely in Python (urllib) — the sandbox-safe
# replacement for `curl -F`, which intermittently fails under the Bash sandbox
# ("failed to change group ID"). `fields` is a list of (name, value) text parts;
# `file_field` is (field_name, file_path) read from disk and sent as a binary part.
# Fails (exit 1) on transport error or non-2xx. Returns the parsed JSON body.
def api_multipart(url, token, fields, file_field):
    import io
    import mimetypes
    import uuid

    boundary = "----asana-tm-" + uuid.uuid4().hex
    buf = io.BytesIO()

    def w(s):
        buf.write(s.encode("utf-8") if isinstance(s, str) else s)

    for name, value in fields:
        w("--%s\r\n" % boundary)
        w('Content-Disposition: form-data; name="%s"\r\n\r\n' % name)
        w("%s\r\n" % value)

    field_name, file_path = file_field
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        die(1, "%s: cannot read attachment file '%s' (%s)" % (PROG, file_path, e))
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    w("--%s\r\n" % boundary)
    w('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (field_name, filename))
    w("Content-Type: %s\r\n\r\n" % ctype)
    w(file_bytes)
    w("\r\n")
    w("--%s--\r\n" % boundary)

    body = buf.getvalue()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        resp = urllib.request.urlopen(req)
        status = resp.getcode()
        resp_body = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").strip()
        die(1, "%s: Asana API error (HTTP %s) on POST %s%s" % (
            PROG, e.code, url, (": " + detail) if detail else ""))
    except urllib.error.URLError as e:
        die(1, "%s: request failed: POST %s (%s)" % (PROG, url, e.reason))
    except Exception as e:
        die(1, "%s: request failed: POST %s (%s)" % (PROG, url, e))
    if status < 200 or status >= 300:
        die(1, "%s: Asana API error (HTTP %s) on POST %s" % (PROG, status, url))
    try:
        return json.loads(resp_body.decode("utf-8", "replace"))
    except Exception:
        die(1, "%s: Asana API returned invalid JSON on POST %s" % (PROG, url))


# --- cache field accessors --------------------------------------------------

# Read workspace_gid from cache, or empty if absent.
def workspace_gid_from(key):
    cache = cache_util.read_cache(key)
    if cache is None:
        return ""
    v = cache.get("workspace_gid")
    if isinstance(v, str) and v:
        return v
    return ""


# --- discovery helpers ------------------------------------------------------

# Collect all workspace projects, following next_page pagination.
def fetch_all_projects(wgid, token):
    # archived=false excludes archived projects server-side (e.g. old "Sprint Board -
    # NN"); `archived` is also fetched so the selectors can defensively skip any that
    # slip through.
    url = "%s/workspaces/%s/projects?opt_fields=name,completed,due_on,archived&archived=false&limit=100" % (API_BASE, wgid)
    all_projects = []
    while url:
        page = api_get(url, token)
        data = page.get("data")
        if isinstance(data, list):
            all_projects.extend(data)
        next_page = page.get("next_page")
        url = ""
        if isinstance(next_page, dict):
            uri = next_page.get("uri")
            if isinstance(uri, str) and uri:
                url = uri
    return all_projects


# Compile a list of regex-string patterns. `values` (from cache) replaces `defaults`
# only when it is a non-empty list; invalid patterns are skipped (warned); if nothing
# compiles, fall back to defaults. Returns a list of compiled regexes.
def _compile_patterns(values, defaults):
    src = values if isinstance(values, list) and values else defaults
    out = []
    for pat in src:
        if not isinstance(pat, str):
            continue
        try:
            out.append(re.compile(pat))
        except re.error:
            err("%s: ignoring invalid board pattern %r" % (PROG, pat))
    return out or [re.compile(p) for p in defaults]


# Resolve (sprint_res, backlog_res) compiled-pattern lists for a project, honoring
# optional cache overrides (`sprint_patterns` / `backlog_patterns`) or the defaults.
def classification_patterns(cache):
    c = cache if isinstance(cache, dict) else {}
    return (
        _compile_patterns(c.get("sprint_patterns"), DEFAULT_SPRINT_PATTERNS),
        _compile_patterns(c.get("backlog_patterns"), DEFAULT_BACKLOG_PATTERNS),
    )


def _matches_any(name, regexes):
    return any(r.search(name) for r in regexes)


# Natural-sort key: splits a name into text/number chunks so "Sprint Board 26/2" sorts
# BEFORE "26/13" (numeric, not lexical). Used only for the no-due_on fallback below.
def _natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s or "")]


# Active sprint among sprint-pattern matches that are not archived and not completed.
# Selection:
#   - If any candidate carries a due_on (the ENG | convention): keep only due_on >=
#     today, latest due_on wins, else None — UNCHANGED from the original rule.
#   - Else (a convention that doesn't set sprint due dates, e.g. "Sprint Board 26/13"):
#     pick the highest sprint number by natural-sorted name.
# Returns {gid,name,due_on} or None.
def select_active_sprint(projects, today, sprint_res):
    candidates = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not isinstance(name, str) or not _matches_any(name, sprint_res):
            continue
        if p.get("archived") is True:
            continue
        if p.get("completed") is not False:
            continue
        candidates.append(p)
    if not candidates:
        return None
    dated = [c for c in candidates if isinstance(c.get("due_on"), str)]
    if dated:
        live = [c for c in dated if c.get("due_on") >= today]
        if not live:
            return None
        live.sort(key=lambda x: x.get("due_on"))
        winner = live[-1]
    else:
        try:
            winner = max(candidates, key=lambda p: _natural_key(p.get("name") or ""))
        except TypeError:
            winner = max(candidates, key=lambda p: p.get("name") or "")
    return {"gid": winner.get("gid"), "name": winner.get("name"), "due_on": winner.get("due_on")}


# Backlog boards: name matches any backlog pattern, is NOT a sprint, not archived.
def select_backlog_boards(projects, sprint_res, backlog_res):
    out = []
    for p in projects:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not isinstance(name, str):
            continue
        if p.get("archived") is True:
            continue
        if _matches_any(name, backlog_res) and not _matches_any(name, sprint_res):
            out.append({"gid": p.get("gid"), "name": name})
    return out


# --- board family commands --------------------------------------------------

# Print the project key per ../references/boards.md derivation.
def board_key(args):
    sys.stdout.write(cache_util.project_key() + "\n")


# Read cache. Exit 0 fresh, 2 miss, 3 stale. Prints cache JSON to stdout when
# present (empty on miss).
def board_read(args):
    if not args:
        die(1, "usage: %s board read <key>" % PROG)
    key = args[0]
    if not os.path.isfile(cache_util.cache_path(key)):
        sys.exit(2)
    cache = cache_util.read_cache(key)
    # A different provider's cache is not ours to read — treat as a miss. A
    # missing marker counts as Asana (legacy; self-heals on next discover).
    if not cache_util.provider_matches(cache, PROVIDER):
        sys.exit(2)
    sys.stdout.write(json.dumps(cache, indent=2) + "\n")
    due = ""
    if isinstance(cache, dict):
        active = cache.get("active_sprint")
        if isinstance(active, dict):
            d = active.get("due_on")
            if isinstance(d, str):
                due = d
    # No active_sprint or no due_on -> treat as fresh for read purposes; resolve/
    # discover handle the absence. Stale only when a due_on exists and is past.
    if cache_util.is_date_stale(due):
        sys.exit(3)
    sys.exit(0)


# Validate and write a cache JSON blob.
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


# Run full discovery against the Asana API and write the cache. Requires a cached
# workspace_gid and a resolvable token.
def board_discover(args):
    if not args:
        die(1, "usage: %s board discover <key>" % PROG)
    key = args[0]
    wgid = workspace_gid_from(key)
    if not wgid:
        die(4, "%s: board discover requires a cached workspace_gid — run bootstrap first (board write <key> <json>)" % PROG)
    token = resolve_token(key)
    cache = cache_util.read_cache(key)
    token_env = "ASANA_PERSONAL_ACCESS_TOKEN"
    if isinstance(cache, dict):
        v = cache.get("asana_token_env")
        if isinstance(v, str) and v:
            token_env = v

    sprint_res, backlog_res = classification_patterns(cache)
    all_projects = fetch_all_projects(wgid, token)
    today = cache_util.today_utc()
    active_sprint = select_active_sprint(all_projects, today, sprint_res)
    backlog_boards = select_backlog_boards(all_projects, sprint_res, backlog_res)

    new_json = {
        "provider": PROVIDER,
        "workspace_gid": wgid,
        "asana_token_env": token_env,
        "cached_at": cache_util.now_iso(),
        "active_sprint": active_sprint,
        "backlog_boards": backlog_boards,
    }
    # Preserve any per-project pattern overrides across re-discovery.
    if isinstance(cache, dict):
        for k in ("sprint_patterns", "backlog_patterns"):
            if isinstance(cache.get(k), list):
                new_json[k] = cache[k]
    cache_util.write_cache(key, new_json)
    sys.stdout.write(json.dumps(cache_util.read_cache(key), indent=2) + "\n")


# Re-run active-sprint selection against the API and write it back, preserving
# the rest of the cache. Used by `board refresh` and the stale path of `board
# resolve`.
def board_refresh(args):
    if not args:
        die(1, "usage: %s board refresh <key>" % PROG)
    key = args[0]
    if not os.path.isfile(cache_util.cache_path(key)):
        die(2, "%s: board refresh: no cache for key '%s'" % (PROG, key))
    wgid = workspace_gid_from(key)
    if not wgid:
        die(4, "%s: board refresh requires a cached workspace_gid" % PROG)
    token = resolve_token(key)

    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        cache = {}
    sprint_res, _ = classification_patterns(cache)
    all_projects = fetch_all_projects(wgid, token)
    today = cache_util.today_utc()
    active_sprint = select_active_sprint(all_projects, today, sprint_res)

    cache["provider"] = PROVIDER
    cache["active_sprint"] = active_sprint
    cache["cached_at"] = cache_util.now_iso()
    cache_util.write_cache(key, cache)
    sys.stdout.write(json.dumps(cache_util.read_cache(key), indent=2) + "\n")


# High-level provider entry point. intent in {active-sprint, backlog}.
def board_resolve(args):
    if len(args) < 2:
        die(1, "usage: %s board resolve <key> <active-sprint|backlog>" % PROG)
    key = args[0]
    intent = args[1]
    if intent not in ("active-sprint", "backlog"):
        die(1, "%s: board resolve: intent must be 'active-sprint' or 'backlog'" % PROG)

    if not os.path.isfile(cache_util.cache_path(key)):
        # Miss. Distinguish "bootstrap needed" (no workspace_gid to discover with)
        # from any future scenario where we could self-discover.
        die(4, "%s: bootstrap needed: no cache for '%s' — resolve workspace + token env, then '%s board write <key> <json>' and '%s board discover <key>'" % (PROG, key, PROG, PROG))

    cache = cache_util.read_cache(key)
    # A different provider's cache can't satisfy an Asana resolve — bootstrap as
    # if missing. A missing marker counts as Asana (legacy; self-heals).
    if not cache_util.provider_matches(cache, PROVIDER):
        die(4, "%s: bootstrap needed: cache for '%s' belongs to another provider — write config then discover" % (PROG, key))

    due = ""
    if isinstance(cache, dict):
        active = cache.get("active_sprint")
        if isinstance(active, dict):
            d = active.get("due_on")
            if isinstance(d, str):
                due = d

    stale = cache_util.is_date_stale(due)

    if stale:
        # Sprint auto-refresh, then return from the refreshed cache.
        _capture_stdout(board_refresh, [key])
        cache = cache_util.read_cache(key)

    if intent == "active-sprint":
        active = cache.get("active_sprint") if isinstance(cache, dict) else None
        if active is None and not stale:
            # Cache present but no active sprint recorded — re-discover before
            # concluding there is none, so a never-populated/stale null is never
            # returned as if authoritative. (If we already refreshed above, skip.)
            wgid = workspace_gid_from(key)
            if not wgid:
                die(4, "%s: bootstrap needed: cache for '%s' has no active_sprint and no workspace_gid — write config then discover" % (PROG, key))
            _capture_stdout(board_refresh, [key])
            cache = cache_util.read_cache(key)
            active = cache.get("active_sprint") if isinstance(cache, dict) else None
        sys.stdout.write(json.dumps(active) + "\n")
    elif intent == "backlog":
        backlog = []
        if isinstance(cache, dict):
            v = cache.get("backlog_boards")
            if isinstance(v, list):
                backlog = v
        sys.stdout.write(json.dumps(backlog) + "\n")


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

# Canonical fields and their fuzzy, case-insensitive match patterns, per
# ../references/custom-fields.md. Order matters: a project's field name is matched
# against each canonical field's patterns; the first canonical field whose pattern
# substring-matches wins. "Category" ("category"/"type") is listed before
# "Product Status" so a "Product Status" field — whose own patterns include the
# generic "status"/"state" — is not stolen, and so a bare "Type" field maps to
# Category. Assignee is native (not a custom field) and is injected separately.
CANONICAL_FIELD_PATTERNS = [
    ("Platform", ["platform"]),
    ("Priority", ["priority", "urgency", "severity"]),
    ("Sizing", ["story points", "t-shirt", "sizing", "size", "points"]),
    ("Estimate", ["estimated time", "time estimate", "estimate", "effort"]),
    ("Category", ["category", "type"]),
    ("Product Status", ["product status", "status", "state"]),
]


# Map an Asana custom field's name to a canonical field name, or None if no
# canonical field's patterns match. Case-insensitive substring match; the first
# canonical field (in CANONICAL_FIELD_PATTERNS order) with any matching pattern
# wins.
def match_canonical(field_name):
    if not isinstance(field_name, str):
        return None
    low = field_name.lower()
    for canonical, patterns in CANONICAL_FIELD_PATTERNS:
        for pat in patterns:
            if pat in low:
                return canonical
    return None


# Build the compact canonical map from a list of custom_field_settings entries
# returned by the Asana API. Each entry has a nested `custom_field`. Records gid,
# type and (for enum) option gid+name under the canonical name. Assignee is added
# as a native field (no gid). Later duplicate matches for the same canonical name
# do not overwrite an earlier one.
def build_fields_map(settings):
    out = {}
    # Assignee is native in Asana (not a custom field).
    out["Assignee"] = {"native": True, "type": "assignee"}
    for s in settings:
        if not isinstance(s, dict):
            continue
        cf = s.get("custom_field")
        if not isinstance(cf, dict):
            continue
        name = cf.get("name")
        canonical = match_canonical(name)
        if canonical is None or canonical in out:
            continue
        entry = {"id": cf.get("gid"), "type": cf.get("type"), "name": name}
        if cf.get("type") == "enum":
            opts = []
            raw_opts = cf.get("enum_options")
            if isinstance(raw_opts, list):
                for o in raw_opts:
                    if isinstance(o, dict):
                        opts.append({"id": o.get("gid"), "name": o.get("name")})
            entry["enum_options"] = opts
        elif cf.get("type") == "number":
            # format/precision drive Estimate unit handling (duration vs hours/minutes).
            entry["format"] = cf.get("format")
            entry["precision"] = cf.get("precision")
        out[canonical] = entry
    return out


# Fetch and build the canonical fields map for an Asana project via its
# custom_field_settings. Network call; exits 1 on transport/API failure.
def discover_fields_map(project_gid, token):
    url = (
        "%s/projects/%s/custom_field_settings"
        "?opt_fields=custom_field.gid,custom_field.name,custom_field.type,"
        "custom_field.format,custom_field.precision,"
        "custom_field.enum_options,custom_field.enum_options.gid,"
        "custom_field.enum_options.name" % (API_BASE, project_gid)
    )
    page = api_get(url, token)
    data = page.get("data") if isinstance(page, dict) else None
    settings = data if isinstance(data, list) else []
    return build_fields_map(settings)


# Read the cached fields map for a project gid, or None if absent. The fields live
# under cache["fields"][<project_gid>] in the same per-repo cache file.
def cached_fields_map(key, project_gid):
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        return None
    if not cache_util.provider_matches(cache, PROVIDER):
        return None
    if cache.get("fields_schema_version") != FIELDS_SCHEMA_VERSION:
        return None  # stale entry shape — force re-discovery
    fields = cache.get("fields")
    if not isinstance(fields, dict):
        return None
    fm = fields.get(project_gid)
    if isinstance(fm, dict):
        return fm
    return None


# Write the fields map for a project gid into the cache, preserving the rest of the
# cache and stamping the provider marker.
def write_fields_map(key, project_gid, fields_map):
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        cache = {}
    cache["provider"] = PROVIDER
    cache["fields_schema_version"] = FIELDS_SCHEMA_VERSION
    fields = cache.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    fields[project_gid] = fields_map
    cache["fields"] = fields
    cache_util.write_cache(key, cache)


# Force a fresh discovery from Asana and write it to cache; print the map.
def fields_discover(args):
    if not args:
        die(1, "usage: %s fields discover <project-gid>" % PROG)
    key = cache_util.project_key()
    project_gid = args[0]
    token = resolve_token(key)
    fields_map = discover_fields_map(project_gid, token)
    write_fields_map(key, project_gid, fields_map)
    sys.stdout.write(json.dumps(fields_map, indent=2) + "\n")


# Return the canonical fields map for a project. Cache-first; on a miss, discover
# from Asana and write back. Exit 0.
def fields_list(args):
    if not args:
        die(1, "usage: %s fields list <project-gid>" % PROG)
    key = cache_util.project_key()
    project_gid = args[0]
    fields_map = cached_fields_map(key, project_gid)
    if fields_map is None:
        token = resolve_token(key)
        fields_map = discover_fields_map(project_gid, token)
        write_fields_map(key, project_gid, fields_map)
    sys.stdout.write(json.dumps(fields_map, indent=2) + "\n")
    sys.exit(0)


# Resolve a single canonical field's descriptor for a project. Cache-first; on a
# miss, discover and write back, then look up. Returns the descriptor dict, or None
# when the canonical field is not present on the project (skip gracefully — not
# every project has every field). Shared by `fields resolve` and `task set-field`.
def _resolve_field_entry(key, project_gid, name):
    fields_map = cached_fields_map(key, project_gid)
    if fields_map is None:
        token = resolve_token(key)
        fields_map = discover_fields_map(project_gid, token)
        write_fields_map(key, project_gid, fields_map)
    entry = fields_map.get(name) if isinstance(fields_map, dict) else None
    if not isinstance(entry, dict):
        return None
    return entry


# Return a single canonical field's descriptor for a project. Cache-first; on a
# miss, discover and write back, then look up. Exit 0 and print the field if it
# exists on the project; exit 2 (empty stdout) if that canonical field is not
# present — skip gracefully, not every project has every field.
def fields_resolve(args):
    if len(args) < 2:
        die(1, "usage: %s fields resolve <project-gid> <CanonicalName>" % PROG)
    key = cache_util.project_key()
    project_gid = args[0]
    name = args[1]
    entry = _resolve_field_entry(key, project_gid, name)
    if entry is None:
        # Field not present on this project — skip gracefully.
        sys.exit(2)
    sys.stdout.write(json.dumps(entry, indent=2) + "\n")
    sys.exit(0)


# --- task family ------------------------------------------------------------

# Pure: coerce a flexible Estimate input into canonical integer MINUTES. This is the
# internal canonical unit only; estimate_number_value then converts it to the value
# actually written, which depends on the target field (hours/minutes/duration).
# `entry` is the resolved field descriptor; it disambiguates a BARE integer (see
# below) so input and output agree on the unit. Accepted forms (case-insensitive,
# surrounding whitespace ignored):
#   - bare integer          -> the FIELD's unit via _estimate_unit_is_hours(entry):
#                              hours field "1" -> 60; minutes/duration or no descriptor
#                              "1" -> 1. (This is the fix for "1" -> 0.02h.)
#   - bare decimal (has ".")-> DECIMAL HOURS, always  ("1.5" -> 90) — decimals are
#                              estimates in hours regardless of field unit
#   - decimal hours + "h"   -> "1.5h" -> 90 ; "2h" -> 120
#   - hh:mm / h:mm          -> "01:30" / "1:30" -> 90  (hours*60 + minutes)
#   - "1h 30m" / "1h30m" / "90m" / "2h" -> sum of the h/m components
# Explicit-unit forms always win over the bare-integer inference. Genuinely unparseable
# input raises ValueError (the caller exits 1) — never a silent wrong number.
# No network — unit-testable.
def _estimate_unit_is_hours(entry):
    """True if the Estimate field stores decimal HOURS (vs minutes). Shared by BOTH the
    input parser (what a bare number means) and the output writer, so the two can never
    disagree. No descriptor (entry=None) -> minutes, backward compatible."""
    if not isinstance(entry, dict):
        return False
    if (entry.get("format") or "").lower() == "duration":
        return False  # paid duration fields are minute-based
    name = (entry.get("name") or "").lower()
    is_minutes = "minute" in name or "(min" in name or name.endswith(" min")
    is_hours = "hour" in name or "hr" in name
    return is_hours and not is_minutes


def parse_estimate_to_minutes(value, entry=None):
    if isinstance(value, bool):
        raise ValueError("Estimate cannot be a boolean")
    if isinstance(value, int):
        return value * 60 if _estimate_unit_is_hours(entry) else value
    if isinstance(value, float):
        # A float is decimal hours (e.g. 1.5 -> 90).
        return int(round(value * 60))
    if not isinstance(value, str):
        raise ValueError("Estimate must be a number or string (got %r)" % type(value).__name__)
    s = value.strip().lower()
    if not s:
        raise ValueError("Estimate is empty")

    # hh:mm / h:mm
    m = re.fullmatch(r"(\d+):([0-5]?\d)", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    # 1h 30m / 1h30m / 90m / 2h / 1h (h and/or m components)
    m = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", s)
    if m and (m.group(1) is not None or m.group(2) is not None):
        hours = int(m.group(1)) if m.group(1) is not None else 0
        minutes = int(m.group(2)) if m.group(2) is not None else 0
        return hours * 60 + minutes

    # Decimal hours with explicit "h": 1.5h -> 90
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*h", s)
    if m:
        return int(round(float(m.group(1)) * 60))

    # Bare number: a dotted value is decimal HOURS (1.5 -> 90, always). A plain integer
    # is interpreted in the FIELD's unit — an hours field reads "1" as 1 hour (-> 60),
    # a minutes/duration field (or no descriptor) reads "1" as 1 minute (-> 1) — so it
    # round-trips to what the writer stores instead of becoming 0.02h.
    if re.fullmatch(r"\d+", s):
        n = int(s)
        return n * 60 if _estimate_unit_is_hours(entry) else n
    if re.fullmatch(r"\d+\.\d+", s):
        return int(round(float(s) * 60))

    raise ValueError(
        "cannot parse Estimate '%s' — expected minutes (90), decimal hours (1.5 / 1.5h), "
        "hh:mm (01:30), or 1h 30m" % value)


# Pure: convert canonical minutes to the value to WRITE for a NUMBER Estimate field.
# Asana number fields carry no intrinsic unit, so the unit is inferred from the field
# descriptor (adaptive-by-name policy):
#   - format == "duration" (paid time field) -> integer minutes (Asana time convention)
#   - name contains "hour"/"hr"              -> decimal hours (minutes/60, at precision)
#   - name contains "min"                    -> integer minutes
#   - otherwise (e.g. "Estimated time")      -> integer minutes  (original default)
# enum Estimate fields (hh:mm option names) never reach here — they are matched to an
# option GID by the enum branch. No network — unit-testable.
def estimate_number_value(minutes, entry):
    if _estimate_unit_is_hours(entry):
        precision = entry.get("precision") if isinstance(entry, dict) else None
        p = precision if isinstance(precision, int) and precision >= 0 else 2
        hours = round(minutes / 60.0, p)
        return int(hours) if p == 0 else hours
    return int(round(minutes))


# opt_fields for `task get` (per ../references/rest.md → Fetch Task Details), kept
# to the small set the compact projection needs.
TASK_GET_OPT_FIELDS = (
    "name,notes,completed,"
    "assignee.name,"
    "custom_fields.name,custom_fields.display_value,custom_fields.type,"
    "custom_fields.resource_subtype,"
    "custom_fields.enum_value.name,"
    "memberships.project.name,memberships.section.name"
)


# Pure projection: raw Asana task dict (the `data` object of GET /tasks/<gid>) ->
# the compact neutral shape. No network — unit-testable on a mock payload.
#
# - ref         : the task gid
# - name        : task name
# - description : the task notes
# - assignee    : assignee.name, or None
# - status      : the Product Status custom field's value (display_value or enum
#                 name), or None when the project has no such field
# - task_id     : the human-readable task key, surfaced from the auto-managed
#                 custom_id field (detected by resource_subtype == "custom_id", NOT
#                 by name — names vary per project, e.g. PD268/MT251). Omitted when
#                 the task has no such field. Read-only; never added to `fields`.
# - board       : compact memberships [{project, section}]
# - fields      : custom fields whose name maps to a canonical name, as
#                 {<CanonicalName>: <value>} (display_value, falling back to the
#                 enum option name). Product Status is also surfaced here.
def project_task(raw):
    if not isinstance(raw, dict):
        raw = {}

    def cf_value(cf):
        if not isinstance(cf, dict):
            return None
        dv = cf.get("display_value")
        if isinstance(dv, str) and dv:
            return dv
        ev = cf.get("enum_value")
        if isinstance(ev, dict):
            name = ev.get("name")
            if isinstance(name, str) and name:
                return name
        return dv

    assignee = None
    a = raw.get("assignee")
    if isinstance(a, dict):
        assignee = a.get("name")

    board = []
    memberships = raw.get("memberships")
    if isinstance(memberships, list):
        for m in memberships:
            if not isinstance(m, dict):
                continue
            proj = m.get("project")
            sect = m.get("section")
            board.append({
                "project": proj.get("name") if isinstance(proj, dict) else None,
                "section": sect.get("name") if isinstance(sect, dict) else None,
            })

    fields = {}
    status = None
    task_id = None
    custom_fields = raw.get("custom_fields")
    if isinstance(custom_fields, list):
        for cf in custom_fields:
            if not isinstance(cf, dict):
                continue
            # The human task key lives in the auto-managed custom_id field, whose
            # NAME varies per project — detect it by resource_subtype and surface its
            # display_value as a top-level read-only task_id (NOT a canonical field).
            if cf.get("resource_subtype") == "custom_id":
                if task_id is None:
                    dv = cf.get("display_value")
                    if isinstance(dv, str) and dv:
                        task_id = dv
                continue
            canonical = match_canonical(cf.get("name"))
            if canonical is None or canonical in fields:
                continue
            value = cf_value(cf)
            fields[canonical] = value
            if canonical == "Product Status":
                status = value

    # Fallback key detection: many projects store the key in a plain TEXT custom
    # field (e.g. a field named "PD268" holding "PD268-72") rather than an
    # auto-managed custom_id field. If no custom_id surfaced a task_id, scan for a
    # text field whose value matches the XXX-123 key shape. Read-only either way.
    if task_id is None and isinstance(custom_fields, list):
        for cf in custom_fields:
            if not isinstance(cf, dict):
                continue
            dv = cf.get("display_value")
            if isinstance(dv, str) and TASK_ID_RE.match(dv.strip()):
                task_id = dv.strip()
                break

    out = {
        "ref": raw.get("gid"),
        "name": raw.get("name"),
        "description": raw.get("notes"),
        "assignee": assignee,
        "status": status,
        "board": board,
        "fields": fields,
    }
    if task_id is not None:
        out["task_id"] = task_id
    return out


# Fetch a task and print the compact neutral projection (NOT the raw blob).
# <task-ref> is a task GID. Network read; exits 1 on transport/API failure.
def task_get(args):
    if not args:
        die(1, "usage: %s task get <task-ref>" % PROG)
    task_gid = args[0]
    key = cache_util.project_key()
    token = resolve_token(key)
    url = "%s/tasks/%s?opt_fields=%s" % (API_BASE, task_gid, TASK_GET_OPT_FIELDS)
    payload = api_get(url, token)
    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        die(1, "%s: task get: Asana response had no task data" % PROG)
    sys.stdout.write(json.dumps(project_task(raw), indent=2) + "\n")
    sys.exit(0)


# Create a task and add it to a board/project. <project-ref> is an Asana project
# GID (the board to add the task to). Workspace comes from the board cache; a
# missing workspace_gid is a bootstrap condition (exit 4). Two API calls: POST
# /tasks (name/notes/workspace/assignee — NO custom fields; Asana rejects them
# before the task belongs to a project), then POST /tasks/<gid>/addProject. Prints
# the SAME compact projection as `task get` (re-fetched after addProject so the
# board membership is reflected), not the raw Asana blob.
def task_create(args):
    if not args:
        die(1, "usage: %s task create <project-ref> --title T [--description D] [--assignee A] [--set Name=Value ...] [--wait-key]" % PROG)
    project_ref = args[0]
    opts = args[1:]
    title = None
    description = None
    assignee = None
    set_pairs = []
    wait_key = False
    i = 0
    while i < len(opts):
        flag = opts[i]
        if flag == "--wait-key":
            wait_key = True
            i += 1
            continue
        if flag in ("--title", "--description", "--assignee", "--set"):
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
                set_pairs.append(value)  # "Name=Value", parsed after the task exists
            i += 2
        else:
            die(1, "%s: task create: unknown argument '%s'" % (PROG, flag))
    if not title:
        die(1, "%s: task create requires --title" % PROG)

    key = cache_util.project_key()
    wgid = workspace_gid_from(key)
    if not wgid:
        die(4, "%s: task create requires a cached workspace_gid — run bootstrap first (board write <key> <json> / board discover <key>)" % PROG)
    token = resolve_token(key)

    data = {"name": title, "workspace": wgid}
    if description is not None:
        data["notes"] = description
    if assignee is not None:
        data["assignee"] = assignee
    created = api_json("%s/tasks" % API_BASE, token, "POST", {"data": data})
    task = created.get("data") if isinstance(created, dict) else None
    gid = task.get("gid") if isinstance(task, dict) else None
    if not gid:
        die(1, "%s: task create: Asana response had no task gid" % PROG)

    # custom fields are rejected before the task belongs to a project, so add it first,
    # then apply any --set fields in ONE batched PUT.
    api_json("%s/tasks/%s/addProject" % (API_BASE, gid), token, "POST", {"data": {"project": project_ref}})
    if set_pairs:
        fdata, skipped = build_field_writes(key, token, [project_ref], parse_field_pairs(set_pairs))
        if skipped:
            err("%s: task create: skipped fields not on the project: %s" % (PROG, ", ".join(skipped)))
        if fdata:
            api_json("%s/tasks/%s" % (API_BASE, gid), token, "PUT", {"data": fdata})

    # The human key is assigned by an async Asana Rule (~0.5s). By default we do NOT
    # wait — the key is resolved lazily by whoever needs it (e.g. create-pr re-fetches
    # at PR time, by which point it is set). Pass --wait-key only for a tight
    # create-then-immediately-name-branch flow that needs it in the same breath.
    url = "%s/tasks/%s?opt_fields=%s" % (API_BASE, gid, TASK_GET_OPT_FIELDS)
    attempts = TASK_ID_POLL_ATTEMPTS if wait_key else 1
    proj = project_task(task)
    for attempt in range(attempts):
        payload = api_get(url, token)
        raw = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(raw, dict):
            proj = project_task(raw)
        if not wait_key or proj.get("task_id"):
            break
        if attempt < attempts - 1:
            time.sleep(TASK_ID_POLL_INTERVAL)
    sys.stdout.write(json.dumps(proj, indent=2) + "\n")
    sys.exit(0)


# Resolve a task's project GIDs from its memberships (so set-field can find the
# project that defines a custom field). Returns a list of project GIDs.
def task_project_gids(task_gid, token):
    url = "%s/tasks/%s?opt_fields=projects,projects.gid" % (API_BASE, task_gid)
    payload = api_get(url, token)
    data = payload.get("data") if isinstance(payload, dict) else None
    out = []
    if isinstance(data, dict):
        projects = data.get("projects")
        if isinstance(projects, list):
            for p in projects:
                if isinstance(p, dict) and p.get("gid"):
                    out.append(p.get("gid"))
    return out


# Print a task-returning write response as the same compact projection as `task get`
# (NOT the raw ~12.5k-char Asana blob) so write confirmations stay token-cheap.
def print_task_projection(api_response):
    data = api_response.get("data") if isinstance(api_response, dict) else None
    sys.stdout.write(json.dumps(project_task(data if isinstance(data, dict) else {}), indent=2) + "\n")


# Resolve ONE canonical field write against a task's projects. Returns a tuple:
#   ("assignee", <value>)            -> native assignee (PUT /tasks {assignee})
#   ("custom_field", <gid>, <value>) -> custom_fields:{<gid>:<value>}
#   None                             -> field not on any of the projects (skip)
# Raises ValueError on an unparseable/unmatched value (caller surfaces it).
# Shared by `set-field` (single) and `set-fields`/`create --set` (batch) so all three
# apply identical enum-match / Estimate-unit / native-assignee logic.
def resolve_field_write(key, token, project_gids, name, value):
    if name == "Assignee":
        return ("assignee", value)
    entry = None
    for pgid in project_gids:
        entry = _resolve_field_entry(key, pgid, name)
        if entry is not None:
            break
    if entry is None:
        return None
    field_gid = entry.get("id")
    ftype = entry.get("type")
    if not field_gid:
        return None
    if ftype == "enum":
        for opt in entry.get("enum_options") or []:
            if not isinstance(opt, dict):
                continue
            if value == opt.get("id") or (
                isinstance(opt.get("name"), str) and value.lower() == opt.get("name").lower()
            ):
                return ("custom_field", field_gid, opt.get("id"))
        raise ValueError("value '%s' does not match any enum option for '%s'" % (value, name))
    if name == "Estimate":
        return ("custom_field", field_gid, estimate_number_value(parse_estimate_to_minutes(value, entry), entry))
    return ("custom_field", field_gid, value)


# Build a single PUT body that applies many field writes at once. Returns
# (data, skipped) where data is {assignee?, custom_fields?} and skipped is the list
# of canonical names not present on the task's projects. Dies on a bad value.
def build_field_writes(key, token, project_gids, pairs):
    data = {}
    custom = {}
    skipped = []
    for name, value in pairs:
        try:
            r = resolve_field_write(key, token, project_gids, name, value)
        except ValueError as e:
            die(1, "%s: %s" % (PROG, e))
        if r is None:
            skipped.append(name)
        elif r[0] == "assignee":
            data["assignee"] = r[1]
        else:
            custom[r[1]] = r[2]
    if custom:
        data["custom_fields"] = custom
    return data, skipped


# Parse "Name=Value" CLI pairs (used by set-fields and create --set). Splits on the
# FIRST '=' so values may contain '='. Canonical names are single tokens.
def parse_field_pairs(items):
    pairs = []
    for it in items:
        if "=" not in it:
            die(1, "%s: expected Name=Value, got '%s'" % (PROG, it))
        name, value = it.split("=", 1)
        name = name.strip()
        if not name:
            die(1, "%s: empty field name in '%s'" % (PROG, it))
        pairs.append((name, value))
    return pairs


# Set a single field on an existing task. <task-ref> is a task GID. Resolves the
# canonical field via the `fields` logic (against the task's project) and writes via
# one PUT. Exit 2 (skip gracefully) when the field is not on any of the task's
# projects. Prints the updated task JSON on success.
def task_set_field(args):
    if len(args) < 3:
        die(1, "usage: %s task set-field <task-ref> <CanonicalName> <value>" % PROG)
    task_gid = args[0]
    name = args[1]
    value = args[2]
    key = cache_util.project_key()
    token = resolve_token(key)

    # Assignee is native — no per-project field resolution needed.
    if name == "Assignee":
        updated = api_json("%s/tasks/%s" % (API_BASE, task_gid), token, "PUT",
                           {"data": {"assignee": value}})
        print_task_projection(updated)
        sys.exit(0)

    project_gids = task_project_gids(task_gid, token)
    if not project_gids:
        die(1, "%s: task set-field: task %s belongs to no project — cannot resolve custom fields" % (PROG, task_gid))

    try:
        r = resolve_field_write(key, token, project_gids, name, value)
    except ValueError as e:
        die(1, "%s: task set-field: %s" % (PROG, e))
    if r is None:
        # Field not present on any of the task's projects — skip gracefully.
        sys.exit(2)

    data = {"assignee": r[1]} if r[0] == "assignee" else {"custom_fields": {r[1]: r[2]}}
    updated = api_json("%s/tasks/%s" % (API_BASE, task_gid), token, "PUT", {"data": data})
    print_task_projection(updated)
    sys.exit(0)


# Set MANY fields on an existing task in ONE PUT (fewer round-trips than repeated
# set-field). <task-ref> is a task GID; remaining args are Name=Value pairs. Fields
# not present on the task's projects are skipped (reported on stderr). Estimate-unit,
# enum-option, and native-assignee handling are identical to set-field. Prints the
# compact projection (from the write response) so the caller sees the stored result.
#   tm.py task set-fields <task-ref> Estimate=1h30m Priority=P2 Assignee=me
def task_set_fields(args):
    if len(args) < 2:
        die(1, "usage: %s task set-fields <task-ref> <Name=Value> [<Name=Value> ...]" % PROG)
    task_gid = args[0]
    pairs = parse_field_pairs(args[1:])
    key = cache_util.project_key()
    token = resolve_token(key)
    project_gids = task_project_gids(task_gid, token)
    if not project_gids:
        die(1, "%s: task set-fields: task %s belongs to no project — cannot resolve custom fields" % (PROG, task_gid))
    data, skipped = build_field_writes(key, token, project_gids, pairs)
    if skipped:
        err("%s: task set-fields: skipped fields not on the task's project(s): %s" % (PROG, ", ".join(skipped)))
    if data:
        # Project the PUT response directly — no extra GET round-trip.
        print_task_projection(api_json("%s/tasks/%s" % (API_BASE, task_gid), token, "PUT", {"data": data}))
    else:
        payload = api_get("%s/tasks/%s?opt_fields=%s" % (API_BASE, task_gid, TASK_GET_OPT_FIELDS), token)
        raw = payload.get("data") if isinstance(payload, dict) else None
        sys.stdout.write(json.dumps(project_task(raw if isinstance(raw, dict) else {}), indent=2) + "\n")
    sys.exit(0)


# Upload an attachment to a task. <task-ref> is a task GID. POST /attachments as
# multipart/form-data (parent=<gid>, file=@path) built with urllib — the sandbox-
# safe replacement for `curl -F`. Prints the attachment JSON on success.
def task_attach(args):
    if len(args) < 2:
        die(1, "usage: %s task attach <task-ref> <file-path>" % PROG)
    task_gid = args[0]
    file_path = args[1]
    if not os.path.isfile(file_path):
        die(1, "%s: task attach: file not found: %s" % (PROG, file_path))
    key = cache_util.project_key()
    token = resolve_token(key)
    result = api_multipart(
        "%s/attachments" % API_BASE,
        token,
        [("parent", task_gid)],
        ("file", file_path),
    )
    out = result.get("data") if isinstance(result, dict) else result
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    sys.exit(0)


# Mark a task as depending on (blocked by) another task. <task-ref> and
# <depends-on-ref> are task GIDs. POST /tasks/<gid>/addDependencies with the
# blocking task gid (per ../references/rest.md → Add Dependencies). Prints the
# response JSON on success.
def task_add_dependency(args):
    if len(args) < 2:
        die(1, "usage: %s task add-dependency <task-ref> <depends-on-ref>" % PROG)
    task_gid = args[0]
    depends_on = args[1]
    key = cache_util.project_key()
    token = resolve_token(key)
    result = api_json(
        "%s/tasks/%s/addDependencies" % (API_BASE, task_gid),
        token, "POST", {"data": {"dependencies": [depends_on]}})
    print_task_projection(result)
    sys.exit(0)


# Set a task's parent (place it under another task). <task-ref> and <parent-ref>
# are task GIDs. POST /tasks/<gid>/setParent (per ../references/rest.md → Set
# Parent). Prints the response JSON on success.
def task_set_parent(args):
    if len(args) < 2:
        die(1, "usage: %s task set-parent <task-ref> <parent-ref>" % PROG)
    task_gid = args[0]
    parent = args[1]
    key = cache_util.project_key()
    token = resolve_token(key)
    result = api_json(
        "%s/tasks/%s/setParent" % (API_BASE, task_gid),
        token, "POST", {"data": {"parent": parent}})
    print_task_projection(result)
    sys.exit(0)


# Add a task to a board/project. <task-ref> is a task GID; <board-ref> is a
# project GID. POST /tasks/<gid>/addProject (per ../references/rest.md → Create
# Task / addProject). Prints the response JSON on success.
def task_add_to_board(args):
    if len(args) < 2:
        die(1, "usage: %s task add-to-board <task-ref> <board-ref>" % PROG)
    task_gid = args[0]
    board = args[1]
    key = cache_util.project_key()
    token = resolve_token(key)
    result = api_json(
        "%s/tasks/%s/addProject" % (API_BASE, task_gid),
        token, "POST", {"data": {"project": board}})
    print_task_projection(result)
    sys.exit(0)


# Pure decision: given a status name, the Product Status field descriptor (the
# `fields` entry, or None) and a list of {gid,name} sections, decide HOW to realize
# the status. Returns one of:
#   ("field",   <option-gid>)   -> PUT custom_fields:{<field-gid>:<option-gid>}
#   ("section", <section-gid>)  -> POST /sections/<gid>/addTask
#   ("none",    None)           -> status matches neither (caller errors)
# Product Status (custom field) is tried FIRST, then a board section — per
# ../../../references/workflow/lifecycle.md (two-axis status model). No network —
# unit-testable on a mock field descriptor + mock sections list.
def decide_set_status(status_name, ps_field, sections):
    if isinstance(ps_field, dict) and ps_field.get("type") == "enum":
        for opt in ps_field.get("enum_options") or []:
            if not isinstance(opt, dict):
                continue
            oname = opt.get("name")
            if status_name == opt.get("id") or (
                isinstance(oname, str) and status_name.lower() == oname.lower()
            ):
                return ("field", opt.get("id"))
    if isinstance(sections, list):
        for sect in sections:
            if not isinstance(sect, dict):
                continue
            sname = sect.get("name")
            if isinstance(sname, str) and status_name.lower() == sname.lower():
                return ("section", sect.get("gid"))
    return ("none", None)


# Fetch a project's board sections as a list of {gid,name}.
def fetch_project_sections(project_gid, token):
    url = "%s/projects/%s/sections?opt_fields=name" % (API_BASE, project_gid)
    payload = api_get(url, token)
    data = payload.get("data") if isinstance(payload, dict) else None
    out = []
    if isinstance(data, list):
        for s in data:
            if isinstance(s, dict):
                out.append({"gid": s.get("gid"), "name": s.get("name")})
    return out


# Set a task's status (two-axis, per ../../../references/workflow/lifecycle.md).
# <task-ref> is a task GID; <status-name> is a neutral lifecycle name. Order:
# (1) Product Status custom field — resolve via the `fields` logic against the
#     task's project(s); if <status-name> matches an enum option, PUT the option.
# (2) Board section move — discover the task's project sections; if <status-name>
#     matches a section name, POST /sections/<gid>/addTask.
# Matches neither -> exit 1 (status is not a known Product Status option or
# section). Prints the realization {axis, ...} on success.
def task_set_status(args):
    if len(args) < 2:
        die(1, "usage: %s task set-status <task-ref> <status-name>" % PROG)
    task_gid = args[0]
    status_name = args[1]
    key = cache_util.project_key()
    token = resolve_token(key)

    project_gids = task_project_gids(task_gid, token)
    if not project_gids:
        die(1, "%s: task set-status: task %s belongs to no project — cannot resolve status" % (PROG, task_gid))

    # Axis 1: Product Status custom field — try each of the task's projects.
    for pgid in project_gids:
        ps_field = _resolve_field_entry(key, pgid, "Product Status")
        axis, target = decide_set_status(status_name, ps_field, [])
        if axis == "field" and target:
            field_gid = ps_field.get("id")
            updated = api_json("%s/tasks/%s" % (API_BASE, task_gid), token, "PUT",
                               {"data": {"custom_fields": {field_gid: target}}})
            out = updated.get("data") if isinstance(updated, dict) else updated
            sys.stdout.write(json.dumps({"axis": "field", "field": "Product Status",
                                         "option": target, "task": out.get("gid") if isinstance(out, dict) else None}, indent=2) + "\n")
            sys.exit(0)

    # Axis 2: board section move — try each of the task's projects.
    for pgid in project_gids:
        sections = fetch_project_sections(pgid, token)
        axis, target = decide_set_status(status_name, None, sections)
        if axis == "section" and target:
            api_json("%s/sections/%s/addTask" % (API_BASE, target), token, "POST",
                     {"data": {"task": task_gid}})
            sys.stdout.write(json.dumps({"axis": "section", "section": target,
                                         "task": task_gid}, indent=2) + "\n")
            sys.exit(0)

    die(1, "%s: task set-status: '%s' is not a known Product Status option or board section on task %s's project(s)" % (PROG, status_name, task_gid))


# Set (replace) a task's description/notes. <task-ref> is a task GID; the body is
# authored as Markdown (positional arg or --body-file), converted to Asana HTML the
# same way comments are (md_to_html → render_body), and PUT to the task's html_notes
# (rich) or notes (plain). Mirrors `comment add`. Prints the compact projection.
def task_set_notes(args):
    if not args:
        die(1, "usage: %s task set-notes <task-ref> (<body> | --body-file <path>)" % PROG)
    task_gid = args[0]
    rest = args[1:]
    body = None
    if rest and rest[0] == "--body-file":
        if len(rest) < 2:
            die(1, "%s: task set-notes: --body-file requires a path" % PROG)
        path = rest[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception as e:
            die(1, "%s: task set-notes: cannot read --body-file '%s' (%s)" % (PROG, path, e))
    elif rest:
        body = rest[0]
    if body is None:
        die(1, "%s: task set-notes requires a body (<body> or --body-file <path>)" % PROG)
    if not re.fullmatch(r"[0-9]+", task_gid):
        die(1, "%s: task set-notes: task-ref must be numeric (got '%s')" % (PROG, task_gid))
    if not body.strip():
        die(1, "%s: task set-notes: body is empty (refusing to blank the description)" % PROG)

    is_html, wrapped = render_body(md_to_html(body))
    field = "html_notes" if is_html else "notes"
    key = cache_util.project_key()
    token = resolve_token(key)
    updated = api_json("%s/tasks/%s" % (API_BASE, task_gid), token, "PUT", {"data": {field: wrapped}})
    print_task_projection(updated)
    sys.exit(0)


# --- comment family ---------------------------------------------------------

# Matches any HTML tag from the set Asana rich text understands (plus structural
# tags). Used to decide whether a body is already HTML (-> html_text) or plain
# text (-> text).
HTML_TAG_PATTERN = re.compile(
    r"<\s*/?\s*("
    r"body|strong|em|u|s|code|a|ul|ol|li|br|p|div|span|b|i|"
    r"h[1-6]|html|head|table|tr|td|th|tbody|thead|img|pre"
    r")(\s[^>]*)?/?\s*>",
    re.IGNORECASE,
)
# Asana does NOT support <br> in rich text — it silently rejects the html_text and
# stores raw content as plain text. Replace any <br>/<br/>/<br /> with a newline.
BR_PATTERN = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
# Collapse runs of 3+ blank lines down to one blank line.
NEWLINE_RUN_PATTERN = re.compile(r"(?:[ \t]*\n[ \t]*){3,}")

# Inline Markdown -> Asana HTML conversions, applied in order. Done before block
# handling. Links first so their bracket/paren syntax is not eaten by emphasis.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_MD_ITALIC_AST_RE = re.compile(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)")
_MD_ITALIC_US_RE = re.compile(r"(?<![_\w])_([^_\n]+)_(?![_\w])")

# Asana only renders explicit <a href> anchors in rich text — bare URLs stay plain
# (not clickable). Auto-linkify bare http(s) URLs, but leave URLs already inside an
# <a> (from a Markdown link) or a <code> span untouched: split on those spans and
# only transform the text outside them. Trailing sentence punctuation is kept out of
# the href.
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_PROTECTED_SPAN_RE = re.compile(r"(<a\b[^>]*>.*?</a>|<code>.*?</code>)", re.IGNORECASE | re.DOTALL)


def _linkify_url(m):
    url = m.group(0)
    trail = ""
    while url and url[-1] in ").,;:!?":
        trail = url[-1] + trail
        url = url[:-1]
    if not url:
        return m.group(0)
    return '<a href="%s">%s</a>%s' % (url, url, trail)


def _linkify_bare_urls(text):
    parts = _PROTECTED_SPAN_RE.split(text)
    for i in range(0, len(parts), 2):  # even indices are outside protected spans
        parts[i] = _BARE_URL_RE.sub(_linkify_url, parts[i])
    return "".join(parts)


def _md_inline(text):
    text = _MD_LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = _MD_BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _MD_CODE_RE.sub(r"<code>\1</code>", text)
    text = _MD_ITALIC_AST_RE.sub(r"<em>\1</em>", text)
    text = _MD_ITALIC_US_RE.sub(r"<em>\1</em>", text)
    text = _linkify_bare_urls(text)
    return text


# Convert a Markdown body to Asana-compatible HTML. Handles headings, bullet and
# numbered lists, and inline emphasis/code/links. List runs are wrapped in <ul>/
# <ol>; consecutive list items of the same kind join into one list. Line breaks
# are emitted as literal "\n" (NOT <br>), per Asana rich-text rules. Blank source
# lines are DROPPED from the output — Asana renders a bare "\n" as a visible vertical
# gap after headings/between blocks, and block tags (<h*>/<ul>/<ol>/<li>) don't need
# blank-line separation. The result is fed to build_payload, which wraps it in <body>.
def md_to_html(body):
    lines = body.split("\n")
    out = []
    list_kind = None  # None | "ul" | "ol"

    def close_list():
        nonlocal list_kind
        if list_kind is not None:
            out.append("</%s>" % list_kind)
            list_kind = None

    for line in lines:
        stripped = line.strip()
        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if h:
            close_list()
            level = len(h.group(1))
            out.append("<h%d>%s</h%d>" % (level, _md_inline(h.group(2)), level))
        elif bullet:
            if list_kind != "ul":
                close_list()
                out.append("<ul>")
                list_kind = "ul"
            out.append("<li>%s</li>" % _md_inline(bullet.group(1)))
        elif numbered:
            if list_kind != "ol":
                close_list()
                out.append("<ol>")
                list_kind = "ol"
            out.append("<li>%s</li>" % _md_inline(numbered.group(1)))
        else:
            close_list()
            out.append(_md_inline(line))
    close_list()
    # Drop blank/whitespace-only lines so Asana doesn't render them as gaps.
    return "\n".join(x for x in out if x.strip())


# Decide whether a body is rich HTML or plain, and normalize it. If it contains HTML
# tags: replace <br> with "\n" (Asana rejects <br>), collapse blank-line runs, and wrap
# in <body>…</body> when not already. Returns (is_html, normalized_body). Shared by the
# comment path (html_text/text) and the notes path (html_notes/notes).
def render_body(body):
    if HTML_TAG_PATTERN.search(body):
        body = BR_PATTERN.sub("\n", body)
        body = NEWLINE_RUN_PATTERN.sub("\n\n", body)
        stripped = body.strip()
        if not (stripped.startswith("<body>") and stripped.endswith("</body>")):
            body = "<body>%s</body>" % body
        return True, body
    return False, body


# Build the comment/story request payload. Returns (mode, payload) where mode in
# {"text","html_text"}.
def build_payload(body):
    is_html, body = render_body(body)
    field = "html_text" if is_html else "text"
    return field, {"data": {field: body}}


# Post a comment (story) to a task. <task-ref> is a task GID. The body is authored
# as Markdown (via positional arg or --body-file), converted to Asana HTML, routed
# through text vs html_text, and POSTed to /tasks/<gid>/stories. Prints the created
# story JSON on success.
def comment_add(args):
    if not args:
        die(1, "usage: %s comment add <task-ref> (<body> | --body-file <path>)" % PROG)
    task_gid = args[0]
    rest = args[1:]
    body = None
    if rest and rest[0] == "--body-file":
        if len(rest) < 2:
            die(1, "%s: comment add: --body-file requires a path" % PROG)
        path = rest[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception as e:
            die(1, "%s: comment add: cannot read --body-file '%s' (%s)" % (PROG, path, e))
    elif rest:
        body = rest[0]
    if body is None:
        die(1, "%s: comment add requires a body (<body> or --body-file <path>)" % PROG)
    if not re.fullmatch(r"[0-9]+", task_gid):
        die(1, "%s: comment add: task-ref must be numeric (got '%s')" % (PROG, task_gid))
    if not body:
        die(1, "%s: comment add: body is empty" % PROG)

    html = md_to_html(body)
    mode, payload = build_payload(html)

    key = cache_util.project_key()
    token = resolve_token(key)
    result = api_json("%s/tasks/%s/stories" % (API_BASE, task_gid), token, "POST", payload)
    out = result.get("data") if isinstance(result, dict) else result
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    sys.exit(0)


# List a task's human comments. <task-ref> is a task GID. GETs the task's stories,
# filters to type=="comment", and prints a compact [{author, text, created_at}].
def comment_list(args):
    if not args:
        die(1, "usage: %s comment list <task-ref>" % PROG)
    task_gid = args[0]
    if not re.fullmatch(r"[0-9]+", task_gid):
        die(1, "%s: comment list: task-ref must be numeric (got '%s')" % (PROG, task_gid))
    key = cache_util.project_key()
    token = resolve_token(key)
    url = ("%s/tasks/%s/stories?opt_fields=type,text,created_by.name,created_at"
           % (API_BASE, task_gid))
    payload = api_get(url, token)
    data = payload.get("data") if isinstance(payload, dict) else None
    out = []
    if isinstance(data, list):
        for s in data:
            if not isinstance(s, dict) or s.get("type") != "comment":
                continue
            cb = s.get("created_by")
            author = cb.get("name") if isinstance(cb, dict) else None
            out.append({
                "author": author,
                "text": s.get("text"),
                "created_at": s.get("created_at"),
            })
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    sys.exit(0)


# --- ref family -------------------------------------------------------------

# An app.asana.com host (with or without a leading scheme). The task GID is always a
# numeric segment; the position depends on the URL form (see ../references/rest.md).
_ASANA_HOST_RE = re.compile(r"^https?://app\.asana\.com/", re.IGNORECASE)
# /1/<org>/.../task/<task-gid>   and   /1/<org>/.../item/<task-gid>
_ASANA_TASK_SEG_RE = re.compile(r"/(?:task|item)/(\d+)")
# /0/<project-gid>/<task-gid>[/...]  — task GID is the 2nd numeric path segment.
_ASANA_ZERO_RE = re.compile(r"^/0/\d+/(\d+)")


# Extract the canonical Asana task GID from an input, or None if the input is not
# recognizable as an Asana task reference. A bare run of digits is accepted as a GID.
# An app.asana.com URL is parsed per the documented URL forms (the `/1/.../task/` and
# `/1/.../item/` forms, then the `/0/<project>/<task>` form). Anything else (other
# hosts, Jira keys, garbage) returns None.
def asana_extract_ref(raw):
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Bare numeric id.
    if re.fullmatch(r"\d+", s):
        return s
    # Only app.asana.com URLs are ours; any other URL/host is not.
    if not _ASANA_HOST_RE.search(s):
        return None
    import urllib.parse
    path = urllib.parse.urlparse(s).path
    m = _ASANA_TASK_SEG_RE.search(path)
    if m:
        return m.group(1)
    m = _ASANA_ZERO_RE.search(path)
    if m:
        return m.group(1)
    return None


# `ref parse <url-or-ref>`: print the canonical Asana task GID and exit 0 if the input
# is an Asana task reference; exit 2 (no output) if it is not this provider's.
def ref_parse(args):
    if not args:
        die(1, "usage: %s ref parse <url-or-ref>" % PROG)
    gid = asana_extract_ref(args[0])
    if gid is None:
        sys.exit(2)
    sys.stdout.write(gid + "\n")
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
    "set-fields": task_set_fields,
    "set-notes": task_set_notes,
    "attach": task_attach,
    "add-dependency": task_add_dependency,
    "set-parent": task_set_parent,
    "add-to-board": task_add_to_board,
    "set-status": task_set_status,
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
