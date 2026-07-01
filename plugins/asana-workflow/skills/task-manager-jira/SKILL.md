---
name: task-manager-jira
version: 0.1.0
description: >
  Jira implementation of the task-manager interface. Maps neutral task operations
  (create/read/update tasks, statuses, fields, comments, attachments, boards) onto Jira
  via the `acli` CLI (+ Atlassian MCP fallback). Invoked by the task-manager seam when the
  project's provider is Jira; not called directly by workflow skills.
---

# Task Manager — Jira provider

Implements the neutral operations defined in `../task-manager/SKILL.md` against Jira. Mechanics live in this skill's references:

- `references/acli.md` — `acli` command patterns and the important gotchas (sprint-field caveat, search `--fields` whitelist, `--from-json` create vs edit schemas, comment-list object shape).
- `references/fields.md` — Jira field discovery and mapping the neutral field set to Jira fields.
- `references/statuses.md` — mapping neutral lifecycle names to Jira via `statusCategory`.
- `references/boards.md` — Jira Agile board + sprint discovery and active-sprint membership.
- `references/spec-summary.md` — fuller `acli` command reference for the long tail.

## Auth

`acli` handles OAuth out of band — there is **no env var and no token** to resolve in this provider, and the seam never sees a credential.

- Verify auth before any operation: `acli jira auth status` — expect `✓ Authenticated`.
- If not authenticated, the user must run `acli jira auth login` **interactively**. This cannot be automated; surface the instruction and stop.
- **Multiple accounts/sites** via `acli` profiles: `acli jira auth switch` between configured accounts; `acli jira auth login --site <site>` to add a new one. When the user names an account that maps to a known profile, switch; if unknown, ask them to log in to that site first.
- The active account is whatever `acli` reports. There is **no per-session override file** — account selection lives entirely in `acli`.

## Transports

The **primary transport is `acli`**. A **secondary transport is required** for fields `acli edit` cannot set on an existing issue — **priority, time tracking, sprint, parent, custom fields**. Pick the transport per-operation; the neutral op signature does not change.

- Secondary transport: the user-connected Atlassian MCP `editJiraIssue` tool (the `claude.ai` Atlassian connector — **not** registered by this plugin), or the Jira REST API directly if the MCP tool is unavailable.
- `editJiraIssue(cloudId: "<site>.atlassian.net", issueIdOrKey: "<KEY>", fields: { ... })` takes the same Jira field IDs as REST (`priority`, `timetracking`, `parent`, `customfield_*`).

## Operation mapping

