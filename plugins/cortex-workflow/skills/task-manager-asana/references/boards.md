# Board Resolution

> The neutral sprint/backlog concept and active-sprint policy live in `../../../references/workflow/boards.md`. This file is the Asana-specific identification, discovery, and caching of those boards.

Asana board classification, cache management, and discovery.

## Board Classification

Every non-archived Asana project is classified by its name against two **lists of
regex patterns** (so multiple naming conventions are supported, not just one):

- **Sprint board**: name matches ANY `sprint_patterns` entry.
- **Backlog board**: name matches ANY `backlog_patterns` entry AND no sprint pattern
  (so a sprint board never also lands in the backlog).
- **Ignored**: everything else (e.g. `Product Backlog`, personal projects).

Archived projects are excluded from both (the discovery query passes `archived=false`
and the selectors defensively skip `archived == true`).

**Default patterns** (code defaults in `../scripts/tm.py`):

| | defaults |
|---|---|
| `sprint_patterns` | `^ENG \| Sprint \d+\.\d+` (e.g. `ENG \| Sprint 26.16`) · `^Sprint\b` (e.g. `Sprint Board 26/13`) |
| `backlog_patterns` | `^ENG \| ` (e.g. `ENG \| Bugs & Issues`) · `^PD\d+-\d+` (e.g. `PD26-8 :: Android app`) |

A workspace with a different naming scheme **overrides** these per-project via optional
`sprint_patterns` / `backlog_patterns` arrays in the cache file (see Cache Schema
below) — they replace the defaults for that project. Prefer adding config over widening
the defaults.

**Sprint liveness:** among non-archived, `completed == false` sprint matches —
1. If any candidate has a `due_on` (the `ENG | ` convention sets due dates): keep only
   `due_on >= today`, and the latest `due_on` wins (else no active sprint).
2. If **none** carry a `due_on` (e.g. `Sprint Board <YY>/<NN>` boards, which don't set
   due dates): pick the **highest sprint number by natural-sorted name** (so `26/13`
   beats `26/2`).

## Cache File

> **The cache lifecycle is enforced by `../scripts/tm.py` (the `board` family)** — `board read`/`board resolve`/`board refresh`/`board discover`/`board write` all go through it (cache-first, never manual discovery on a hit). This file documents the schema + rules the script implements; the script is the single code path the provider calls.

### Location

`~/.cortex/cortex-workflow/<project-key>.json` — NOT in the repo, NOT committed.

### Project Key Derivation

```bash
# Prefer git remote URL for stable, unique identity
git remote get-url origin 2>/dev/null \
  | sed 's|[^a-zA-Z0-9]|-|g' \
  | sed 's|-\{2,\}|-|g' \
  | tr '[:upper:]' '[:lower:]'
# Fallback if no remote:
basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
```

### Schema

```json
{
  "workspace_gid": "111111111",
  "asana_token_env": "ASANA_PERSONAL_ACCESS_TOKEN",
  "cached_at": "2026-04-16T10:00:00Z",
  "active_sprint": {
    "gid": "9999999",
    "name": "ENG | Sprint 26.16",
    "due_on": "2026-04-27"
  },
  "backlog_boards": [
    {"gid": "1111111", "name": "ENG | MT251 :: Mobile Toolkit"},
    {"gid": "2222222", "name": "ENG | BI :: Business Intelligence"},
    {"gid": "3333333", "name": "ENG | Bugs & Issues"}
  ]
}
```

### Fields

| Field | Description |
|---|---|
| `workspace_gid` | Asana workspace GID — discovered on first use |
| `asana_token_env` | Name of the env var holding the Asana token for this project. Default: `ASANA_PERSONAL_ACCESS_TOKEN`. On first use, if this var is set, cache the name automatically. If not set, ask the user which env var holds the token. |
| `cached_at` | ISO 8601 timestamp of last full cache write |
| `active_sprint` | The currently active sprint board (`due_on` may be `null` for conventions that don't set sprint due dates) |
| `backlog_boards` | All non-sprint projects in the workspace matching a backlog pattern |
| `sprint_patterns` | *(optional)* array of regex strings overriding the default sprint patterns for this project |
| `backlog_patterns` | *(optional)* array of regex strings overriding the default backlog patterns for this project |

> `sprint_patterns` / `backlog_patterns` are **preserved across re-discovery** — `board discover` carries them forward into the rewritten cache.

## Cache Refresh Triggers

### 1. Sprint Auto-Refresh

Before any operation that needs the sprint board, check if `active_sprint.due_on` is in the past. (A `null` `due_on` — conventions without sprint due dates — is treated as fresh; refresh those manually when the sprint advances.) If past:

1. Query workspace projects (see API Calls below)
2. Classify sprint boards using the pattern lists (Board Classification)
3. Find the active sprint (sprint liveness rules above)
4. Update `active_sprint` in cache and write the file
5. Report: `Sprint board refreshed: <new> (was: <old>)`

### 2. Full Discovery (First Use)

If no cache file exists for the current project key:

1. Resolve workspace GID (see Workspace GID Bootstrapping)
2. Resolve token env var (see Token Env Var)
3. Query all workspace projects
4. Classify each project — sprint boards and backlog boards
5. Find the active sprint
6. Write the full cache file
7. Report what was discovered

### 3. Manual Refresh

User passes a URL override or says "refresh boards". Re-run the full discovery flow and overwrite the cache.

### 4. Backlog Staleness

No automatic expiry for backlog boards — they change rarely. Manual refresh covers the case of a new board being created.

## Workspace GID Bootstrapping

On first use with no cache:

```
GET /users/me?opt_fields=workspaces,workspaces.gid,workspaces.name
```

Route via the recipes in `references/rest.md` (Fetch Current User).

- If one workspace → use it, cache the GID
- If multiple → ask the user which one, cache the choice

## Token Env Var

The `asana_token_env` field stores the name of the environment variable holding the Asana token for this project.

On first use:
- If `$ASANA_PERSONAL_ACCESS_TOKEN` is set → cache `"ASANA_PERSONAL_ACCESS_TOKEN"` as the env var name
- If not set → ask the user which env var holds the token, cache the answer

Subsequent operations read the token from the cached env var name. Token resolution is handled per `references/rest.md` (Token Resolution) — this field is a project-level hint that can inform token selection.

## API Calls for Discovery

All use the recipes in `references/rest.md`.

**List all workspace projects:**
```
GET /workspaces/<workspace_gid>/projects?opt_fields=name,completed,due_on,archived&archived=false&limit=100
```

Paginate if `next_page` is present in the response. `archived=false` excludes archived projects; classify each remaining project using the Board Classification rules above (don't pre-filter by a single prefix — the pattern lists decide).

## Loading the Cache

Every skill that needs board information follows this sequence:

1. Derive the project key
2. Read `~/.cortex/cortex-workflow/<project-key>.json`
3. If file missing → run Full Discovery
4. If file exists → check sprint freshness (`active_sprint.due_on < today`?)
   - If stale → run Sprint Auto-Refresh
   - If fresh → use cached data
5. Return the loaded cache object for use by the calling skill
