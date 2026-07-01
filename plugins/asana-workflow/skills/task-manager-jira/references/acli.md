# `acli` command patterns & gotchas

The `acli` mechanics for the Jira provider. Not a skill — referenced from `../SKILL.md`. Authoritative help is always one flag away: `acli jira <subcommand> --help`. The fuller surface lives in `spec-summary.md`.

`acli` handles OAuth out of band: no env var, no token. Verify with `acli jira auth status` (expect `✓ Authenticated`); if missing, the user must run `acli jira auth login` interactively (cannot be automated).

## URL & Key Extraction

Issue keys are extracted from any Jira URL or bare input with regex `[A-Z][A-Z0-9_]+-\d+`. Match the **first** occurrence.

- `https://acme.atlassian.net/browse/TP-687` → `TP-687`
- `https://acme.atlassian.net/jira/software/c/projects/TP/boards/268?selectedIssue=TP-687` → `TP-687`
- `TP-687` → `TP-687`

The project key is the prefix before the dash (`TP` from `TP-687`). The board ID, if not in the URL, is resolved via `acli jira board search --project TP --type scrum --json` (see `boards.md`). The site is whatever `acli jira auth status` reports.

## View (get_task)

```bash
acli jira workitem view TP-687 --fields "*all" --json
```

- `--fields "*all"` returns every field incl. custom fields and time tracking.
- `--fields "key,summary,status,…"` limits the payload (no whitelist on `view`, unlike `search`).
- `--json` is required for programmatic parsing. Output is a top-level object with a `fields` map.

> **Sprint-field caveat.** A missing `sprint` key does **not** prove "not in a sprint." On some instances the key is omitted entirely when the issue is in no sprint (no `sprint` key at all — not `null`); on others the sprint lives only under a `customfield_*` (commonly `customfield_10020`). Confirm membership with JQL instead: `acli jira workitem search --jql "key = <KEY> AND sprint in openSprints()" --json` — an empty result means it is not in an active sprint.

## Search (JQL)

```bash
acli jira workitem search --jql "<JQL>" [--limit N] [--paginate] [--json]
```

> **Search `--fields` whitelist.** `acli jira workitem search --fields` accepts **only** `issuetype,key,assignee,priority,status,summary`. Anything else errors with `fields '<x>' are not allowed`. For richer fields, list keys via `search`, then `workitem view --fields "*all"` per key.

Default `--limit` is 50 and silently cuts large result sets — pass `--limit 200` or `--paginate`.

## Create (create_task)

> **Goes through `scripts/tm.py task create <project-key> --title T [--description D] [--assignee A] [--type T]`** (`--type` defaults to `Task`), which wraps `acli jira workitem create` for the neutral title/description/assignee surface. Fields not on that surface (priority / time tracking / sprint / custom) still use the `--from-json` path documented below, or the post-create MCP fallback. The raw `acli` form:

```bash
acli jira workitem create \
  --project TP --type Task \
  --summary "Fix null pointer in export pipeline" \
  --description "The CSV exporter crashes when the input has zero rows." \
  --assignee "@me" --label "bug,export" --parent TP-200 --json
```

Flags: `--project`(`-p`), `--type`(`-t`), `--summary`(`-s`), `--description`(`-d`), `--description-file`, `--assignee`(`-a`: `@me` / `default` / email / account-id), `--label`(`-l`, comma-separated), `--parent` (parent/epic key on creation), `--from-json`, `--generate-json`, `--json`. Save the returned `key` for downstream ops.

### `--from-json` (create) — required for non-flag fields

**Priority, time tracking, sprint, and custom fields are NOT flags.** Set them only via `--from-json`:

```bash
acli jira workitem create --generate-json > /tmp/spec.json   # template
cat > /tmp/spec.json <<'EOF'
{
  "projectKey": "TP",
  "type": "Task",
  "summary": "Fix null pointer in export pipeline",
  "description": {"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"…"}]}]},
  "assignee": "@me",
  "parentIssueId": "TP-200",
  "additionalAttributes": {
    "priority": {"name": "Highest"},
    "timetracking": {"originalEstimate": "3h"},
    "customfield_10020": 1234
  }
}
EOF
acli jira workitem create --from-json /tmp/spec.json --json
```

