# Asana REST recipes

Raw Asana REST patterns used by the Asana provider. Not a skill — referenced from `../SKILL.md`.

Common Asana REST API patterns for task management workflows. All operations use bearer token authentication via a resolved token (see Token Resolution below).

## Prerequisites

- `$ASANA_PERSONAL_ACCESS_TOKEN` env var — primary Asana personal access token (required)
  - If missing: guide user to https://app.asana.com/0/my-apps
  - Add to `~/.zshrc`: `export ASANA_PERSONAL_ACCESS_TOKEN="your-token"`
- Additional tokens (optional) — stored as `ASANA_TOKEN_<NAME>` env vars, e.g.:
  - `export ASANA_TOKEN_WORK="your-work-token"`
  - `export ASANA_TOKEN_CLIENT_X="your-client-x-token"`

## Token Resolution

At the start of every invocation, resolve which token to use and treat it as `$ASANA_TOKEN` for all subsequent API calls in this skill.

**Resolution order:**

1. **Check conversation context** — if a token override was set earlier in this session (e.g., user said "use my work account"), use that token value directly.
2. **Otherwise** — use `$ASANA_PERSONAL_ACCESS_TOKEN` as the default.

**Switching accounts (conversational):**

When the user says something like "use my work Asana account", "switch to the client token", or any similar intent:

1. Run `env | grep ^ASANA_TOKEN_` to discover available named tokens.
2. Match the user's phrasing conversationally against the discovered names (e.g., "work" → `ASANA_TOKEN_WORK`, "client x" → `ASANA_TOKEN_CLIENT_X`).
3. If exactly one match: set it as the active token override in conversation context. Confirm: "Switched to ASANA_TOKEN_WORK for this session." (replace `ASANA_TOKEN_WORK` with the actual matched variable name)
4. If multiple plausible matches: list the options and ask the user which to use.
5. If no match found: report clearly (e.g., "No ASANA_TOKEN_* var found matching 'work'. Available: ASANA_TOKEN_CLIENT_X") and fall back to the default.

**Error handling for the resolved token:**

- If the resolved token value is empty: report it (e.g., "ASANA_TOKEN_WORK is set but empty") and fall back to `$ASANA_PERSONAL_ACCESS_TOKEN`.
- If an API call returns 401 on the switched token: report "ASANA_TOKEN_WORK appears invalid or expired (HTTP 401)." and offer to fall back to the default.

The active token override is session-only — nothing is written to disk.

## Authentication

All requests use the token resolved above:

```
Authorization: Bearer $ASANA_TOKEN
```

## Common Operations

### Fetch Current User

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/users/me?opt_fields=gid,name,email"
```

### Fetch Project Custom Field Settings

Returns all custom field definitions for a project — field GIDs, names, types, and enum options. Use this to discover what fields exist before creating or updating tasks.

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/projects/<project-gid>/custom_field_settings\
?opt_fields=custom_field.gid,custom_field.name,custom_field.type,\
custom_field.enum_options,custom_field.enum_options.gid,custom_field.enum_options.name"
```

> **Sandbox warning — use `scripts/tm.py task …` for writes, never `curl`.** `curl -F` (multipart) and `curl -d "$(…)"` (command-substituted JSON bodies) intermittently fail under the Bash sandbox's restrictive profile (`failed to change group ID`). The write recipes below (create, update-custom-field, attachment) are realized through the script's `task` family, which builds the request with Python `urllib` in a single top-level process — sandbox-safe. The `curl GET` reads elsewhere on this page are fine as-is.

### Create Task

Use the script — it does the two-step create+addProject in one call, via urllib:

```bash
scripts/tm.py task create <project-gid> --title "<title>" [--description "<desc>"] [--assignee "<user_gid>"]
```

It runs `POST /tasks` (name, notes, workspace from the board cache, assignee) — **no `custom_fields`**, which the Asana API rejects until the task belongs to a project — then `POST /tasks/<gid>/addProject`. Set custom fields afterward via **Update Custom Field** (`task set-field`). The created task JSON (including its `gid`) is printed to stdout. A missing cached `workspace_gid` exits 4 (bootstrap; see `boards.md`).

