---
name: refine-tasks
description: >
  Standalone, ad-hoc refinement path for Refinement-status Asana tasks that did
  NOT come through `task-breakdown` (which now produces implementation plans
  inline). Turns Refinement-status Asana tasks into one-shotters. Given any
  input that resolves to a deterministic set of Asana tasks (task URLs, a
  milestone/section in a project, a project URL, or a user-described filter),
  reads the codebase, resolves ambiguities, composes a detailed implementation
  plan per task, attaches it as implementation-plan.md, and transitions the
  task from Refinement to Unassigned. Triggers: "refine these tasks",
  "/refine-tasks", "refine M1", "refine milestone X", or providing one or more
  Asana task URLs alongside a request to detail / spec / plan them. Do NOT
  trigger to create new Asana tasks, or to start implementing / executing
  a task.
---

# Refine Tasks

`task-breakdown` now generates per-task `implementation-plan.md` files inline, so tasks created through it land in Asana already at **Unassigned** with a plan attached. This skill exists for the **ad-hoc later refinement** path: Refinement-status tasks that did not come through `task-breakdown` — manual `log-task` creations, hand-edited descriptions, legacy pre-inline-plan tasks, or tasks the user explicitly wants re-refined.

Take a deterministic set of Asana tasks in **Refinement** product status and produce a codebase-informed implementation plan for each. The plan is attached to the task as `implementation-plan.md` and the task transitions to **Unassigned** so it is ready for staffing.

The skill operates on Asana tasks in **Refinement** status — typically produced upstream by a planning/upload workflow — and produces tasks in **Unassigned** status with two artifacts attached to the task:

1. **`implementation-plan.md`** — a detailed code-free plan attached as a file, written for the downstream agent (or human) that will implement the task.
2. **A "Refinement summary" Asana comment** — a short, human-readable digest of decisions made during refinement (resolved ambiguities, pattern choices, edge cases), written for followers watching the task in Asana. Carries no implementation-bearing content.

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
2. Fetch each task's Product Status **and Platform** custom fields. Apply two filters:
   - **Status filter** — keep only tasks where Product Status is `Refinement`. For tasks in any other status, log:
     > Skipped "<title>" — status is `<status>`, not Refinement.
   - **Platform filter** — skip tasks where Platform is `Design`. Design work (Figma files, wireframes, design specs) is produced by humans, not Claude; flag each skipped Design task prominently so the user can route it through the design workflow:
     > ⚠ Skipped "<title>" — Platform is Design. Design tasks aren't refined by Claude. Design tasks should normally go straight to Unassigned (design work — Figma files, wireframes, design specs — is produced by humans); this one is in Refinement because it was moved there manually. Either revert it to Unassigned or change its Platform if that's wrong.
3. Order the remaining tasks topologically by their Asana dependencies (so dependencies appear before dependents).
4. Present the confirmation prompt above. On `n`, abort. On `Y`, proceed.

## Phase 2: Discovery

### 2a. Asana discovery

- Discover Product Status custom field GIDs for `Refinement` and `Unassigned` by name (never hardcode option GIDs). See `references/asana-custom-field-discovery.md` (plugin-level shared reference).

### 2b. Per-task context

Read each task's full Asana description. A properly-prepared task already contains Purpose, Description, Acceptance Criteria, an optional Out of scope, and an aggregated References list — that's the input contract refine-tasks expects. No external file lookup is needed; if the description is missing any of these fields, surface that to the user and ask whether to proceed anyway or abort the task.

### 2c. Codebase

Follow the References on each task to read specs, CLAUDE.md files, and source files. Explore the source tree (`ls` key directories), identify exemplar files for the patterns the tasks will follow, and confirm any file paths that will appear in the implementation plan actually exist (or are clearly new files this task creates per convention).

---

## Phase 3: Per-task processing (in dependency order)

**Process one task at a time, fully, before moving to the next.** For each task in dependency order, run **all** of steps 3a → 3f end-to-end — ambiguity batch, plan composition, attachment upload, summary comment, status move, progress report — *and only then* start the next task.

Do **NOT** batch by step. Specifically, do not:

- Compose plans for all tasks first and then upload them all at the end.
- Collect ambiguity questions for every task into one mega-prompt at the start.
- Stage drafts in a temporary folder and submit them together.
- Defer status moves to a final pass.

Why serial-per-task matters:

- The user sees real-time progress and can intervene mid-batch if something looks wrong, instead of waiting for a black-box "done" at the end.
- A failure on task 5 leaves tasks 1–4 fully refined in Asana — not in a half-drafted local state.
- Each ambiguity batch is scoped to one task; the user isn't context-switching across seven tasks in a single Q&A.
- Re-runs are cheap and natural: re-running refine-tasks on the same input will skip already-Unassigned tasks and pick up wherever it stopped.

The only steps that legitimately span the whole batch are **Phase 1** (resolve the task set) and **Phase 2** (Asana + codebase discovery shared across tasks). From Phase 3 onward, each task is a self-contained unit.

For each Refinement task, in dependency order, run these steps:

### 3a. Challenge the spec and resolve ambiguities