- `description` MUST be ADF when set via `--from-json`; plain text is only accepted via the `--description` flag.
- `additionalAttributes` accepts the Jira field IDs that appear in `workitem view --fields "*all"` — `priority`, `timetracking`, `labels`, any `customfield_NNNNN`.

## Edit (set_field / set_parent on existing issues)

> **Goes through `scripts/tm.py task set-field <issue-key> <CanonicalName> <value>`.** The script runs `acli edit` for the reachable fields (**assignee / labels / type**) and exits 0. For the fields `acli edit` CANNOT reach (priority / story points / time tracking / parent / sprint / any customfield) it exits non-zero with a `needs Atlassian MCP editJiraIssue fallback (agent-handled)` signal — the skill then performs that write via the MCP tool / REST (see "Setting fields `acli edit` can't reach" below). The script never silently no-ops.

The command is `edit` (not `update`). Flags: `--key`(`-k`, comma list), `--jql`, `--filter`, `--summary`, `--description`, `--description-file`, `--assignee` / `--remove-assignee`, `--labels` / `--remove-labels`, `--type`, `--from-json` / `--generate-json`, `--yes`(`-y`), `--json`.

```bash
acli jira workitem edit --key TP-687 --summary "New summary" --yes
acli jira workitem edit --key TP-687 --assignee "@me" --yes
acli jira workitem edit --key TP-687 --labels "bug,priority-high" --yes
```

> **`--from-json` on `edit` is far narrower than on `create`** (both gotchas verified against current `acli`):
> 1. **`--from-json` is mutually exclusive with `--key` / `--jql` / `--filter`.** Passing them together errors with `if any flags in the group [key jql filter generate-json from-json] are set none of the others can be`. The target key(s) go *inside* the JSON as `"issues": ["TP-687"]`.
> 2. **`edit`'s JSON schema rejects `additionalAttributes`** (`json: unknown field "additionalAttributes"`). Accepted keys are only `issues`, `summary`, `description`, `assignee`, `type`, `labelsToAdd`, `labelsToRemove`. There is **no `acli edit` path — flag or JSON — to set priority, time tracking, sprint, parent, or custom fields** on an existing issue.

```bash
cat > /tmp/edit.json <<'EOF'
{ "issues": ["TP-687"], "summary": "New summary", "labelsToAdd": ["priority-high"] }
EOF
acli jira workitem edit --from-json /tmp/edit.json --yes
```

### Setting fields `acli edit` can't reach (multi-transport)

For priority / time tracking / sprint / parent / custom on an **existing** issue, use the alternate transport — Atlassian MCP `editJiraIssue` (or REST):

```
editJiraIssue(cloudId: "<site>.atlassian.net", issueIdOrKey: "TP-687",
              fields: { "timetracking": { "originalEstimate": "3h" } })
```

`fields` takes the same Jira field IDs as REST (`priority`, `timetracking`, `parent`, `customfield_*`). If the MCP tool is unavailable, fall back to REST `PUT /rest/api/3/issue/<KEY>` with the same `fields` body. Never silent no-op.

## Transition (set_status)

```bash
acli jira workitem transition --key TP-687 --status "In Progress" --yes
```

`--status` is the **target status name** (not a transition ID) — `acli` resolves the transition. Accepts a comma list on `--key` or `--jql` for bulk. Resolve the neutral lifecycle name → Jira status by **statusCategory** (see `statuses.md`), then pass that status name.

## Comments (add_comment / get_comments)

> **Go through `scripts/tm.py comment …`.** `scripts/tm.py comment add <issue-key> (<body> | --body-file <path>)` wraps `acli jira workitem comment create` (prefer `--body-file` for large/multiline bodies). `scripts/tm.py comment list <issue-key>` wraps `acli jira workitem comment list --json` and returns the compact `[{author, text, created_at}]` (reading `.comments`, not the top-level object — see below). The raw `acli` forms:

