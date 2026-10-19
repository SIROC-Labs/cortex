# Boards (neutral)

The siroc workflow organizes tasks on three kinds of board, independent of the task manager:

- **Sprint board** — the current iteration's work. Exactly one is *active* at a time.
- **Backlog board** — longer-lived collections of not-yet-scheduled work.
- **Agent board** — one board per workspace holding work unattended agents may pick up. Several people share it; a run takes only cards that are unassigned or assigned to its user. Its columns are addressed by **role**, never by name.

**Milestones (epics) and members.** A milestone is a sprint goal: one task with a Goal, a Definition of Done and an execution order in its description, filed on its product board. Its **members** are the implementation tasks under it. Milestones and **standalone tasks** (bugs, hotfixes, milestones too small to have members) are the units added to a sprint board and moved through its columns; members never go on a sprint board, are in the sprint through their milestone, carry no estimate, and track execution in Dev Status (`lifecycle.md`). Names: milestones `E{n} — <name>`, members `E{n}.{m} — <name>`.

**Milestone branches.** Each milestone has one `milestone/<slug>` branch per repository, cut from the parent branch (usually `main`) and recorded in a **Branches** table in the milestone's description (`| Repository | Branch | Parent |`).

- `<slug>` — the milestone name without its `E{n} — ` prefix, lower-cased, non-alphanumerics collapsed to `-`, trimmed; the same in every repository (`E3 — Development environment` → `development-environment`).
- **Repository** cell — `<org>/<repo>`, matched against the `origin` remote's `<org>/<repo>`; a bare `<repo>` matches the current repository's name.
- **Creating a missing row** — `git fetch origin <parent>`, `git push origin origin/<parent>:refs/heads/milestone/<slug>` (reuse the branch when it already exists on `origin`), then add `` | <org>/<repo> | `milestone/<slug>` | `<parent>` | `` to the table with `set_description`, under a `## Branches` heading when there is none, leaving the rest of the description unchanged. A row whose branch is missing on `origin` is an error to report, never recreated. A member's branch is cut from the milestone branch and its PR targets it; it merges there without the owner's review unless its Dev Status is Owner Review. When every member is completed the milestone moves to To QA and its branch's PR into the parent opens; merging that PR after human QA is the owner's.

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

**Dependencies.** A card waits while any card it depends on is neither completed nor merged. "Merged" means the `ready` or `done` column of the agent board, or a column with the same name as one of them on any other board the blocker sits on. `in_review` does not count: the blocker's PR is open and its work is not yet on the milestone branch a dependent builds from. Anything else, including an unknown column or no board at all, blocks.

**Milestones.** Every authoring run creates one milestone in a project the operator names (never the agent board) and one milestone branch per repository, as above. Cards are the milestone's members, also placed on the agent board; they target that branch; the review run merges into it; merging it into its parent is the operator's.

Identification, caching and rotation mechanics live in the `agent-loop-setup` skill's script; the provider only realizes `list_boards`, `get_board`, `ensure_board`, `ensure_columns`, `list_tasks(board, column)`, `move_task` and `get_dependencies`.