This is the only phase where you interact with the user during refinement. The user is in the conversation and available — when an assumption is load-bearing and the codebase can't resolve it, ask. When the path is genuinely clear from the codebase, sibling tasks, or the task description, don't manufacture questions just to ask.

The framing is: *use the user when their input adds value*. Not every task has open questions; some tasks are mechanically clear from existing patterns. Trust your reading. But when you spot a real ambiguity, lean toward asking rather than guessing — a wrong assumption baked into the plan is worse than a small interruption.

Scan these categories for genuine open questions on each task:

1. **Scope edges** — cases the task description didn't mention: empty inputs, error inputs, partial data, very large inputs, concurrent access, idempotency.
2. **Pattern selection** — when multiple existing patterns in the codebase could apply (e.g., two form libraries, two state-management approaches), which one does this task follow?
3. **UX / behavior** — for user-facing tasks: loading states, error states, empty states, success feedback, validation feedback, optimistic vs server-confirmed UI.
4. **Naming and structure** — file/module names, type names, route paths that aren't pinned down by an existing convention.
5. **Migration / backwards compatibility** — when modifying existing code: keep old behavior, deprecate, hard-cut? Is there data to migrate?
6. **Test scope** — what coverage level is expected; which specific scenarios are non-negotiable.
7. **Trade-offs** — explicit choice points the implementer would otherwise make alone (simplicity vs exhaustiveness, performance vs readability, MVP vs complete).

**Ask** when the codebase + task description + earlier tasks in the same milestone don't resolve a category, or when you'd otherwise make a load-bearing choice the user might want to own.

**Skip** when the answer is unambiguous from existing patterns, the task description, or prior milestone tasks. Some tasks are genuinely question-free — that's fine.

**Batch every question for one task into a single prompt.** Don't drip-feed.

Example batched prompt:

> Before refining "Employee list page", confirm:
>
> 1. **Scope edge:** Should the list paginate (and at what page size), or render all employees? The spec didn't say.
> 2. **Pattern:** The codebase has `src/lib/data-table.tsx` (custom) and the `@radix/data-table` pattern in `src/lib/projects-table.tsx`. Use the custom one for consistency with Projects list?
> 3. **Empty state:** Show a "No employees yet" placeholder, or hide the list entirely when empty?
> 4. **Loading state:** Skeleton rows, or a spinner overlay?
>
> Answer 1–4, or "all default" to let me pick reasonable defaults from the codebase patterns.

When you skip the prompt for a task, note it briefly in that task's progress line so the user can flag it if they think a question was warranted (e.g., `Refined "User entity": no open questions, plan attached`). The transparency lets the user trust the silence is deliberate, not a missed beat.

### 3b. Compose the implementation plan

Generate the `implementation-plan.md` content for this task. Use **`plugins/asana-workflow/references/implementation-plan-template.md`** (plugin-level shared reference, also used by `task-breakdown`) for the full structure, content rules, and self-review checklist.

The plan is **code-free** by design — it provides enough context (file paths, models, signatures, exemplar patterns, decisions) for the downstream agent implementing the task to derive the actual implementation from the live codebase. refine-tasks removes ambiguity about *what* and *why*; the downstream session writes the code. High-level structure:

- **Header** — `# <Task title>`, Asana URL, milestone, verbatim Purpose. **Never use T-labels in the plan** — they are breakdown-internal identifiers.
- **Resolved decisions** (optional) — choices recorded from the Phase 3a ambiguity batch
- **Files** — `Create` / `Modify` / `Reference` paths grouped by action; every path real
- **Models** (when the task introduces data structures) — name + fields + types + constraints, described in structured prose, **not** as class declarations
- **Functions / Endpoints** (when the task introduces new public surfaces) — name + parameters + return shape + behavior, described not implemented
- **Patterns to follow** — cross-cutting exemplars too broad to inline in a step
- **Step-by-step plan** — numbered steps (optional `- [ ]` checkbox), one action each. For testable behavior, use TDD order (write failing test → verify fails → implement → verify passes → commit). State the *intent* of each step, the file it touches, and the pattern to follow — never the literal code.
- **Acceptance criteria mapping** — table tying each acceptance criterion to the step(s) that verify it
- **Edge cases** — non-happy-path expectations
- **How to test** — concrete end-to-end verification commands (shell / curl / manual UI walkthrough) the executor runs at the end
- **References** — every source consulted

### 3c. Upload as Asana attachment

Upload the markdown content as an attachment on the task:

- Filename: `implementation-plan.md`
- Mime type: `text/markdown`
- Endpoint: `POST /tasks/<task_gid>/attachments` (via the `asana-api` skill)

**Replacement on re-run.** Before uploading, list the task's existing attachments. If an attachment named `implementation-plan.md` already exists, delete it first (DELETE `/attachments/<attachment_gid>`). Never accumulate duplicate plans.

### 3d. Post a refinement summary as a comment

After the plan is attached, post an Asana comment on the same task with a **human-readable summary** of what refinement decided. This is the "at-a-glance" view for followers (PM, designer, anyone watching the task) — not the full implementation plan, which is the attachment.

