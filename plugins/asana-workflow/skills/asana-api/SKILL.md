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

Use `asana-post-comment.py <task-gid> "<body>"`. The script inspects the body, routes it through the correct Asana API field (`text` or `html_text`), and validates the payload locally before posting. Author the body as plain text or as Asana HTML — no field selection or wrapping is needed at the call site.

**Markdown is not supported by Asana.** If the source content is in Markdown (e.g., the user pasted Markdown, or another skill produced a Markdown-formatted summary), convert it to Asana HTML before invoking the script. Sending raw Markdown produces literal asterisks, backticks, and bracket characters in the rendered comment. Common conversions:

| Markdown | Asana HTML |
|---|---|
| `**bold**` | `<strong>bold</strong>` |
| `*italic*` or `_italic_` | `<em>italic</em>` |
| `` `code` `` | `<code>code</code>` |
| `[text](url)` | `<a href="url">text</a>` |
| `- item` / `* item` (bullet list) | `<ul><li>item</li></ul>` |
| `1. item` (numbered list) | `<ol><li>item</li></ol>` |
| ` ```code block``` ` | `<pre><code>code block</code></pre>` |
| `# Heading` | `<h1>Heading</h1>` (or `<strong>Heading</strong>` for lighter weight) |

For mixed-format input (e.g., a Markdown bullet list embedded in plain prose), convert the entire body to HTML — once any HTML tag is present, the body must be coherent HTML throughout.

**Line breaks in rich text use literal `\n`, not `<br>`.** Asana does not support `<br>` — if the rich-text body contains `<br>`, Asana silently rejects it and stores the body as plain text, which then renders with visible HTML tags in the UI. The script defensively auto-replaces `<br>` (and `<br/>`, `<br />`) with `\n` before posting, so accidentally including a `<br>` won't break the comment — but authoring the body with `\n` directly is cleaner.

**Invocation:** invoke by bare command name only — `asana-post-comment.py`, not `python3 asana-post-comment.py` and not a constructed path. The script is shipped in this plugin's `bin/` directory, which Claude Code automatically prepends to `PATH`; it has a `#!/usr/bin/env python3` shebang and is marked executable, so the bare-name invocation runs it directly. Do **not** construct a path from the skill's base directory or from anywhere else — the script is not co-located with `SKILL.md`.

Run `asana-post-comment.py --help` for the full behaviour spec.

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