```bash
acli jira workitem comment create --key TP-687 --body "Comment text"
acli jira workitem comment create --key TP-687 --body-file /tmp/comment.md
acli jira workitem comment list   --key TP-687 --json
acli jira workitem comment update --id <comment-id> --body "..."
acli jira workitem comment delete --id <comment-id>
```

Author Markdown; `acli` auto-wraps plain text into ADF. Rich Markdown → ADF (headings, lists, code, links) is the provider's job — convert before submitting. `update`/`delete` are not on the neutral surface — use the raw `acli` form for those.

> **Comment-list object shape.** `comment list --json` returns an **object**, not a bare array: `{"comments": [...], "total": N, "startAt": 0, "maxResults": 50, "isLast": true}`. Read `.comments` for the entries (each has `author`, `body`, `created`, `updated`) and `.total` for the count. `len(result)` on the top level returns `5` (wrapper keys), not the number of comments; `total == 0` means no comments.

## Delete (delete_task)

```bash
acli jira workitem delete --key TP-687 --yes
```

`--yes` skips the confirmation prompt. (Confirm flag set with `acli jira workitem delete --help` on your `acli` build.)

## Issue Links (add_dependency)

Dependencies are Jira **issue links**. The link **type is configurable** (a provider-local setting); default `"Blocks"`. Semantics: `add_dependency(task, depends_on)` means `task` is **blocked by** `depends_on`.

```bash
# If the acli build exposes a link command (confirm with: acli jira workitem link --help):
acli jira workitem link --from <DEPENDS_ON> --to <TASK> --type "Blocks"
```

If `acli` has no link command, use REST (alternate transport):

```bash
curl -s -X POST -H "Content-Type: application/json" \
  "https://<site>.atlassian.net/rest/api/3/issueLink" \
  -d '{"type":{"name":"Blocks"},
       "inwardIssue":{"key":"<TASK>"},
       "outwardIssue":{"key":"<DEPENDS_ON>"}}'
```

The `"Blocks"` link type has inward `"is blocked by"` and outward `"blocks"`. To make `<TASK>` blocked by `<DEPENDS_ON>`, the outward (blocking) issue is `<DEPENDS_ON>` and the inward (blocked) issue is `<TASK>`. To use a different relationship, change the link `type.name` (e.g. `"Relates"`); discover available types via `GET /rest/api/3/issueLinkType`.

## Attachments (upload / remove / get)

```bash
acli jira workitem attachment list   --key TP-687 --json   # get_attachments
acli jira workitem attachment delete --id <attachment-id>   # remove_attachment
```

> **`acli` cannot upload attachments.** `scripts/tm.py task attach <issue-key> <file-path>` exits non-zero with the `needs Atlassian MCP editJiraIssue fallback (agent-handled)` signal — the script cannot call the MCP itself. The skill then uploads via the alternate transport — the Atlassian MCP or REST:
> ```bash
> curl -s -X POST -H "X-Atlassian-Token: no-check" \
>   -F "file=@/path/to/file.png" \
>   "https://<site>.atlassian.net/rest/api/3/issue/TP-687/attachments"
> ```
> If REST is unavailable, prompt the operator to attach via the Jira UI. Never silent no-op.

## Subtasks (get_subtasks)

No native subtask endpoint. Subtasks are work items with the issue as parent — list via JQL:

```bash
acli jira workitem search --jql "parent = TP-687" --json
```

## Output shapes cheat sheet

| Command | List wrapper key |
|---|---|
| `acli jira board search --json` | `values` |
| `acli jira board list-sprints --json` | `sprints` |
| `acli jira sprint list-workitems --json` | `issues` |
| `acli jira workitem search --json` | top-level **array** (not wrapped) |
| `acli jira workitem view --json` | top-level object with `fields` |
| `acli jira workitem comment list --json` | object `{comments, total, startAt, maxResults, isLast}` |
