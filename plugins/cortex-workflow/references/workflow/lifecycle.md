# Workflow Lifecycle (neutral)

A task's state spans **two parallel axes**, expressed independently of any task manager. Callers use `set_status(task, <name>)` with a name from either axis; the provider realizes it (a status-field value, a board-column move, a workflow transition, …) and may use one mechanism for both axes or a separate mechanism per axis.

## Product Status — the delivery-pipeline state

The task's position in the delivery pipeline, in order:

1. **Requirements** — capturing what the work needs.
2. **Sizing** — estimating relative size.
3. **Refinement** — detailing the task into an actionable plan.
4. **Unassigned** — refined, in the backlog, not yet picked up.
5. **Scheduled** — slotted into an upcoming iteration.
6. **Assigned** — picked up by an owner; the point at which work starts.
7. **Ready** — work is complete and awaiting final validation (e.g. PM sign-off) before completion. A *near-complete* state, not a starting point.

**Cancelled** — terminal exit; the work will not proceed.

## Execution columns — where active work sits

A **separate axis** from Product Status. A task can carry a Product Status (e.g. `Assigned`) while simultaneously sitting in an execution column:

- **In Progress** — actively being worked on.
- **In Review** — implementation complete, under review.
- **To QA** — a milestone whose members are all completed, awaiting human QA on its milestone branch.
- **Completed** (a.k.a. **Done**) — finished.

Execution columns apply to the units on a sprint board: milestones and standalone tasks.

## Dev Status — a milestone member's execution state

A milestone member (see `boards.md`) never sits on a sprint board, so its execution state is the **Dev Status** field instead of a column:

- **To Do** — not started; the default for a new member.
- **In Progress** — branch and draft PR against the milestone branch exist.
- **Owner Review** — set by the owner: the PR waits for the owner's approval instead of merging on its own.
- **Blocked** — work cannot proceed.
- **Done** — merged into the milestone branch. Setting it also marks the member completed.

`set_status(member, <name>)` with a Dev Status name writes this field. A member still carries a Product Status.

## How providers realize the two axes

A provider maps both axes onto its own model — one mechanism for both, or a separate mechanism per axis. `set_status(task, <name>)` resolves the name to whatever the provider uses; *how* it does so is the provider's concern, documented in the `task-manager-<provider>` skill, not in this neutral rule.

## Notes

- The two axes **coexist** — read the right one for the question at hand (pipeline position vs. is-work-underway).
- A provider may **collapse several states onto one native bucket**; callers must not assume a state survives a 1:1 round-trip.
