# Runtime Bindings

Maps the abstract capabilities this plugin's skills need to the concrete skill that provides them in each supported runtime. Skills reference capabilities, never skill names from other plugins. This table is the single place where that mapping lives for the `product` plugin.

## Capabilities

- **`READ_TASK`** — resolve a task or project reference (URL or id) in the project's task manager and read it: the task itself plus its subtasks, comments, and attachments as needed. Read-only.
- **`RUN_INTERVIEW`** — run a structured interview with the user: one question at a time, multiple-choice with a recommended option.

## Bindings

| Capability | Claude Code | OpenCode | Codex |
|---|---|---|---|
| `READ_TASK` | — | — | — |
| `RUN_INTERVIEW` | `superpowers:brainstorming` | `superpowers:brainstorming` | `superpowers:brainstorming` |

**Resolution rules:**
- `READ_TASK`: go through the bound skill's neutral operations. Never call a task-tracking provider or its API directly.
- **Missing binding is not a blocker.**
  - `READ_TASK`: tell the user the task cannot be fetched and ask them to paste or export its content, then continue with that as the source.
  - `RUN_INTERVIEW`: run the interview directly with the same mechanic.
