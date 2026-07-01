---
name: task-manager
version: 0.1.0
description: >
  Neutral interface to the project's task manager (Asana, Jira, etc.). Other skills
  perform all task operations through this seam — create/read/update tasks, statuses,
  fields, comments, and attachments — without naming a specific provider. Use whenever
  a workflow needs to read or write a task, ticket, or issue.
---

# Task Manager (interface)

The single seam between workflow skills and whatever task manager a project uses. Callers invoke the **neutral operations** below; this skill resolves the active provider and delegates the mechanics to it. Callers never name a provider, an endpoint, or an identifier.

## Resolution (do this once per session)

Run the seam's resolver — never inspect the cache by hand, and never "guess vs ask". Resolution is **detection-only**: the resolver layers cached marker → task-URL detection → ask (there is no committed selector file).

```bash
${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager/scripts/resolve_provider.py [--url <task-url-or-ref>]
```

Pass `--url` whenever the operator provides a task URL/id (it lets the resolver detect the provider from the link). It prints the provider on stdout and the resolution source on stderr. Branch on the **exit code**:

- **0** → use the printed provider; cache it for the rest of the session. When stderr says `source=detected`, the resolver has already persisted the provider marker to the per-repo cache — nothing more to do.
- **3** → conflict: the cached provider and the URL-detected provider disagree (both printed on stderr). Surface both to the operator and let them choose; do not silently pick. Persist their choice with `resolve_provider.py --set <provider>`.
- **4** → nothing to go on (no cached marker, no URL). Ask the operator which task manager this project uses, then persist it with `resolve_provider.py --set <provider>`. Do not guess.
- **1** → resolver error; surface it.

Then, for all operations, load and follow `task-manager-<provider>` (e.g. `task-manager-asana`) — it implements the operations below. `find_task(ref)` is realized by the resolved provider's `scripts/tm.py ref parse <url-or-ref>` (canonical ref on stdout, exit 0 recognized / exit 2 not this provider's).

## Neutral operations (open, semantic contract)

Describe intent; the provider fills the specifics. This list is the **common path**, not a closed API — extend it by editing this section when a genuinely neutral need appears. Anything not covered here is reachable through the provider's native capability (a provider-coupled path, used deliberately and rarely).

- `get_current_user()` — the authenticated user.
- `find_task(ref)` — resolve a URL or id to a task handle.
- `get_task(task)` — name, description, assignee, fields, status, board membership.
- `create_task(title, description, board?, assignee?, fields?)` — `fields` is an optional map of `field_name → value` (from `references/workflow/fields.md`) applied at creation in one shot.
- `delete_task(task)` — permanently remove a task.
- `add_to_board(task, board)`
- `add_dependency(task, depends_on)` — mark `task` as blocked by / dependent on another task. The native relationship/link **type** (e.g. Jira "Blocks") may be provider-configured.
- `set_parent(task, parent)` — set the task's parent / add it to an epic (hierarchy write).
- `set_status(task, status)` — `status` is a name from `references/workflow/lifecycle.md`.
- `set_field(task, field_name, value)` — `field_name` from `references/workflow/fields.md`.
- `set_fields(task, {field_name: value, …})` — set multiple fields at once; **prefer over repeated `set_field` when setting 2+ fields** (providers apply them in a single write). Fields a provider can't address are skipped/surfaced, never silently wrong.
- `set_description(task, body)` — replace the task's description; author `body` as Markdown (the provider converts). The editing counterpart to `create_task`'s `description`.
- `add_comment(task, body)` — author `body` as Markdown; the provider converts.
- `upload_attachment(task, file_path)` / `remove_attachment(task, attachment)`
- `get_subtasks(task)` / `get_comments(task)` / `get_attachments(task)` — list a task's subtasks / comments / attachments.
- `list_fields(board)` — canonical fields available on a board.
- `list_tasks(board)` — enumerate the tasks on a board/sprint.
- `resolve_board(intent)` — e.g. `"active sprint"`, `"backlog"` (policy in `references/workflow/boards.md`).

## Rules

- Operate only through the resolved provider; never call a task manager's API directly from a caller.
- Field names and status names come from the neutral workflow references, not from provider terms.
- Surface provider errors faithfully (status code + message); never silently skip a failed operation.

To add a new provider, see `references/provider-guide.md`.
