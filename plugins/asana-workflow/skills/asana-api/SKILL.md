---
name: asana-api
version: 0.1.0
description: >
  Operate with Asana API - create, read, update tasks, projects, users, and all Asana resources
  using the node-asana SDK or direct REST calls. Use when the user mentions Asana tasks, projects,
  workspaces, or any Asana operations.
---

# Asana API

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

### Create Task

**Do NOT include `custom_fields` in this call** — the Asana API rejects them until the task belongs to a project. Set custom fields via **Update Custom Field** after adding to a project.

```bash
curl -s -X POST -H "Authorization: Bearer $ASANA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "name": "<title>",
      "notes": "<description>",
      "workspace": "<workspace_gid>",
      "assignee": "<user_gid or null>"
    }
  }' \
  "https://app.asana.com/api/1.0/tasks"
```

Save the returned `gid` as `<task_gid>`.

### Add Task to Project

```bash
curl -s -X POST -H "Authorization: Bearer $ASANA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"data":{"project":"<project-gid>"}}' \
  "https://app.asana.com/api/1.0/tasks/<task-gid>/addProject"
```

A task can belong to multiple projects — call this once per project.

### Fetch Task Details

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>?opt_fields=name,notes,assignee,assignee.name,custom_fields,custom_fields.name,custom_fields.display_value,custom_fields.enum_value,custom_fields.enum_value.name,custom_fields.type,memberships,memberships.project,memberships.project.name,memberships.section,memberships.section.name,projects,projects.name"
```

### Move Task to Section

Move tasks between board columns (e.g., "In Progress", "In Review"):

1. List sections in the project:
   ```bash
   curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
     "https://app.asana.com/api/1.0/projects/<project-gid>/sections?opt_fields=name"
   ```

2. Find the target section by name, then move:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $ASANA_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"data":{"task":"<task-gid>"}}' \
     "https://app.asana.com/api/1.0/sections/<section-gid>/addTask"
   ```

### Update Custom Field

```bash
curl -s -X PUT -H "Authorization: Bearer $ASANA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"data":{"custom_fields":{"<field-gid>":"<value>"}}}' \
  "https://app.asana.com/api/1.0/tasks/<task-gid>"
```

For enum fields, the value is the enum option GID.

### Post Comment on Task

**Always use the bundled `asana-post-comment.sh` wrapper. Do not POST `/tasks/<gid>/stories` directly with curl.**

The wrapper exists because Asana's stories endpoint has two mutually-exclusive body fields (`text` and `html_text`) whose shape rules are easy to get wrong — past sessions have repeatedly posted HTML into `text` (which renders as literal angle brackets in the UI) or sent `html_text` without the required `<body>` wrapper (which Asana rejects). The wrapper validates the body shape against the field locally and only POSTs if the payload is well-formed. Routing every comment through it makes the broken-payload bug structurally impossible.

The wrapper lives in the plugin's `bin/` directory, which Claude Code adds to `PATH` automatically — call it by bare command name, no path prefix needed.

**Plain text comment:**

```bash
asana-post-comment.sh <task-gid> --text "🏁 Starting work — branch: MT251-47/foo
Draft PR: https://github.com/owner/repo/pull/N"
```

URLs are auto-linked by Asana. Use `--text` whenever the comment has no formatting beyond line breaks and links — for example the 🏁 start comment and the 🤖 Done ship summary.

**Rich-text comment:**

```bash
asana-post-comment.sh <task-gid> --html-text "<body><strong>✅ QA Verification — Feature Complete</strong><br><br><strong>What was verified</strong><ul><li>Item one</li><li>Item two</li></ul></body>"
```

Use `--html-text` whenever the comment needs bold, italics, lists, code spans, or links rendered as anchor text. The body must be wrapped in `<body>...</body>` (the wrapper enforces this; Asana rejects unwrapped rich text). Supported tags inside: `<strong>`, `<em>`, `<u>`, `<s>`, `<code>`, `<a href="...">`, `<ul><li>`, `<ol><li>`, `<br>`, `<h1>`–`<h2>`.

When constructing the body, escape any user-supplied content that may contain `<`, `>`, or `&` (e.g., code samples) so it does not break the markup.

**Exit codes:**

| Exit | Meaning |
|---|---|
| `0` | Comment posted; story GID printed to stdout |
| `1` | Invalid usage, missing token, or Asana API failure |
| `2` | `--text` body contained HTML tags — switch to `--html-text` |
| `3` | `--html-text` body missing `<body>...</body>` wrapper |
| `4` | Both `--text` and `--html-text` supplied (mutually exclusive) |
| `5` | Neither `--text` nor `--html-text` supplied |

A non-zero exit means the comment was **not** posted. Fix the body shape and retry — do not fall back to raw curl. If the wrapper's checks are wrong for a legitimate case, fix the wrapper, not the calling code.

The wrapper uses the same token resolution as the rest of this skill (`$ASANA_TOKEN` if set, otherwise `$ASANA_PERSONAL_ACCESS_TOKEN`).

### Fetch Subtasks

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>/subtasks?opt_fields=name,completed,gid"
```

### Fetch Task Stories (Comments)

```bash
curl -s -H "Authorization: Bearer $ASANA_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task-gid>/stories?opt_fields=type,text,created_by.name,created_at"
```

Filter results for `type: "comment"` to get human-written comments.

### Upload Attachment

Upload a file (screenshot, video, etc.) to a task:

```bash
curl -s -X POST -H "Authorization: Bearer $ASANA_TOKEN" \
  -F "parent=<task-gid>" \
  -F "file=@/path/to/file.png" \
  "https://app.asana.com/api/1.0/attachments"
```

Supported file types include images (`.png`, `.jpg`), videos (`.mp4`), and documents. The `parent` field is the task GID. The response includes the attachment GID and download URL.

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