**Critical:** the comment is for human readers. It must carry **zero value for the agent that will later implement the task** — implementers read the task description and the attached `implementation-plan.md`; the comment is commentary, not directives.

**Content guidelines:**

- Lead with `📋 Refinement summary` so the comment is easy to spot in the activity feed.
- 3–6 bullet points typically — fewer is fine, longer only when truly warranted.
- Focus on what was **decided or discovered during refinement** that a casual reader wouldn't already know from the task description:
  - Answers given by the user during the Phase 3a ambiguity batch (the decisions, distilled)
  - Pattern choices when there were multiple candidates (e.g., "chose A over B for consistency with X")
  - Notable trade-offs or considerations the team should be aware of
  - Edge cases worth flagging to non-implementing readers
- **Do NOT include:**
  - The Purpose / Description / Out of scope / Acceptance Criteria — they live in the task description already
  - File paths, function signatures, model field lists, step-by-step actions — they live in the attached plan
  - Anything an implementer would need to do the work — that audience reads the attachment, not the comment
- Keep bullets terse (under ~120 characters each); the comment should fit on a phone screen.

**Posting:** post the comment via the `asana-api` skill.

Both examples below are written in Asana rich text (HTML).

**Example (substantive refinement):**

```html
<body><strong>📋 Refinement summary</strong><ul><li>Pagination: default <code>limit=50</code>, max <code>200</code> — was unspecified in the breakdown</li><li>Pattern choice: custom <code>data-table.tsx</code> (matches the Projects list) rather than Radix</li><li>Empty state: explicit "No employees yet" placeholder, not a hidden list</li></ul>Full plan: see the attached <em>implementation-plan.md</em>.</body>
```

**Example (mechanical refinement, nothing notable):**

```html
<body><strong>📋 Refinement summary</strong> — plan follows existing patterns directly, no notable trade-offs. Full plan in the attached <em>implementation-plan.md</em>.</body>
```

Always post a comment, even when minimal. The presence of the comment signals to followers that the task has been refined and is ready.

**Re-runs:** post a fresh comment each time. Re-refinement is a deliberate manual action (user reverts Product Status to Refinement); the resulting timeline of summary comments is expected.

### 3e. Move Product Status

Update the task's Product Status custom field from `Refinement` to `Unassigned` using the enum option GIDs resolved in Phase 2a.

### 3f. Progress report

Single-line report per task:

> Refined "Employee list page": plan attached, summary posted

---

## Phase 4: Summary

After processing all tasks, present a summary table and link to the project board:

```
Refined 4 tasks:
  1. Employee entity + repository      Unassigned
  2. Employee CRUD API endpoints       Unassigned
  3. Employee list page                Unassigned
  4. Employee create/edit form         Unassigned

Project: https://app.asana.com/0/<project_gid>/
Next step: pick any task and begin implementation through your preferred workflow.
```

If any tasks were skipped (wrong status, Design platform), list them at the end, grouped by reason. Example:

```
Skipped:
  ⚠ "Wireframe employee list" — Platform is Design (revert to Unassigned manually if it was moved by mistake)
  - "Audit log refactor" — status is Scheduled, not Refinement
```

---

## Behavior at edges

- **Dependency task still in Refinement when refining a dependent.** Warn the user: the dependent's plan can reference the dependency's task description but not its (nonexistent) implementation plan. Allow proceeding or include the dependency in this run.
- **A reference URL in the task description is unreachable.** Surface to the user; allow proceeding (the plan notes the missing source) or aborting.
- **Re-run mid-failure.** Per-task work is effectively atomic: if attachment upload succeeds but the status move fails, the task remains in Refinement; a re-run replaces the now-stale attachment and tries again.
- **Custom field discovery fails.** If `Refinement` or `Unassigned` enum option cannot be resolved by name on the Product Status field, abort with:
  > Product Status field on this project does not have the required enum options (`Refinement`, `Unassigned`). Confirm both are present, then re-run.

---

## What This Skill Does NOT Do

- Does not create new Asana tasks
- Does not move tasks beyond Unassigned (Scheduled / Assigned / Ready are PM concerns)
- Does not write code or scaffold projects (the downstream implementing agent does that)
- Does not generate plans for tasks in any status other than Refinement
- Does not refine Design-platform tasks (Figma / wireframe / design-spec work is produced by humans)

## Reference Files

- **`references/input-resolution.md`** — how to interpret each input shape into a deterministic GID list
- **`plugins/asana-workflow/references/implementation-plan-template.md`** — structure and content rules for the attached `implementation-plan.md` (plugin-level shared reference, also used by `task-breakdown`)

## Dependencies

- `asana-api` — all Asana API operations route through this skill (resolve task set, fetch descriptions and custom fields, upload the implementation-plan.md attachment, post the Refinement summary comment, move Product Status).

This skill has no other skill dependencies. Upstream and downstream agents (whatever they may be) interact with refine-tasks only through Asana state: the input is Refinement-status tasks with a well-formed description; the output is Unassigned-status tasks with `implementation-plan.md` attached.
