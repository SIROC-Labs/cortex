# Board Resolution

Shared reference for board classification, cache management, and discovery. All skills that need board information reference this file.

## Board Classification

Every Asana project is classified by its name:

- **Sprint board**: name matches the regex `ENG \| Sprint \d+\.\d+`
- **Backlog board**: name starts with `ENG | ` but does not match the sprint pattern
- **Ignored**: everything else (personal projects, non-ENG projects)

**Sprint liveness:** A sprint board is "active" when:
1. `completed == false`
2. `due_on >= today`

If multiple sprints pass both checks, pick the one with the latest `due_on`.

## Cache File

### Location

`~/.cortex/asana-workflow/<project-key>.json` — NOT in the repo, NOT committed.

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
| `active_sprint` | The currently active sprint board (not completed, due date in future) |
| `backlog_boards` | All non-sprint `ENG | ` prefixed projects in the workspace |

## Cache Refresh Triggers

### 1. Sprint Auto-Refresh

Before any operation that needs the sprint board, check if `active_sprint.due_on` is in the past. If so:

1. Query workspace projects (see API Calls below)
2. Filter to sprint boards using the classification regex
3. Find the active sprint (not completed, `due_on >= today`, latest `due_on` wins)
4. Update `active_sprint` in cache and write the file
5. Report: `Sprint board refreshed: ENG | Sprint 26.18 (was: ENG | Sprint 26.16)`

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

Route through `asana-api` skill.

- If one workspace → use it, cache the GID
- If multiple → ask the user which one, cache the choice

## Token Env Var

The `asana_token_env` field stores the name of the environment variable holding the Asana token for this project.

On first use:
- If `$ASANA_PERSONAL_ACCESS_TOKEN` is set → cache `"ASANA_PERSONAL_ACCESS_TOKEN"` as the env var name
- If not set → ask the user which env var holds the token, cache the answer

Subsequent operations read the token from the cached env var name. The `asana-api` skill handles actual token resolution — this field is a project-level hint that can inform token selection.

## API Calls for Discovery

All routed through the `asana-api` skill.

**List all workspace projects:**
```
GET /workspaces/<workspace_gid>/projects?opt_fields=name,completed,due_on&limit=100
```

Paginate if `next_page` is present in the response. Filter results to projects whose name starts with `ENG | `, then classify each using the Board Classification rules above.

## Loading the Cache

Every skill that needs board information follows this sequence:

1. Derive the project key
2. Read `~/.cortex/asana-workflow/<project-key>.json`
3. If file missing → run Full Discovery
4. If file exists → check sprint freshness (`active_sprint.due_on < today`?)
   - If stale → run Sprint Auto-Refresh
   - If fresh → use cached data
5. Return the loaded cache object for use by the calling skill
