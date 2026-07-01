# Jira board & sprint resolution

> The neutral sprint/backlog concept and active-sprint policy live in `../../../references/workflow/boards.md`. This file is the Jira-specific identification, discovery, and membership of those boards. Not a skill — referenced from `../SKILL.md`.

> **The cache lifecycle is enforced by `../scripts/tm.py` (the `board` family)** (`board key`/`board read`/`board resolve`/`board discover`/`board refresh`/`board write`), which shares `../../task-manager/scripts/cache_util.py` with the seam (the neutral key/path/timestamp/staleness layer). Go through the script for `resolve_board` — it is cache-first and only runs the `acli` discovery below on a genuine miss. This file documents the Jira board/sprint model the script implements.

Jira Agile organizes work on **boards** (scrum/kanban) and **sprints**. The neutral "sprint board" maps to a Jira scrum board's active sprint; the neutral "backlog" maps to issues in no sprint.

## Resolve the board for a project

```bash
acli jira board search --project TP --type scrum --json   # → {"values": [...]}
```

Take the first scrum board for the project. The board ID may also be read from a board URL (`/jira/software/c/projects/TP/boards/268` → `268`). Cache the resolved board ID in the machine-local `~/.cortex/` cache; never commit or hard-code it.

## Active sprint

```bash
acli jira board list-sprints --id 268 --state active --json   # → {"sprints": [...]}
```

`--state active` returns the open (current, not-yet-finished) sprint(s). Per the neutral active-sprint policy, when more than one candidate qualifies the **latest-ending** one wins (compare `endDate`). Save the sprint `id` for `list_tasks` and create-time sprint assignment.

## List tasks on a board / sprint (list_tasks)

```bash
# Active sprint
acli jira sprint list-workitems --board 268 --sprint <sprint-id> --json --limit 200   # → {"issues": [...]}

# Or any board/sprint slice via JQL
acli jira workitem search --jql "project = TP AND sprint in openSprints()" --json --limit 200
```

Default `--limit` is 50 — pass `--limit 200` or `--paginate` to avoid silently truncating.

## Active-sprint membership of an issue (prefer this over a board diff)

To decide whether a **given issue** is in the active sprint, do **not** diff the board's issue list. Read the issue's own sprint state via JQL — it is authoritative even when the `sprint` field is omitted from `workitem view` (see the sprint-field caveat in `acli.md`):

```bash
acli jira workitem search --jql "key = <KEY> AND sprint in openSprints()" --json
```

A non-empty result means the issue is in an active sprint; an empty result means it is not.

## Backlog

The backlog is **issues in no sprint** (and not done):

```bash
acli jira workitem search \
  --jql "project = TP AND sprint is EMPTY AND statusCategory != Done ORDER BY rank ASC" \
  --json --limit 200
```

## Adding an issue to a sprint (add_to_board — PARTIAL)

`acli` has **no sprint-add command** (`acli jira sprint` exposes only `create`/`delete`/`update`/`view`/`list-workitems`). Degrade, never silent no-op:

1. **On create** — set the sprint custom field via `--from-json` `additionalAttributes` (`{ "customfield_<sprintFieldId>": <SPRINT-ID> }`). The sprint field ID is instance-specific (commonly `customfield_10020`) — discover it at runtime (see `fields.md` / `acli.md`).
2. **On an existing issue** — `acli edit` cannot set it. Use the Atlassian MCP `editJiraIssue` tool (`fields: { "customfield_<sprintFieldId>": <SPRINT-ID> }`) or REST.
3. **Fallback** — prompt the operator: "Issue created. `acli` cannot add it to the active sprint automatically — please drag it into Sprint <name> in the Jira UI, then continue."

## Caching

Concrete instance values (board ID, active-sprint ID + end date, discovered sprint custom-field ID) belong in the machine-local `~/.cortex/` cache — never committed, never in workflow references. Refresh when the cached sprint's `endDate` is in the past or the operator asks to refresh.
