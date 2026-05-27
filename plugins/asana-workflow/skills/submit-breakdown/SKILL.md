---
name: submit-breakdown
description: >
  Pushes a task breakdown to Asana by faithfully replicating the breakdown
  markdown into Asana tasks. Use this skill whenever the user wants to submit,
  push, publish, or create Asana tasks from a task breakdown file — "submit this
  breakdown", "push these tasks to Asana", "create Asana tasks from the breakdown",
  "submit breakdown to Asana", "publish this plan", or after completing a
  task-breakdown and the user says "let's push it". Also triggers when the user
  provides a breakdown file path and an Asana project URL together. Do NOT trigger
  on requests to create a single Asana task (that's log-task) or to start working
  on an existing task (that's start-task).
---

# Submit Breakdown

Replicate a task breakdown (output of `task-breakdown`) into Asana as tasks in **Refinement** product status. The skill performs no codebase analysis, resolves no ambiguities, and writes no implementation plans — those are the job of `refine-tasks`, which runs later for a chosen batch of tasks.

The goal: a faithful, low-friction upload so the breakdown is visible in Asana and ready for refinement.

## Prerequisites

- `asana-api` skill for all Asana API operations — route every call through it, no raw curl.
- **Execute API calls directly via the `asana-api` skill — do not write helper scripts.** It is tempting to wrap the per-task creation loop in a Python or Node script that batches the calls. Don't. The agent has direct tool access to every Asana operation needed here (create task, set custom fields, set dependencies, create section, post comment, delete). Wrapping them in a script adds an opaque layer, hides individual call failures, makes progress harder to report, and produces an artifact (the script file) that has no reason to persist. Make the calls one by one as tool invocations; report progress per task.
- A task breakdown file (output of `task-breakdown`) — markdown with milestones, tasks, dependencies, **and per-task `Estimate:` field**.
- An Asana project URL — the target project where tasks will be created.
- The target project's Product Status custom field must include a **Refinement** enum option. The skill verifies this before doing anything else and aborts with a clear message if it's missing.

## Inputs

1. **Breakdown file path** — a markdown file from `task-breakdown` containing tasks grouped by milestone, with per-task: title, platform, category, description, estimate, dependencies, acceptance criteria, and references. The estimate is taken verbatim — this skill does not produce or revise estimates.
2. **Asana project URL** — `app.asana.com/0/<project_gid>/...`

If either input is missing, ask for it before proceeding.

---

## Phase 1: Discovery (Asana only)

### 1a. Fetch project structure

1. **Fetch the project** to get sections (these map to milestones).
2. **Discover custom field GIDs** by fetching the project's custom field settings. The field names are standard but GIDs vary per project:
   - **Platform** — enum: Backend, Frontend, Design, iOS, Android
   - **Estimate** — number (hours)
   - **Category** — enum: Feature Request, Technical Request, Bug, Customer Support, Documentation
   - **Priority** — enum: P0, P1, P2, P3, P4
   - **Product Status** — enum: Requirements, Sizing, **Refinement**, Unassigned, Scheduled, Assigned, Ready, Canceled

   Read **`references/asana-custom-field-discovery.md`** (plugin-level shared reference) for field name matching patterns and how to record GIDs.

3. **Resolve the Product Status enum option GIDs** for `Refinement` and `Unassigned` by name from the field's `enum_options`. Never hardcode option GIDs — they vary per project.

4. **Pre-flight check.** If the Product Status field does not contain a `Refinement` enum option, abort with:

   > Product Status field on this project does not have a `Refinement` enum option. Add `Refinement` as a value on the custom field in Asana, then re-run submit-breakdown.

5. **Fetch existing tasks per section** to understand current state — what's done, what exists, what the breakdown says to remove.

This skill does **no codebase discovery**. The references embedded in each task description (aggregated by Phase 2) are what `refine-tasks` will use later.

---

## Phase 2: Render Descriptions

For each task in the breakdown, render the Asana task description by aggregating fields from the breakdown.

Read `references/description-template.md` for the full structure, content rules, and formatting rules.

Key principles:
- The description is a faithful render of the breakdown task entry — Purpose, Description, Scope, Dependencies, Acceptance Criteria, References.
- References aggregate from three levels (task entry, milestone block, file header) and are deduplicated by URL/path.
- No implementation-plan content. No file paths inferred. No analysis. If the breakdown didn't say it, the description doesn't say it.
- **No T-labels in the Asana description.** T-labels (`T1`, `T2`, …) are internal to the breakdown markdown only — they exist solely so the breakdown can express dependencies before Asana GIDs exist. Once tasks are in Asana, the canonical reference is the Asana task link. Any `Depends on: T1, T2` in the breakdown must be resolved to Asana task links in the description; never write the literal `T1` / `T2` into Asana.
- No questions asked of the user during this phase. Any ambiguity is `refine-tasks`' problem to resolve later.

---

## Phase 3: Submit to Asana

Create tasks in **dependency order** — tasks with no dependencies first, then tasks that depend on those, etc. This ensures GIDs are available for resolving dependency-link references.

### Step 1: Create all tasks (NO Asana dependencies yet)

The Asana `create_task` / `create_tasks` tools do NOT support a dependencies field. Any dependency data passed during creation is silently ignored. Dependencies are wired in a separate step below.

For each task, create it with:
- **Name** — from the breakdown task title (no platform prefix; Platform is a custom field)
- **Description** (HTML) — composed in Phase 2, passed as `html_notes` wrapped in `<body>...</body>`
- **Section** — corresponds to the breakdown's milestone (create the section if missing)
- **Custom fields:**
  - Platform — from the breakdown task entry
  - Estimate — from the breakdown task entry's `Estimate:` field, converted from `hh:mm` to decimal hours (e.g., `01:30` → `1.5`)
  - Category — from the breakdown task entry
  - Priority — default `P3`
  - **Product Status — `Refinement`** (using the enum option GID resolved in Phase 1a)

Track every returned task GID in a T-label → GID map (e.g., `T1 → "1234567890"`).

### Step 2: Wire dependencies (separate API calls)

After ALL tasks exist, wire dependencies using `asana_set_task_dependencies`. This is a separate tool — not a field on create_task.

For each task that has dependencies in the breakdown:
- Look up the dependency T-labels in the T-label → GID map
- Call `asana_set_task_dependencies` with `task_id` = this task's GID and `dependencies` = array of dependency GIDs

### Task title rules
- No platform prefix (Platform is a custom field)
- Descriptive, concise — taken from the breakdown but cleaned up if needed

### Section mapping
- Each milestone in the breakdown maps to a section in the Asana project.
- If the section doesn't exist yet, create it.
- Sections should be ordered to match the milestone order in the breakdown.

### Progress reporting
After creating each task, report briefly:
> Created: "Task title" (M1) — [Platform] · Refinement · estimate hh:mm

After all tasks and dependencies are set:
> All N tasks created in Refinement status with dependencies wired. Run `/refine-tasks` against this project when you're ready to add implementation plans. [Project URL]

---

## Phase 4: Cleanup

### Originating Task Disposition

If the breakdown has an **Originating Task** section, handle it based on the specified action:

**Delete:** List the task name and GID, ask for confirmation, then delete.

**Complete:** Mark the task as complete and post a comment listing all newly created tasks. The comment should include each task's name and Asana URL, grouped by milestone. Example comment format:

> This task has been decomposed into the following implementation tasks:
>
> **M1 :: Core Data Layer**
> - [Setup employee entity + repository](task-url)
> - [Employee CRUD API endpoints](task-url)
>
> **M2 :: Employee Management UI**
> - [Employee list page](task-url)
> - ...

**Both actions require explicit user confirmation** — no exceptions.

### Task Removal

If the breakdown specifies additional tasks to remove (via Source field pointing to existing Asana tasks):

1. List the tasks to be deleted with their names and GIDs.
2. **Ask the user for confirmation before deleting.**
3. Delete only after explicit confirmation.

---

## User Interaction Model

- **Do NOT present each task description for review.** The descriptions render mechanically from the breakdown; the user already approved the breakdown.
- **Do NOT ask implementation-ambiguity questions.** Those go to `refine-tasks`.
- **Ask confirmation** only for destructive actions — task deletions in Phase 4.
- **If no questions, proceed silently.** Create the task and move on.
- **Report progress** — brief status updates so the user knows things are moving.

## Related Skills

- `task-breakdown` — produces the input file for this skill, including rough estimates and per-task validation
- `refine-tasks` — picks up where this skill leaves off; reads Refinement-status tasks, performs codebase analysis, attaches an implementation plan, revises the estimate, transitions to Unassigned
- `start-task` — consumes refined tasks (downloads the attached implementation plan and includes it in the routed sub-skill's context)
- `asana-api` — all Asana API operations route through this skill
