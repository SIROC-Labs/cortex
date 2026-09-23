# Boards (neutral)

The siroc workflow organizes tasks on three kinds of board, independent of the task manager:

- **Sprint board** — the current iteration's work. Exactly one is *active* at a time.
- **Backlog board** — longer-lived collections of not-yet-scheduled work.
- **Agent board** — one board per workspace holding work an unattended agent may pick up. Its columns are addressed by **role**, never by name.

**Active-sprint policy:** the active sprint is the current, not-yet-finished iteration. When more than one candidate qualifies, the latest-ending one wins.

How sprint vs. backlog boards are *identified*, and how the active sprint is *discovered and cached*, is provider-specific — see the active provider skill. Skills request boards by intent (`resolve_board("active sprint")`, `resolve_board("backlog")`), never by a provider-specific name pattern.

## The agent board

| Role | Meaning | Who moves cards in |
|---|---|---|
| `queue` | Ready for implementation, ordered by priority | the operator, an authoring skill |
| `in_progress` | Claimed by a run; anything here belongs to a run, and a stale card is a crashed run | the unattended run |
| `blocked` | Needs the operator: a question, a failure, a diagnosis to confirm | the unattended run |
| `in_review` | A PR is ready for review | the unattended run |
| `done` | Finished | the operator |

Roles are the contract because names collide: Product Status already uses `Ready` for near-complete work. A board created by the setup skill uses the names `Queue`, `In Progress`, `Blocked`, `In Review`, `Done`; an existing board maps its own names to the roles at setup. Skills request the board with `resolve_board("agent-queue")` and address columns as `columns[<role>]`; a move onto this board is `move_task`, never `set_status`.

**Rotation.** An agent board may be a series whose name carries a sprint number. The machine-local cache holds a name pattern whose numeric capture groups order the series; the newest board by numeric comparison of those groups is the board. Rotation detects the newest board; creating the next one is the operator's.

**Ordering.** Cards in `queue` are taken by the neutral `Priority` field, highest first, unset last, then by the provider's native order within the column.

**Dependencies.** A card waits while any card it depends on is neither completed nor at or past review. "At or past review" means the `in_review` or `done` column of the agent board, or a column with the same name as either on any other board the blocker sits on. Anything else, including an unknown column or no board at all, blocks.

Identification, caching and rotation mechanics live in the `agent-loop-setup` skill's script; the provider only realizes `list_boards`, `get_board`, `ensure_board`, `ensure_columns`, `list_tasks(board, column)`, `move_task` and `get_dependencies`.