A task can belong to multiple projects — to add it to additional projects, `POST /tasks/<gid>/addProject` once per project.

### Add Dependencies

Mark a task as blocked by / dependent on another task. Wire dependencies only after all referenced tasks exist (their GIDs must already be available). Use the script — it builds the request with urllib (no `curl`):

```bash
scripts/tm.py task add-dependency <task-gid> <depends-on-gid>
```

It `POST`s `/tasks/<gid>/addDependencies` with `{"data":{"dependencies":["<depends-on-gid>"]}}`. `<depends-on-gid>` is the blocking task; it renders as a blocking relationship in Asana. The response JSON is printed to stdout.

### Set Parent

Set a task's parent (place it under another task in the hierarchy). Use the script (urllib, no `curl`):

```bash
scripts/tm.py task set-parent <task-gid> <parent-gid>
```

It `POST`s `/tasks/<gid>/setParent` with `{"data":{"parent":"<parent-gid>"}}`.

### List Tasks in a Project

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/projects/<project-gid>/tasks?opt_fields=name,completed"
```

Results are paginated — follow the `next_page` offset to fetch all tasks.

### Fetch Task Details

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>?opt_fields=name,notes,assignee,assignee.name,custom_fields,custom_fields.name,custom_fields.display_value,custom_fields.enum_value,custom_fields.enum_value.name,custom_fields.type,memberships,memberships.project,memberships.project.name,memberships.section,memberships.section.name,projects,projects.name"
```

### Set Status (two-axis: Product Status field or board section)

Set a task's status. Use the script — it implements the **two-axis** model in `../../../references/workflow/lifecycle.md` and writes via urllib (no `curl`):

```bash
scripts/tm.py task set-status <task-gid> <status-name>
```

Order (documented): it tries the **Product Status custom field FIRST** — resolve via the `fields` logic; if `<status-name>` matches an enum option, `PUT /tasks/<gid>` `custom_fields:{<field-gid>:<option-gid>}`. **Then** a **board section** move — discover the task's project sections (`GET /projects/<gid>/sections`), and if `<status-name>` matches a section name, `POST /sections/<section-gid>/addTask` `{"data":{"task":"<gid>"}}`. Matches neither → exit 1 (not a known Product Status option or section).

The underlying section-move endpoints, for reference:

1. List sections in the project:
   ```bash
   curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
     "https://app.asana.com/api/1.0/projects/<project-gid>/sections?opt_fields=name"
   ```

2. Find the target section by name, then move (the script does this via urllib):
   ```
   POST /sections/<section-gid>/addTask   {"data":{"task":"<task-gid>"}}
   ```

### Add to Board (addProject)

Add an existing task to another board/project. Use the script (urllib, no `curl`):

```bash
scripts/tm.py task add-to-board <task-gid> <project-gid>
```

It `POST`s `/tasks/<gid>/addProject` with `{"data":{"project":"<project-gid>"}}`. A task can belong to multiple projects — run once per project.

### Update Custom Field

Use the script — it resolves the canonical field (gid/type/enums) via the `fields` logic, then `PUT`s via urllib:

```bash
scripts/tm.py task set-field <task-gid> <CanonicalName> <value>
```

Realization: enum → the matching option GID (value matched by option name or gid); `Estimate` → unit-adaptive (enum hh:mm option, or number in hours/minutes/duration per the field — see `custom-fields.md`); `Assignee` → the native `assignee` field (`PUT /tasks/<gid>`, not a custom field); other custom fields → `PUT custom_fields:{<field-gid>:<value>}`. Exit 2 when the canonical field is not on the task's project(s) — skip gracefully.

### Post Comment on Task

Use the script — author the body as **Markdown**, and it converts to Asana HTML, routes through the correct field, and `POST`s `/tasks/<gid>/stories` via urllib:

