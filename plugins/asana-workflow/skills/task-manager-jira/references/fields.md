# Jira field discovery & mapping

> Field *meanings* are defined neutrally in `../../../references/workflow/fields.md`. This file is the Jira-specific discovery + mapping of those fields. Not a skill — referenced from `../SKILL.md`.
>
> **Discovery + neutral-name→Jira-id mapping is code-enforced by `../scripts/tm.py fields`** (`fields list <project-ref>` / `fields resolve <project-ref> <CanonicalName>` / `fields discover <ISSUE-KEY>`). The mapping below — native fields (`issuetype`/`priority`/`labels`/`timetracking`/`parent`/`assignee`/`status`) and the customfield-backed fields (Sizing/Platform) discovered at runtime — is what that script implements; do not re-ingest the full `fields` map and map by hand. The script needs a representative **issue key** on first discovery (the `workitem view` payload is keyed by id only; customfield names come from `acli jira field list` metadata, and a customfield whose name can't be matched is recorded undetermined and skipped, never guessed).

## Discovery

Jira has no per-board field-settings endpoint. Discover available fields (and custom-field IDs) by inspecting a representative issue:

```bash
acli jira workitem view <KEY> --fields "*all" --json
```

The response's `fields` map holds every field, keyed by Jira field ID. System fields use stable names (`summary`, `description`, `assignee`, `priority`, `labels`, `issuetype`, `parent`, `timetracking`, `status`). Custom fields appear as `customfield_NNNNN` — these IDs are **instance-specific and discovered at runtime, never hard-coded**.

To find a custom field's ID, scan the `fields` map for the value or name you expect (e.g. story points, sprint):

```bash
acli jira workitem view <KEY-WITH-VALUE> --fields "*all" --json \
  | python3 -c "import json,sys; f=json.load(sys.stdin)['fields']; [print(k,'→',v) for k,v in f.items() if k.startswith('customfield_') and v is not None]"
```

## Neutral field → Jira mapping

| Neutral field | Jira field | Set via | Notes |
|---|---|---|---|
| Type / Category | `issuetype` (**native issue type**: `Bug`, `Story`, `Task`, `Epic`, …) | `acli create --type` / `acli edit --type` | Native in Jira, not a custom field. Used for routing (Bug → bug flow). |
| Sizing | **story points** (`customfield_NNNNN`) | create `--from-json` `additionalAttributes`; existing → MCP `editJiraIssue` / REST | ID discovered at runtime (commonly `customfield_10008`/`10016` — verify per instance). Jira's native estimate. |
| Estimate | `timetracking` (`originalEstimate` as `"1w 2d 3h 4m"`) | create `--from-json`; existing → MCP `editJiraIssue` / REST | `*Seconds` companions are read-only conversions; `null` ≠ zero (= unestimated). |
| Priority | `priority` (`{"name": "Highest"}`) | create `--from-json`; existing → MCP `editJiraIssue` / REST | Not an `acli` flag. |
| Labels | `labels` | `acli create --label` / `acli edit --labels` / `--remove-labels` | Reachable via `acli`. |
| Parent / Epic | `parent` / `parentIssueId` | create `--parent` or `--from-json parentIssueId`; existing → MCP `editJiraIssue` / REST | `acli edit` has no `--parent` and rejects it in JSON — re-parent via alternate transport. |
| Assignee | `assignee` (`@me` / `default` / email / account-id) | `acli create --assignee` / `acli edit --assignee` / `--remove-assignee` | Native attribute. |
| Platform | a `customfield_NNNNN` (if the project defines it) | discover at runtime; create `--from-json`; existing → MCP / REST | Skip gracefully if the project has no such field. |
| Product Status | `status` (via transition) | `acli workitem transition` | Not a settable field — moved by workflow transitions. See `statuses.md`. |

## Reachability summary (which transport)

- **`acli` reaches**: `summary`, `description`, `assignee`, `labels`, `issuetype` (edit); plus `parent` and the `--from-json` create fields at creation time.
- **`acli edit` cannot reach** (existing issue): `priority`, story points (Sizing), `timetracking` (Estimate), sprint, `parent`, any `customfield_*`. Route those through the Atlassian MCP `editJiraIssue` tool or REST `PUT /rest/api/3/issue/<KEY>` — this is the PARTIAL / multi-transport path (see `acli.md` → "Setting fields `acli edit` can't reach").

Not every project carries every field. A field with no match in the instance is skipped gracefully, never invented.
