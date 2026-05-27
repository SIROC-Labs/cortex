---
name: refine-tasks
description: >
  Turns Refinement-status Asana tasks into one-shotters. Given any input that
  resolves to a deterministic set of Asana tasks (task URLs, a milestone/section
  in a project, a project URL, or a user-described filter), reads the codebase,
  resolves ambiguities, composes a detailed implementation plan per task,
  attaches it as implementation-plan.md, revises the estimate, and transitions
  the task from Refinement to Unassigned. Triggers: "refine these tasks",
  "/refine-tasks", "refine M1", "refine milestone X", or providing one or more
  Asana task URLs alongside a request to detail / spec / plan them. Do NOT
  trigger to create new tasks (that's submit-breakdown) or to start
  implementing a task (that's start-task).
---

# Refine Tasks

Take a deterministic set of Asana tasks in **Refinement** product status and produce a codebase-informed implementation plan for each. The plan is attached to the task as `implementation-plan.md`, the estimate is revised based on real code analysis, and the task transitions to **Unassigned** so it is ready for staffing.

This skill is the bridge between strategic decomposition (`task-breakdown` + `submit-breakdown`, which produce Refinement tasks) and execution (`start-task`, which consumes refined tasks).

## Prerequisites

- `asana-api` skill for all Asana API operations — route every call through it, no raw curl.
- Access to the codebase the tasks are about (refine-tasks reads source files to ground the plan in real paths and patterns).
- At least one Asana task in `Refinement` status that the user wants refined.

## Input

Any input that resolves to a deterministic, ordered list of Asana task GIDs. Accepted shapes:

- One or more Asana task URLs (e.g., `https://app.asana.com/0/<project>/<task>`).
- A project URL plus a milestone (section) name — e.g., "refine M1" or "refine the Core Data Layer milestone".
- A project URL alone — implies "every task in Refinement status in this project".
- A project URL plus a user-described filter — e.g., "all backend Refinement tasks in M2".

Read **`references/input-resolution.md`** for the resolution rules and the exact prompts to use when the input is ambiguous.

Whatever the input, **confirm the resolved set with the user before proceeding**:

> About to refine 4 tasks (in dependency order):
>   1. Employee entity + repository
>   2. Employee CRUD API endpoints
>   3. Employee list page
>   4. Employee create/edit form
> Proceed? [Y/n]

## Strict state filter

A task is eligible for refinement **only if Product Status = Refinement**. Any task in another status is refused (logged and skipped, not silently passed through). This makes the lifecycle one-directional and avoids ambiguity about "re-refinement" or "downgrade from Unassigned."

If the user wants to re-refine a task, they must first change its status back to Refinement manually. This skill does not perform that transition.

---

## Phase 1: Resolve and confirm task set

1. Parse the user's input and resolve to a list of Asana task GIDs (see `references/input-resolution.md`).
2. Fetch each task's Product Status custom field. Filter to `Refinement` only. For tasks in any other status, log:
   > Skipped "<title>" — status is `<status>`, not Refinement.
3. Order the remaining tasks topologically by their Asana dependencies (so dependencies appear before dependents).
4. Present the confirmation prompt above. On `n`, abort. On `Y`, proceed.

## Phase 2: Discovery

### 2a. Asana discovery

- Discover Product Status custom field GIDs for `Refinement` and `Unassigned` by name (never hardcode option GIDs). See `references/asana-custom-field-discovery.md` (plugin-level shared reference).
- Discover the Estimate custom field GID.

### 2b. Per-task context

Read each task's full Asana description. It already contains Purpose, Description, Scope, Acceptance Criteria, Dependencies, and the aggregated References list — that's the contract `submit-breakdown` provides. No external file lookup is needed.

### 2c. Codebase

Follow the References on each task to read specs, CLAUDE.md files, and source files. Explore the source tree (`ls` key directories), identify exemplar files for the patterns the tasks will follow, and confirm any file paths that will appear in the implementation plan actually exist (or are clearly new files this task creates per convention).

---

## Phase 3: Per-task processing (in dependency order)

For each Refinement task, run these steps:

### 3a. Challenge the spec and resolve ambiguities

This is the **only phase where you interact with the user** during refinement. Use it. The implementation plan is only as good as the assumptions baked into it, and the user is the one who knows which assumptions are load-bearing.

For each task, **proactively** probe across these categories. The breakdown task description and the codebase rarely cover all of them — most tasks have at least one unresolved question worth confirming.

1. **Scope edges** — cases the task description didn't mention: empty inputs, error inputs, partial data, very large inputs, concurrent access, idempotency.
2. **Pattern selection** — when multiple existing patterns in the codebase could apply (e.g., two different form libraries, two different state-management approaches), which one does this task follow?
3. **UX / behavior** — for user-facing tasks: loading states, error states, empty states, success feedback, validation feedback, optimistic vs server-confirmed UI.
4. **Naming and structure** — file/module names, type names, route paths that match codebase conventions but the breakdown didn't pin down.
5. **Migration / backwards compatibility** — when modifying existing code: keep old behavior, deprecate, hard-cut? Is there data to migrate?
6. **Test scope** — what level of coverage is expected (unit, integration, e2e); which specific scenarios are non-negotiable.
7. **Trade-offs** — explicit choice points the implementer would otherwise make alone (simplicity vs exhaustiveness, performance vs readability, MVP vs complete feature).

**Batch every question for one task into a single prompt** to the user. Don't drip-feed.

**Default to asking at least one question per task.** If you are about to skip the prompt entirely, first state which of the 7 categories you verified against the codebase / spec and why no question is needed in each. If that statement feels uncomfortable to write, that's a signal there's a question worth asking after all.

Example batched prompt:

> Before refining "Employee list page", confirm:
>
> 1. **Scope edge:** Should the list paginate (and at what page size), or render all employees? The spec didn't say.
> 2. **Pattern:** The codebase has `src/lib/data-table.tsx` (custom) and the `@radix/data-table` pattern in `src/lib/projects-table.tsx`. Use the custom one for consistency with Projects list?
> 3. **Empty state:** Show a "No employees yet" placeholder, or hide the list entirely when empty?
> 4. **Loading state:** Skeleton rows, or a spinner overlay?
>
> Answer 1–4, or "all default" to let me pick reasonable defaults from the codebase patterns.

### 3b. Compose the implementation plan

Generate the `implementation-plan.md` content for this task. Use **`references/implementation-plan-template.md`** for the full structure, content rules, and self-review checklist.

The template is inspired by the `superpowers:writing-plans` skill — plans are checkbox-tracked, code-explicit, and TDD-first where the task has testable behavior. High-level structure:

- **Header** — `# <Task title>`, Asana URL, milestone, verbatim Purpose. **Never use T-labels in the plan** — they are breakdown-internal identifiers.
- **Files** — `Create` / `Modify` / `Reference` paths grouped by action; every path real
- **Step-by-step plan** — `- [ ]` checkbox steps, 2–5 minutes each, with the actual code/commands to run and the expected outcome. For testable behavior, use TDD order (write failing test → verify fails → implement → verify passes → commit).
- **Patterns to follow** — cross-cutting exemplars too broad to inline in a step
- **Acceptance criteria mapping** — table tying each acceptance criterion to the step(s) that verify it
- **Edge cases** — non-happy-path expectations
- **References** — every source consulted

### 3c. Revise the estimate

Recompute the estimate based on the codebase-informed view (number of files, exemplar availability, design decisions, edge cases). Use the same `hh:mm` quarter-hour format and the calibration anchors in `references/decomposition-principles.md` → "Rough Estimation" (in the task-breakdown skill — the calibration is shared).

If the revised estimate differs from the rough estimate by more than 25%, display the delta in the progress report:

> Refined "Employee list page": estimate 02:15 (was 01:30, +50%), plan attached

### 3d. Upload as Asana attachment

Upload the markdown content as an attachment on the task:

- Filename: `implementation-plan.md`
- Mime type: `text/markdown`
- Endpoint: `POST /tasks/<task_gid>/attachments` (via the `asana-api` skill)

**Replacement on re-run.** Before uploading, list the task's existing attachments. If an attachment named `implementation-plan.md` already exists, delete it first (DELETE `/attachments/<attachment_gid>`). Never accumulate duplicate plans.

### 3e. Update the Estimate custom field

Set the Estimate custom field to the revised value (decimal hours).

### 3f. Move Product Status

Update the task's Product Status custom field from `Refinement` to `Unassigned` using the enum option GIDs resolved in Phase 2a.

### 3g. Progress report

Single-line report per task:

> Refined "Employee list page": estimate 02:15 (was 01:30), plan attached

---

## Phase 4: Summary

After processing all tasks, present a summary table and link to the project board:

```
Refined 4 tasks:
  1. Employee entity + repository      01:30 → 01:45  Unassigned
  2. Employee CRUD API endpoints       02:00 → 02:30  Unassigned
  3. Employee list page                02:30 → 02:30  Unassigned
  4. Employee create/edit form         02:45 → 03:00  Unassigned

Project: https://app.asana.com/0/<project_gid>/
Next step: run `/start-task <task-url>` on any of these.
```

If any tasks were skipped due to wrong status, list them at the end.

---

## Behavior at edges

- **Dependency task still in Refinement when refining a dependent.** Warn the user: the dependent's plan can reference the dependency's task description but not its (nonexistent) implementation plan. Allow proceeding or include the dependency in this run.
- **A reference URL in the task description is unreachable.** Surface to the user; allow proceeding (the plan notes the missing source) or aborting.
- **Re-run mid-failure.** Per-task work is effectively atomic: if attachment upload succeeds but the status move fails, the task remains in Refinement; a re-run replaces the now-stale attachment and tries again.
- **Custom field discovery fails.** If `Refinement` or `Unassigned` enum option cannot be resolved by name on the Product Status field, abort with:
  > Product Status field on this project does not have the required enum options (`Refinement`, `Unassigned`). Confirm both are present, then re-run.

---

## What This Skill Does NOT Do

- Does not create new Asana tasks (that's `submit-breakdown`)
- Does not move tasks beyond Unassigned (Scheduled / Assigned / Ready are PM concerns)
- Does not write code or scaffold projects (that's `start-task` and its routed sub-skills)
- Does not generate plans for tasks in any status other than Refinement

## Reference Files

- **`references/input-resolution.md`** — how to interpret each input shape into a deterministic GID list
- **`references/implementation-plan-template.md`** — structure and content rules for the attached `implementation-plan.md`

## Related Skills

- `task-breakdown` — produces the breakdown with rough estimates and validation
- `submit-breakdown` — uploads the breakdown to Asana with Product Status = Refinement
- `start-task` — consumes refined tasks; downloads `implementation-plan.md` as part of its task-context bundle
- `asana-api` — all Asana API operations route through this skill