| Neutral op | Jira realization |
|---|---|
| `get_current_user()` | `acli jira auth status` (reports the authenticated account/site) (`references/acli.md`). |
| `find_task(ref)` | `scripts/tm.py ref parse <url-or-ref>` — extracts the issue key with regex `[A-Z][A-Z0-9_]+-\d+` (first match) from a `*.atlassian.net` URL or a bare key and prints it; exits 2 (no output) when the input is not a Jira reference. Project key is the prefix before the dash (`references/acli.md` → URL & Key Extraction). |
| `get_task(task)` | `scripts/tm.py task get <issue-key>` — runs `acli jira workitem view <KEY> --fields "*all" --json` and returns a **compact neutral projection** (`{ref,name,description,assignee,status,board,fields}`; native fields mapped by their stable ids, customfield-backed canonical fields via `acli jira field list` metadata, `status` = `{name,category}`, `name` = summary) instead of the raw `*all` blob (token win). For unusual long-tail needs, the raw `*all` recipe in `references/acli.md` (View) is still available. |
| `create_task(...)` | `scripts/tm.py task create <project-key> --title T [--description D] [--assignee A] [--type T]` → `acli jira workitem create` (`--type` defaults to `Task`). Priority / time tracking / sprint / custom fields are **not flags** and not part of this neutral surface → set them at creation via `acli ... --from-json` `additionalAttributes`, or post-create via the MCP fallback (`references/acli.md` → Create). |
| `delete_task(task)` | `acli jira workitem delete --key <KEY> --yes` (`references/acli.md` → Delete). |
| `add_to_board(task, board)` | `scripts/tm.py task add-to-board <issue-key> <board-ref>` — **PARTIAL**: `acli` has no sprint-add command, so the script **exits 1** with the sprint-field/MCP/operator fallback signal. Degrade per `references/boards.md`: on **create** set the sprint field via `--from-json`; on an **existing** issue via Atlassian MCP `editJiraIssue` (`customfield_<sprintId>`) / REST; else prompt the operator to drag it into the sprint in the UI. Never silent no-op. |
| `add_dependency(task, depends_on)` | `scripts/tm.py task add-dependency <issue-key> <depends-on-key>` — Jira **issue link** (link type configurable, default `"Blocks"`). Runs `acli jira workitem link` **if this acli build exposes it**; otherwise **PARTIAL**: exits 1 with the "needs Atlassian MCP / REST `POST /rest/api/3/issueLink` (agent-handled)" signal. Direction: `task` is blocked by `depends_on` (`references/acli.md` → Issue Links). |
| `set_parent(task, parent)` | On **create**: `--parent <KEY>` flag or `parentIssueId` in `--from-json`. On an **existing** issue: `scripts/tm.py task set-parent <issue-key> <parent-key>` — **PARTIAL**: `acli edit` cannot set parent, so the script **exits 1** with the Atlassian MCP `editJiraIssue` (`fields.parent`) / REST fallback signal (`references/acli.md` / `references/fields.md`). |
| `set_status(task, status)` | `scripts/tm.py task set-status <issue-key> <status-name>` — resolves the neutral lifecycle name → a target Jira status by **statusCategory** (`new`/`indeterminate`/`done`), not literal strings: lists the issue's available transitions, picks the one whose `to.statusCategory.key` matches (preferring a name match within the category), then runs `acli jira workitem transition --key <KEY> --status "<name>" --yes`. No transition reaches the category → exit 1 (`references/statuses.md`). |
| `set_field(task, field_name, value)` | `scripts/tm.py task set-field <issue-key> <CanonicalName> <value>` — **PARTIAL**. `acli edit` reaches **assignee / labels / type** (the script sets these and exits 0). **priority / sizing (story points) / time tracking / parent / sprint / any customfield** are NOT reachable by `acli edit`: the script exits non-zero with a `needs Atlassian MCP editJiraIssue fallback (agent-handled)` signal — the skill then performs that write via the Atlassian MCP `editJiraIssue` tool (or REST). `Product Status` is set via transition (`set_status`), not here. Mapping rules in `references/fields.md`. Never silent no-op. |
| `set_fields(task, {field: value, …})` | Apply multiple fields together: `acli`-reachable ones (assignee / labels / type) in one `acli edit`, and **all** MCP-only fields (priority / sizing / time / parent / sprint / customfields) bundled into a **single** Atlassian MCP `editJiraIssue` call — Jira's edit endpoint accepts a multi-field `fields` object, so this is one write, not N. Fields the provider can't address are surfaced, never silently dropped. (A `tm.py task set-fields` verb mirroring the Asana provider is the thin follow-up; until then the seam may degrade to per-field `set_field`.) |
| `add_comment(task, body)` | `scripts/tm.py comment add <issue-key> (<body> \| --body-file <path>)` → `acli jira workitem comment create`. Author Markdown; `acli` wraps it to ADF. Prefer `--body-file` for large/multiline bodies (`references/acli.md` → Comments). |
| `get_comments(task)` | `scripts/tm.py comment list <issue-key>` → reads `acli jira workitem comment list --json` (an **object** `{comments:[…], total, …}`; the script reads `.comments`, not the top-level) and returns the compact `[{author, text, created_at}]` (`references/acli.md` → Comments). |
| `upload_attachment(task, file)` | **PARTIAL** — `scripts/tm.py task attach <issue-key> <file-path>` exits non-zero with the MCP/operator-fallback signal (`acli` cannot upload, and the script cannot call the MCP). The skill then performs the upload via the Atlassian MCP / REST `POST /rest/api/3/issue/<KEY>/attachments` (header `X-Atlassian-Token: no-check`), else prompts the operator to attach via the Jira UI. Never silent no-op (`references/acli.md` → Attachments). |
| `remove_attachment(task, attachment)` | `acli jira workitem attachment delete --id <attachment-id>` (`references/acli.md` → Attachments). |
| `get_attachments(task)` | `acli jira workitem attachment list --key <KEY> --json` (`references/acli.md` → Attachments). |
| `get_subtasks(task)` | `acli jira workitem search --jql "parent = <KEY>" --json` (no native subtask endpoint; subtasks are work items with that parent) (`references/acli.md` → Subtasks). |
| `list_fields(board)` | `scripts/tm.py fields list <project-ref>` — code-enforced discovery + neutral-name→Jira-id mapping (cache-first, discover-on-miss + write-back). `<project-ref>` must be a representative **issue key** on first discovery (e.g. `TP-687`); the cache is keyed by the project prefix. Force a refresh with `scripts/tm.py fields discover <ISSUE-KEY>`. Under the hood it views the issue (`acli jira workitem view <KEY> --fields "*all" --json`) plus `acli jira field list` metadata; rules in `references/fields.md`. |
| `list_tasks(board)` | Active sprint → `acli jira sprint list-workitems --board <ID> --sprint <ID> --json --limit 200`; otherwise `acli jira workitem search --jql "…" --json --limit 200` (`references/boards.md`). |
| `resolve_board(intent)` | **Hard gate — cache-first, never manual discovery on a hit.** FIRST, MANDATORY action: derive the key via `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager-jira/scripts/tm.py board key`, then run `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager-jira/scripts/tm.py board resolve <key> <intent>` (intent ∈ `active-sprint`/`backlog`). It reads cache-first, auto-refreshes only when the cached active sprint is stale (`endDate` past or `state != active`), and signals miss/bootstrap via exit code. Do **NOT** issue manual `acli jira board search`/`list-sprints` discovery when the script returns a board. Live discovery happens only via the script's `board discover` path (`acli`) on a genuine miss (exit 4 = bootstrap: resolve the Jira project key + scrum board per `references/boards.md`, `board write` them, then `board discover`), and it writes back. For active-sprint **membership** of a given issue, still prefer the issue's own `sprint in openSprints()` JQL over a board diff; backlog = issues in no sprint. Discovery rules + schema live in `references/boards.md`. |

For operations not in the table, use `references/spec-summary.md` directly — this is the provider-coupled long-tail path.

## Errors / partial support

Per `../task-manager/references/provider-guide.md`: when `acli` cannot perform a neutral op (`add_to_board`, `upload_attachment`, `set_parent`/`set_field`/sprint on an existing issue), the provider MUST either route through the alternate transport (Atlassian MCP `editJiraIssue` / REST) or return a clear, operator-actionable prompt. **Never silently no-op.**

Surface `acli` errors faithfully — report the error and the command attempted:

- `✓ Authenticated` missing → `acli jira auth status` failed; user must run `acli jira auth login`.
- `403 Forbidden` → user lacks permission on the project/issue.
- `404 Not Found` → invalid issue key or deleted resource.
- `fields '<x>' are not allowed` → hit the `search --fields` whitelist; use `workitem view --fields "*all"` per key instead.
