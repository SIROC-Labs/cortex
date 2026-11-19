# Runtime Bindings

Maps the abstract capabilities this plugin's skills need to the concrete skill that provides them in each supported runtime. Skills reference capabilities, never skill names from other plugins. This table is the single place where that mapping lives for the `dev-toolkit` plugin.

## Capabilities

- **`MANAGE_TASKS`** — read and write the project's task manager through neutral operations: `get_current_user()`, `resolve_board(intent)` (`"active sprint"`, `"backlog"`, or a board URL/name), `list_fields(board)`, `create_task(title, description, assignee?)`, `add_to_board(task, board)`, `set_field(task, field_name, value)`, `set_status(task, status)`, `get_task(task)`.
- **`START_TASK`** — begin development on an existing task, given its URL.
- **`SHIP_WORK`** — ship committed work on a branch: push, open the PR, and update the task.

## Bindings

| Capability | Claude Code | OpenCode | Codex |
|---|---|---|---|
| `MANAGE_TASKS` | — | — | — |
| `START_TASK` | — | — | — |
| `SHIP_WORK` | — | — | — |

**Resolution rules:**
- `MANAGE_TASKS`: go through the bound skill's neutral operations. Never call a task-tracking provider or its API directly from a skill.
- **Missing binding is not a blocker.**
  - `MANAGE_TASKS`: realize the same operations with whatever task-manager tooling the session has (a connector, a CLI). If there is none, show the user the confirmed draft and ask them to create the task and paste back its URL and ID.
  - `START_TASK`: tell the user the task is logged and give them its URL. Do not start the work.
  - `SHIP_WORK`: stop after the local commit and tell the user the branch and worktree path. Do not push or open a PR.
