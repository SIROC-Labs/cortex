---
name: task-manager-asana
version: 0.1.0
description: >
  Asana implementation of the task-manager interface. Maps neutral task operations
  (create/read/update tasks, statuses, fields, comments, attachments, boards) onto the
  Asana REST API. Invoked by the task-manager seam when the project's provider is Asana;
  not called directly by workflow skills.
---

# Task Manager — Asana provider

Implements the neutral operations defined in `../task-manager/SKILL.md` against Asana. Mechanics live in this skill's references:

- `references/rest.md` — raw REST recipes (auth, tasks, sections, comments, attachments, stories, subtasks).
- `references/custom-fields.md` — discovering field identifiers and mapping the neutral field set.
- `references/boards.md` — sprint/backlog identification, discovery, caching.
- `references/spec-summary.md` — full Asana API reference (232 endpoints) for the long tail.

## Token resolution

Resolve the Asana token exactly as in `references/rest.md` (Token Resolution): default `$ASANA_PERSONAL_ACCESS_TOKEN`, with conversational `ASANA_TOKEN_<NAME>` overrides. Session-only; nothing written to disk.

## Operation mapping

| Neutral op | Asana realization |
|---|---|
| `get_current_user()` | `scripts/tm.py user me` — `GET /users/me` (gid, name, email, workspaces) via urllib. |
| `find_task(ref)` | `scripts/tm.py ref parse <url-or-ref>` — extracts the numeric task GID from an `app.asana.com` URL (or a bare numeric id) and prints it; exits 2 (no output) when the input is not an Asana reference (`references/rest.md` → URL Formats). |
| `get_task(task)` | `scripts/tm.py task get <task-gid>` — `GET /tasks/<gid>` with the documented `opt_fields`, returning a **compact neutral projection** (`{ref,name,kind,description,assignee,status,board,fields}`; `kind` = `milestone` when `resource_subtype == "milestone"` else `task`; custom-field names mapped to canonical names, `status` = the `Product Status` value) instead of the raw blob (token win). For unusual long-tail needs, the raw `opt_fields` recipe in `references/rest.md` (Fetch Task Details) is still available. |
| `create_task(...)` | `scripts/tm.py task create <project-gid> --title T [--description D] [--assignee A] [--kind task\|milestone] [--milestone <anchor-gid>] [--set Name=Value ...] [--wait-key]` — `POST /tasks` (with `resource_subtype:"milestone"` when `--kind milestone`; no custom fields until added to a project) then `POST /tasks/<gid>/addProject`; with `--milestone` the task also joins that milestone's section (`POST /sections/<gid>/addTask`); then any `--set` fields in ONE batched `PUT`, all via urllib. Prints the compact projection. The human key is assigned by an async Asana Rule; create does **not** block on it — pass `--wait-key` only for a tight create-then-name-branch flow. Prefer `--set` over follow-up `set-field` calls. |
| `list_milestones(board)` | `scripts/tm.py milestone list <project-gid>` — one entry per section carrying a `kind=milestone` anchor: `{name, ref (anchor gid), expanded (has ≥1 member task)}`. |
| `milestone_tasks(milestone)` | `scripts/tm.py milestone tasks <project-gid> <milestone-ref>` — the milestone's member tasks (its section's non-anchor tasks). |
| `ensure_milestone(board, name)` | `scripts/tm.py milestone ensure <project-gid> <name>` — idempotent: ensures a section named `<name>` and a `kind=milestone` anchor task in it; prints `{name, ref, created}`. Never overwrites an existing anchor's description. |
| `delete_task(task)` | `scripts/tm.py task delete <task-gid>` — `DELETE /tasks/<gid>` via urllib. |
| `add_to_board(task, board)` | `scripts/tm.py task add-to-board <task-gid> <project-gid>` — `POST /tasks/<gid>/addProject` via urllib. |
| `add_dependency(task, depends_on)` | `scripts/tm.py task add-dependency <task-gid> <depends-on-gid>` — `POST /tasks/<gid>/addDependencies` with the blocking task gid via urllib (`references/rest.md`). |
| `set_parent(task, parent)` | `scripts/tm.py task set-parent <task-gid> <parent-gid>` — `POST /tasks/<gid>/setParent` via urllib (`references/rest.md`). |
| `set_status(task, status)` | `scripts/tm.py task set-status <task-gid> <status-name>` — **two-axis** (`../../../references/workflow/lifecycle.md`): tries the `Product Status` custom field FIRST (resolve via the `fields` logic; status matching an enum option → `PUT custom_fields`), then a board **section** move (discover the task's project sections; status matching a section name → `POST /sections/<gid>/addTask`). Matches neither → exit 1 (not a known Product Status option or section). All via urllib. |
| `set_field(task, field_name, value)` | `scripts/tm.py task set-field <task-gid> <CanonicalName> <value>` — resolves the field via the `fields` logic (gid/type/enums), then writes via urllib: enum → option GID (value matched by option name or gid), Estimate → unit-adaptive write (enum hh:mm option, or number in hours/minutes/duration per the field — see `references/custom-fields.md`), Assignee → the native `assignee` field (`PUT /tasks/<gid>`), other custom fields → `PUT custom_fields:{<gid>:<value>}`. Exit 2 = field not on the task's project(s), skip gracefully. |
| `set_fields(task, {field: value, …})` | `scripts/tm.py task set-fields <task-gid> <Name=Value> …` — same resolution as `set_field` but applies **all** fields in ONE `PUT` (assignee + custom_fields combined). **Prefer this when setting 2+ fields** — one round-trip instead of N. Fields not on the task's project(s) are skipped (reported on stderr); prints the compact projection. |
| `set_description(task, body)` | `scripts/tm.py task set-notes <task-gid> (<body> \| --body-file <path>)` — author the body as **Markdown**; same conversion as `add_comment` (Markdown → Asana HTML, blank lines stripped, `<br>` defended, `<body>`-wrapped), then `PUT`s `html_notes` (rich) / `notes` (plain) via urllib. Replaces the whole description. Prefer `--body-file` for large/multiline bodies. |
| `add_comment(task, body)` | `scripts/tm.py comment add <task-gid> (<body> \| --body-file <path>)` — author the body as **Markdown**; the script converts it to Asana HTML, routes it through the correct field (`text` vs `html_text`), defends against `<br>`, and `POST`s `/tasks/<gid>/stories` via urllib (sandbox-safe). Prefer `--body-file` for large/multiline bodies (`references/rest.md` → Post Comment). |
| `upload_attachment(task, path)` | `scripts/tm.py task attach <task-gid> <file-path>` — `POST /attachments` multipart (`parent=<gid>`, `file=@path`) built with urllib (sandbox-safe; replaces `curl -F`). |
| `remove_attachment(task, attachment)` | `DELETE /attachments/<attachment-gid>` (`references/rest.md`). |
| `get_subtasks(task)` | `GET /tasks/<gid>/subtasks` (`references/rest.md`). |
| `get_comments(task)` | `scripts/tm.py comment list <task-gid>` — `GET /tasks/<gid>/stories` filtered to `type:comment`, returns the compact `[{author, text, created_at}]` (`references/rest.md` → Fetch Task Stories). |
| `get_attachments(task)` | `GET /tasks/<gid>/attachments` (`references/rest.md`). |
| `list_fields(board)` | `scripts/tm.py fields list <project-gid>` — code-enforced discovery + name→GID mapping (cache-first, discover-on-miss + write-back); returns the compact canonical field map. Force a refresh with `scripts/tm.py fields discover <project-gid>`. Rules in `references/custom-fields.md`. |
| `list_tasks(board)` | `scripts/tm.py task list <project-gid>` — `GET /projects/<gid>/tasks` (paginated), compact `{gid,name,kind,completed}` per task (`kind` from `resource_subtype`), via urllib. |
| `resolve_board(intent)` | **Hard gate — cache-first, never manual discovery on a hit.** FIRST, MANDATORY action: derive the key via `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager-asana/scripts/tm.py board key`, then run `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager-asana/scripts/tm.py board resolve <key> <intent>` (intent ∈ `active-sprint`/`backlog`). It reads cache-first, auto-refreshes only when the sprint is stale, and signals miss/bootstrap via exit code. Do **NOT** issue manual project-list queries when the script returns a board. Live discovery happens only via the script's `board discover` path on a genuine miss (exit 4 = bootstrap: resolve workspace + token env per `references/boards.md`, `board write` them, then `board discover`), and it writes back. Classification/discovery rules + schema live in `references/boards.md`. |

For operations not in the table, use `references/spec-summary.md` directly — this is the provider-coupled long-tail path.

## Errors

Follow `references/rest.md` (Error Handling): 401 → token fallback/regenerate, 403/404 → report, 429 → back off per `Retry-After`. Never silently skip a failed call.
