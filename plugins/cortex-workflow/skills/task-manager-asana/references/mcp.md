# Asana MCP transport

Realizes the neutral task-manager operations over an operator-connected Asana MCP server. Not a skill — referenced from `../SKILL.md` → Transport resolution. Used only when `tm.py auth status` exits 4 and this transport is callable.

**Principle:** the agent does the network, `tm.py` does the policy. Every MCP read is fed to an offline verb (`--from-json`) that applies the same classification, mapping and rendering the REST verbs apply and writes the same `~/.cortex/cortex-workflow/<key>.json` cache. Every MCP write sends a payload an offline verb planned. Never hand-write a `custom_fields` map or an HTML body.

Invoke `tm.py` as `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager-asana/scripts/tm.py`. Save each MCP result to a file in the scratch directory and pass its path, or pipe it on stdin with `-`.

## Detection

This transport is available when the tools of an Asana MCP server are callable in the current session. Check the tool list; do not call a tool to find out. A server this reference has been written against:

| Server | Tool names used below | Checked |
|---|---|---|
| claude.ai Asana connector | `get_me`, `get_task`, `get_tasks`, `create_tasks`, `update_tasks`, `add_comment`, `get_project`, `get_projects`, `update_project`, `create_project`, `search_objects`, `get_attachments`, `delete_task` | 2026-09-23 |

Any other Asana MCP server: read its tool schemas first. The table below is written in Asana API terms (`opt_fields`, `custom_fields`, `add_projects`), so mapping a differently named tool is mechanical. Record the server in this table when you do.

The connected account is the account. `ASANA_TOKEN_<NAME>` switching does not apply here.

## Rules

- **Pagination.** Every list call (`get_tasks`, `get_projects`, `get_attachments`) pages. Follow `next_page` / `offset` until exhausted and concatenate the arrays before ingesting. One page is not the population.
- **Partial success.** `create_tasks` and `update_tasks` return `succeeded` and `failed`. Any entry in `failed` is a failed operation: surface its `errors` verbatim and stop the invoking operation there. Never read a non-empty `succeeded` as success.
- **Field values.** `custom_fields` keys are field GIDs and single-select values are option GIDs. Always plan them with `fields plan`.
- **Bodies.** Comments and descriptions are authored as Markdown and rendered with `render body`. The connector rejects `<br>`, `<thead>`, `<th>` and unwrapped HTML; the verb produces the accepted shape.
- **Errors.** Surface the tool's error text verbatim, with the operation that failed. Throttling is the connector's concern.
- **Cache.** Same file, same schema as REST. `asana_token_env` is absent on a cache built here; nothing reads it in this mode.

## Bootstrap (no cache for this repo)

1. `get_me` → the user's workspaces. One → use it. Several → ask the operator which (attended runs only; an unattended run stops).
2. `get_projects(archived=false, limit=100, opt_fields="name,completed,due_on,archived")`, following `offset` until `next_page` is null; concatenate.
3. `tm.py board ingest <key> --from-json <projects.json> --workspace-gid <gid>` — `<key>` from `tm.py board key`.
4. Fields are ingested lazily on first use per project (see `list_fields`).

## Operation table

