# Board Config Reference

## Loading Board Configuration

Board discovery, caching, and refresh are handled by the shared module. Read `references/board-resolution.md` (at the plugin root: `plugins/asana-workflow/references/board-resolution.md`) for:

- Cache file location and schema
- Project key derivation
- Sprint auto-refresh logic
- Full discovery flow for first use
- Workspace GID bootstrapping

Load the cache at the start of Step 2. If the cache doesn't exist, the shared module's Full Discovery flow handles first-time setup (including asking for workspace and token env var).

## Applying URL Overrides (from Step 0)

After loading the cache, merge any URL overrides parsed in Step 0:

- If `sprint_override` is set → update `active_sprint` with the resolved GID and name
- If `backlog_override` is set → add to `backlog_boards` if not already present (match by GID)
- If `workspace_override` is set and cache has no `workspace_gid` → set it

If any override was applied, save the updated cache and report:
```
Sprint board updated: ENG | Sprint 27.x  (was: ENG | Sprint 26.x)
Config saved to ~/.cortex/asana-workflow/<project-key>.json
```

## Resolve a Project URL to Name + Workspace GID

Given a URL `app.asana.com/0/<gid>/...`, extract the GID with `app.asana.com/0/(\d+)`, then fetch via `asana-api`:

```
GET /projects/<gid>?opt_fields=name,workspace.gid
```

Use the returned `name` and `workspace.gid`. Never ask the user for raw GIDs or workspace GIDs — always derive them from the URL.

## Smart Board Suggestion

When `log-task` creates a task, suggest which backlog board(s) to add it to.

### Scoring

Load all `backlog_boards` from cache. Score each by relevance to the task:

1. **Category match** — if the task is a bug, boost boards whose name contains "Bug" or "Issue" (case-insensitive)
2. **Feature keyword match** — extract keywords from the task title and description, match against the feature name portion of `ENG | {prefix} :: {name}` boards. Tokenize both sides (split on spaces, hyphens, underscores) and count overlapping tokens.
3. **Repo affinity** — if the git remote repo name or directory name appears as a substring in a board's feature name (e.g., repo `mobile-toolkit` matches `ENG | MT251 :: Mobile Toolkit`), boost that board.

### Presentation

Only show boards that scored > 0 (i.e., at least one scoring rule matched). Pre-select them. Do **not** list all available boards — instead offer an escape hatch for the user to name others:

```
Suggested boards for "Fix crash on empty CSV export":
  [x] ENG | Bugs & Issues  (matched: bug category)

Sprint: ENG | Sprint 26.16  (auto-detected)

Confirm boards, or name other boards to add: [Y/n]
```

If the user names a board not in the suggested list, fuzzy-match it against the full `backlog_boards` cache by name. If no boards scored > 0, say "No strong board match — name the backlog(s) to add this to" and list all available boards so the user can pick.

The sprint board is always added automatically — it is not part of the suggestion list.
