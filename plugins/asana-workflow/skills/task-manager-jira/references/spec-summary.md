# `acli jira` command summary

Fuller reference of the `acli jira` surface for the long tail. Not a skill — referenced from `../SKILL.md`. Authoritative help is always one flag away: `acli jira <subcommand> --help`. For the common-path mechanics and gotchas, see `acli.md`.

## Authentication

| Command | Purpose |
|---|---|
| `acli jira auth status` | Show current site, email, OAuth status (`✓ Authenticated`) |
| `acli jira auth login [--site <site>]` | Interactive OAuth login (user-initiated only) |
| `acli jira auth switch` | Switch between configured accounts/sites |
| `acli jira auth logout` | Sign out |

## Work items

```bash
acli jira workitem view <KEY> [--fields "<list>" | --fields "*all"] [--json]
acli jira workitem search --jql "<JQL>" [--limit N] [--paginate] [--json]
acli jira workitem create  -p <KEY> -t <Type> -s "<summary>" [-d "<desc>"] [--description-file <p>] [-a "@me"] [-l "<labels>"] [--parent <KEY>] [--from-json <p>] [--generate-json] [--json]
acli jira workitem edit    -k "<KEY>[,<KEY>]" [--summary] [--description] [--assignee|--remove-assignee] [--labels|--remove-labels] [--type] [--from-json <p>] [--yes] [--json]
acli jira workitem transition --key <KEY> --status "<target-name>" [--yes]
acli jira workitem delete  --key <KEY> [--yes]
acli jira workitem comment create --key <KEY> (--body "..." | --body-file <p>)
acli jira workitem comment list   --key <KEY> --json
acli jira workitem comment update --id <id> --body "..."
acli jira workitem comment delete --id <id>
acli jira workitem attachment list   --key <KEY> --json
acli jira workitem attachment delete --id <attachment-id>
```

Key constraints (full detail in `acli.md`):
- `search --fields` whitelist: `issuetype,key,assignee,priority,status,summary` only.
- `view` has no field whitelist; `--fields "*all"` returns everything.
- Priority / time tracking / sprint / custom fields: `--from-json` `additionalAttributes` on **create** only.
- `edit --from-json` rejects `additionalAttributes` and is mutually exclusive with `--key`/`--jql`/`--filter` (key goes inside JSON as `"issues"`). No `acli edit` path for priority/time/sprint/parent/custom.
- `--description` via `--from-json` MUST be ADF; the `--description` flag accepts plain text.
- `transition --status` is the target status **name**; `acli` resolves the transition.
- `acli` cannot **upload** attachments (use REST) and has **no sprint-add** command (see `boards.md`).
- `comment list --json` returns an object `{comments, total, …}` — read `.comments`.
- Subtasks: no native endpoint; `search --jql "parent = <KEY>"`.

## Boards & sprints

```bash
acli jira board search [--type scrum|kanban|simple] [--project <KEY>] [--name "<partial>"] [--json]   # → {"values":[...]}
acli jira board list-sprints --id <BOARD_ID> [--state active|closed|future] [--json]                  # → {"sprints":[...]}
acli jira sprint list-workitems --board <BOARD_ID> --sprint <SPRINT_ID> --json --limit 200            # → {"issues":[...]}
acli jira sprint (create|update|delete|view)   # metadata only — no add/move-issues subcommand
```

## Projects

```bash
acli jira project list --json
acli jira project view <KEY> --json
```

## Time tracking

The `timetracking` field exposes both display strings and raw seconds:

| Field | Type | Meaning |
|---|---|---|
| `timetracking.originalEstimate` | string | Estimate as `"1w 2d 3h 4m"` |
| `timetracking.originalEstimateSeconds` | int | Estimate in seconds |
| `timetracking.remainingEstimate` / `…Seconds` | string / int | Remaining work |
| `timetracking.timeSpent` / `…Seconds` | string / int | Logged time |
| `aggregatetimeoriginalestimate` / `aggregatetimespent` | int | Rolled up across subtasks |
| `worklog` | object | `{total, worklogs:[...]}` — capped at 20 by default |
| `workratio` | int | `(timespent/originalestimate)*100`; `-1` if undefined |

`*Seconds` fields can be `null` (unestimated / no logged time) — **`null` is not zero**; surface as "unestimated". Set the original estimate on **create** via `--from-json additionalAttributes.timetracking`; on an **existing** issue via the Atlassian MCP `editJiraIssue` tool / REST (`acli edit` cannot).

## Status categories (universal)

Every status has `statusCategory.key` ∈ `new` (To Do) / `indeterminate` (In Progress) / `done` (Done), independent of the workflow's status names. Gate on the key, not the name — see `statuses.md`.

## Issue links

```bash
# REST (link type configurable; default "Blocks"):
curl -s -X POST -H "Content-Type: application/json" \
  "https://<site>.atlassian.net/rest/api/3/issueLink" \
  -d '{"type":{"name":"Blocks"},"inwardIssue":{"key":"<TASK>"},"outwardIssue":{"key":"<DEPENDS_ON>"}}'
# Available types: GET /rest/api/3/issueLinkType
```

See `acli.md` → Issue Links for the `acli` command form (if the build exposes one) and direction semantics.

## Common pitfalls

- **Treating seconds as hours** — every `*Seconds` field is seconds (`/3600` hours, `/28800` working days).
- **Summing nulls as zero** — a `null` estimate is *unestimated*; count separately.
- **Forgetting `--limit`** — default 50 silently truncates; use `--limit 200` / `--paginate`.
- **Hardcoding sprint/board/custom-field IDs** — resolve at runtime; cache machine-locally.
- **`search --fields` whitelist** — only six fields; `view` per key for the rest.
- **Missing `sprint` key ≠ not in sprint** — confirm via JQL `sprint in openSprints()`.
- **`comment list` is an object** — read `.comments`, not the top level.