| Neutral op | MCP call(s) | Offline verb |
|---|---|---|
| `get_current_user()` | `get_me` | — |
| `find_task(ref)` | — | `tm.py ref parse <url-or-ref>` |
| `get_task(task)` | `get_task(task_id, include_comments=false, include_subtasks=false, opt_fields="gid,name,notes,resource_subtype,assignee.name,memberships.project.gid,memberships.project.name,memberships.section.gid,memberships.section.name,custom_fields.gid,custom_fields.name,custom_fields.type,custom_fields.display_value,custom_fields.enum_value.name,custom_fields.resource_subtype,dependencies.gid,permalink_url")` | `tm.py task project --from-json <task.json>` |
| `get_comments(task)` | `get_task(task_id, include_comments=true, comment_limit=50)`; keep stories with `type == "comment"` as `{author, text, created_at}` | — |
| `get_subtasks(task)` | `get_task(task_id, include_subtasks=true)` → `subtasks` | — |
| `get_attachments(task)` | `get_attachments(parent=<task>)`, paged; fetch `download_url` to read a file | — |
| `create_task(title, description, board, assignee?, fields?, kind?, milestone?)` | `render body --for notes` → `fields plan <board> Name=Value …` → `create_tasks([{name, html_notes\|notes, project_id: <board>, section_id?, assignee?, resource_subtype: "milestone"?, custom_fields?}])`. With `milestone`: `section_id` = the anchor's section from `get_task(anchor).memberships` on that board. The human key is assigned asynchronously by an Asana rule; re-read the task when it is needed | `render body`, `fields plan` |
| `delete_task(task)` | `delete_task(task_id)` | — |
| `add_to_board(task, board)` | `update_tasks([{task, add_projects: [{project_id: <board>}]}])` | — |
| `add_dependency(task, depends_on)` | `update_tasks([{task, add_dependencies: [<depends_on>]}])` | — |
| `set_parent(task, parent)` | `update_tasks([{task, parent}])` | — |
| `set_status(task, status)` | for the task's project: `get_project(project_id, include_sections=true)`; ensure fields are cached (`list_fields`); `status plan <project> <status> --sections-from-json <project.json>`; axis `field` → `update_tasks([{task, custom_fields: {field_gid: option_gid}}])`; axis `section` → `update_tasks([{task, add_projects: [{project_id, section_id}]}])` | `status plan` |
| `set_field(task, name, value)` / `set_fields(task, {…})` | ensure fields are cached for the task's project; `fields plan <project> Name=Value …`; `update_tasks([{task, custom_fields?, assignee?}])`; report `skipped` names | `fields plan` |
| `set_description(task, body)` | `render body --for notes (--body-file)` → `update_tasks([{task, html_notes\|notes}])` | `render body` |
| `add_comment(task, body)` | `render body --for comment (--body-file)` → `add_comment(task_id, html_text\|text)` | `render body` |
| `upload_attachment(task, file)` | **no MCP tool** — see Partial support | — |
| `remove_attachment(task, attachment)` | **no MCP tool** — see Partial support | — |
| `list_fields(board)` | `tm.py fields list <board> --offline`; exit 2 → `get_project(project_id=<board>, opt_fields="custom_field_settings.custom_field.gid,custom_field_settings.custom_field.name,custom_field_settings.custom_field.type,custom_field_settings.custom_field.format,custom_field_settings.custom_field.precision,custom_field_settings.custom_field.enum_options.gid,custom_field_settings.custom_field.enum_options.name")` → `tm.py fields ingest <board> --from-json <project.json>` | `fields list --offline`, `fields ingest` |
| `list_tasks(board, column?)` | `get_tasks(project=<board> \| section=<column>, opt_fields="gid,name,completed,resource_subtype,assignee.name,custom_fields.name,custom_fields.display_value,custom_fields.enum_value.name", limit=100)`, paged; per item `task project --from-json` and keep `{gid: ref, name, kind, completed, assignee, fields}` | `task project` |
| `list_milestones(board)` | `get_project(include_sections=true)`; per section `get_tasks(section=<gid>, opt_fields="gid,name,resource_subtype")`, paged; build `[{section, tasks}]` | `tm.py milestone classify --from-json <groups.json>` |
| `milestone_tasks(milestone)` | `get_task(anchor)` → its section on the board; `get_tasks(section=<gid>, opt_fields="gid,name,resource_subtype")`, paged; drop `resource_subtype == "milestone"` | — |
| `ensure_milestone(board, name)` | `get_project(include_sections=true)`; no section named `name` → `update_project(project_id, add_sections=[{name}])` then re-read; no `milestone` task in that section → `create_tasks([{name, project_id, section_id, resource_subtype: "milestone"}])`; print `{name, ref, created}`; never touch an existing anchor's description | — |
| `resolve_board(intent)` | `tm.py board key`; `tm.py board resolve <key> <active-sprint\|backlog> --offline`; exit 4 → Bootstrap above; exit 3 → repeat Bootstrap steps 2–3 (the cached `workspace_gid` is reused, so `--workspace-gid` may be omitted); exit 0 → use the printed board | `board resolve --offline`, `board ingest` |
| `list_boards()` | `get_projects(archived=false, limit=100, opt_fields="name,completed")`, paged → `[{ref: gid, name, completed}]` | — |
| `get_board(board)` | `get_project(project_id, include_sections=true)` → `{ref, name, columns: sections as [{ref: gid, name}]}` | — |
| `ensure_board(name, columns)` | `list_boards()` → exact name → reuse; else `create_project(name, default_view="board", sections=[{sectionName} …])` → `{ref, created: true}` | — |
| `ensure_columns(board, names)` | `get_project(include_sections=true)`; `update_project(project_id, add_sections=[{name} …])` for the missing names; re-read | — |
| `move_task(task, board, column)` | `update_tasks([{task, add_projects: [{project_id: <board>, section_id: <column>}]}])` | — |
| `get_dependencies(task)` | `get_task(task_id, opt_fields="dependencies.gid")`; per blocker `get_task(dep, opt_fields="name,completed,memberships.project.gid,memberships.project.name,memberships.section.gid,memberships.section.name")` → `{ref, name, completed, memberships: [{board: {ref, name}, column: {ref, name}}]}` | — |

## Partial support

Attachments have no MCP realization. Follow the partial-support rule in `../../task-manager/references/provider-guide.md`:

- **`upload_attachment(task, file)` with `file` named `implementation-plan.md`:** write the plan into the description instead. `get_task` → current `notes`; if a section headed `## Implementation plan` exists, replace it through the end of the description; otherwise append `\n\n## Implementation plan\n\n` + the file's content. Then `set_description` with the result. Consumers find it there (plan artifact convention in `plugins/cortex-workflow/references/runtime-bindings.md`). Report `attachment realized as description section`.
- **`upload_attachment` with any other file, and `remove_attachment`:** stop that operation with `MCP transport cannot upload attachments — attach <path> to <task url> manually`, then continue with the rest of the invoking operation. Never skip silently.
- **Reading attachments** works through `get_attachments` and the `download_url`. A failed download is reported, not worked around.

A description write that exceeds Asana's `html_notes` limit fails; surface the error as a partial-support stop naming the file.
