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
- **Completed** (a.k.a. **Done**) — finished.

## How providers realize the two axes

A provider maps both axes onto its own model — one mechanism for both, or a separate mechanism per axis. `set_status(task, <name>)` resolves the name to whatever the provider uses; *how* it does so is the provider's concern, documented in the `task-manager-<provider>` skill, not in this neutral rule.

## Notes

- The two axes **coexist** — read the right one for the question at hand (pipeline position vs. is-work-underway).
- A provider may **collapse several states onto one native bucket**; callers must not assume a state survives a 1:1 round-trip.
