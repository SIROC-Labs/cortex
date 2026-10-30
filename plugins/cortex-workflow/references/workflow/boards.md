# Boards (neutral)

The siroc workflow organizes tasks on three kinds of board, independent of the task manager:

- **Sprint board** — the current iteration's work. Exactly one is *active* at a time.
- **Backlog board** — longer-lived collections of not-yet-scheduled work.
- **Agent board** — one board per workspace holding work unattended agents may pick up. Several people share it; a run takes only cards that are unassigned or assigned to its user. Its columns are addressed by **role**, never by name.

**Active-sprint policy:** the active sprint is the current, not-yet-finished iteration. When more than one candidate qualifies, the latest-ending one wins.

How sprint vs. backlog boards are *identified*, and how the active sprint is *discovered and cached*, is provider-specific — see the active provider skill. Skills request boards by intent (`resolve_board("active sprint")`, `resolve_board("backlog")`), never by a provider-specific name pattern.

## The agent board

| Role | Meaning | Who moves cards in |
|---|---|---|
| `queue` | Ready for implementation or rework, ordered by priority | the operator, an authoring skill, the review run handing a card back |
| `in_progress` | Claimed by a build run; a card here assigned to this user with no live run is a crashed run, one assigned to someone else is theirs | the build run |
| `blocked` | Needs the operator: a question, a failure, a refusal to confirm | the build run, the review run |
| `in_review` | A PR awaits the review run | the build run |
| `ready` | Reviewed and squash-merged into its milestone branch, not yet released | the review run |
| `done` | Finished | the operator |

Roles are the contract because names collide: Product Status already uses `Ready` for near-complete work. A board created by the setup skill uses the names `Queue`, `In Progress`, `Blocked`, `In Review`, `Ready`, `Done`; an existing board maps its own names to the roles at setup. Skills request the board with `resolve_board("agent-queue")` and address columns as `columns[<role>]`; a move onto this board is `move_task`, never `set_status`.

**Rotation.** An agent board may be a series whose name carries a sprint number. The machine-local cache holds a name pattern whose numeric capture groups order the series; the newest board by numeric comparison of those groups is the board. Rotation detects the newest board; creating the next one is the operator's.

**Ordering.** Cards in `queue` are taken by the neutral `Priority` field, highest first, unset last, then by the provider's native order within the column.

**Dependencies.** A card waits while any card it depends on is neither completed nor merged. A milestone's work item is merged exactly when it is completed. "Merged" means the `ready` or `done` column of the agent board, or a column with the same name as one of them on any other board the blocker sits on. `in_review` does not count: the blocker's PR is open and its work is not yet on the milestone branch a dependent builds from. Anything else, including an unknown column or no board at all, blocks.

**Milestones.** Two kinds of card sit on the agent board: a single task, and a milestone — a milestone-kind card that travels the columns as one. A milestone's cards are its **work items**, created with `create_task(…, milestone=…)` and never members of the agent board: no `move_task`, no column. A work item may sit on its product board for its key and fields. Its state is read in place, and nothing else records it:

| State | Read from |
|---|---|
| waiting | open and unassigned |
| held | open and assigned; the latest `🤖` comment names the step — `started`, `Ready for review` with its PR, `Needs clarification`, `Blocked` |
| merged | completed: squash-merged into the milestone branch |

The milestone's description keeps a `## Cards` table (Ref, Title, Repo, State, PR); whoever changes a work item's state updates its row in the same step. The milestone's column is the aggregate of its work items: `blocked` while a held one's latest marker is `Needs clarification` or `Blocked`, `ready` once all are complete, `queue` until the first claim (none held, none complete, none carrying a `🤖` marker), `in_progress` from then on — merged work with nothing in flight stays `in_progress`; never `in_review`, since review happens per work item. A milestone whose `Executor` is `Agent` opens its open, unassigned work items to the build run; one assigned to a person is out of the loop. Single tasks keep the column flow above.

Every authoring run creates one milestone on the agent board and one `milestone/<slug>` branch per repository. Its work items target that branch; the review run merges into it; merging it into its parent is the operator's.

Identification, caching, rotation, candidate order and the milestone aggregate live in the `agent-loop-setup` skill's script; the provider only realizes `list_boards`, `get_board`, `ensure_board`, `ensure_columns`, `list_tasks(board, column)`, `move_task`, `milestone_tasks`, `get_comments` and `get_dependencies`.
