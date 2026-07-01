# Smart Board Suggestion

When `log-task` creates a task, suggest which backlog board(s) to add it to. Boards themselves are resolved through the `task-manager` interface (`resolve_board("active sprint")`, `resolve_board("backlog")`) in Step 2 — this reference only covers the orchestrator's suggestion heuristics, not how boards are discovered or stored.

## Scoring

Take the set of backlog boards resolved in Step 2 and score each by relevance to the task:

1. **Category match** — if the task is a bug, boost boards whose name signals bugs or issues (case-insensitive substring on "bug" / "issue").
2. **Feature keyword match** — extract keywords from the task title and description and match them against the descriptive part of each board's name. Tokenize both sides (split on spaces, hyphens, underscores) and count overlapping tokens.
3. **Repo affinity** — if the git remote repo name or directory name appears as a substring in a board's descriptive name (e.g., repo `mobile-toolkit` matches a board named for the Mobile Toolkit), boost that board.

## Presentation

Only show boards that scored > 0 (i.e., at least one scoring rule matched). Pre-select them. Do **not** list all available boards — instead offer an escape hatch for the user to name others:

```
Suggested boards for "Fix crash on empty CSV export":
  [x] Bugs & Issues  (matched: bug category)

Sprint: <active sprint board name>  (auto-detected)

Confirm boards, or name other boards to add: [Y/n]
```

If the user names a board not in the suggested list, fuzzy-match it against the full backlog board set by name. If no boards scored > 0, say "No strong board match — name the backlog(s) to add this to" and list all available backlog boards so the user can pick.

The sprint board is always added automatically — it is not part of the suggestion list.