```bash
scripts/tm.py comment add <task-gid> "<markdown body>"
scripts/tm.py comment add <task-gid> --body-file /path/to/body.md
```

Prefer `--body-file` for large/multiline bodies — it keeps the body off the command line, avoiding command-substitution fragility under the Bash sandbox.

**The script converts Markdown → Asana HTML for you** (Asana does not render Markdown — raw Markdown would show literal asterisks, backticks, and brackets). What it does, as documentation:

| Markdown | Asana HTML |
|---|---|
| `**bold**` | `<strong>bold</strong>` |
| `*italic*` or `_italic_` | `<em>italic</em>` |
| `` `code` `` | `<code>code</code>` |
| `[text](url)` | `<a href="url">text</a>` |
| `- item` / `* item` (bullet list) | `<ul><li>item</li></ul>` |
| `1. item` (numbered list) | `<ol><li>item</li></ol>` |
| `# Heading` | `<h1>Heading</h1>` |

It then decides the API field automatically: a body containing HTML tags is sent as `html_text` (wrapped in `<body>…</body>` when not already); a plain body with no tags is sent as `text` (Asana auto-links URLs). The created story JSON is printed to stdout.

**Line breaks in rich text use literal `\n`, not `<br>`.** Asana does not support `<br>` — if the rich-text body contains `<br>`, Asana silently rejects it and stores the body as plain text, which then renders with visible HTML tags in the UI. The script defensively auto-replaces `<br>` (and `<br/>`, `<br />`) with `\n` before posting, so an accidental `<br>` won't break the comment.

### Fetch Subtasks

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>/subtasks?opt_fields=name,completed,gid"
```

### Fetch Task Stories (Comments)

Use the script — it `GET`s the task's stories, filters to `type:comment`, and returns the compact `[{author, text, created_at}]`:

```bash
scripts/tm.py comment list <task-gid>
```

Under the hood it calls `GET /tasks/<gid>/stories?opt_fields=type,text,created_by.name,created_at` and keeps only `type == "comment"` entries.

### Upload Attachment

Upload a file (screenshot, video, etc.) to a task. **`curl -F` is unreliable under the Bash sandbox** — use the script, which builds the `multipart/form-data` body in Python (urllib):

```bash
scripts/tm.py task attach <task-gid> /path/to/file.png
```

It `POST`s to `/attachments` with `parent=<task-gid>` and the file part. Supported file types include images (`.png`, `.jpg`), videos (`.mp4`), and documents. The response (attachment GID + download URL) is printed to stdout.

### List Attachments

List a task's attachments (names and download URLs):

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>/attachments?opt_fields=name,download_url"
```

### Delete Attachment

Remove an attachment from a task (e.g., before re-uploading a regenerated file so duplicates never accumulate). List the task's attachments first to find the target GID:

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>/attachments?opt_fields=name"
```

Then delete by attachment GID:

```bash
curl -s -X DELETE -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/attachments/<attachment-gid>"
```

## URL Formats and GID Extraction

Asana URLs come in several formats. The task GID is always a numeric segment:

- `https://app.asana.com/0/<project-gid>/<task-gid>`
- `https://app.asana.com/0/<project-gid>/<task-gid>/f`
- `https://app.asana.com/1/<org-gid>/project/<project-gid>/task/<task-gid>`
- `https://app.asana.com/1/<org-gid>/inbox/<inbox-gid>/item/<task-gid>/...`

## Error Handling

- **401 Unauthorized** — If using a named override token (e.g., `ASANA_TOKEN_WORK`), follow the fallback logic in Token Resolution above. If using the default `$ASANA_PERSONAL_ACCESS_TOKEN`, guide the user to regenerate at https://app.asana.com/0/my-apps.
- **403 Forbidden** — User lacks access to the resource.
- **404 Not Found** — Invalid GID or deleted resource.
- **429 Rate Limited** — Back off and retry after the `Retry-After` header.

Never silently skip a failed API call. Report the status code and error message.

## Full API Reference

For the complete list of 232 endpoints across 45 resources, consult **`references/spec-summary.md`**.
