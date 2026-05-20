---
name: submit-breakdown
description: >
  Pushes a task breakdown to Asana as fully specified, implementation-ready tasks. Use this skill
  whenever the user wants to submit, push, publish, or create Asana tasks from a task breakdown
  file — "submit this breakdown", "push these tasks to Asana", "create Asana tasks from the
  breakdown", "submit breakdown to Asana", "publish this plan", or after completing a
  task-breakdown and the user says "let's push it". Also triggers when the user provides a
  breakdown file path and an Asana project URL together. Do NOT trigger on requests to create
  a single Asana task (that's log-task) or to start working on an existing task (that's start-task).
---

# Submit Breakdown

Transform a task breakdown (output of `task-breakdown`) into atomic, self-contained Asana tasks that `start-task` can execute with minimal user interaction.

This skill owns **what** and **why** — scope, constraints, traceability, acceptance criteria. `start-task` owns **how** — implementation planning, brainstorming, coding.

The goal: maximize signal in each task description so that a separate Claude session running `start-task` — with access to the codebase but no prior conversation context — can execute effectively.

## Prerequisites

- `asana-api` skill for all Asana API operations — route every call through it, no raw curl.
- A task breakdown file (output of `task-breakdown`) — markdown with milestones, tasks, dependencies.
- An Asana project URL — the target project where tasks will be created.

## Inputs

1. **Breakdown file path** — a markdown file from `task-breakdown` containing tasks grouped by milestone, with per-task: title, platform, category, description, scope, dependencies, and references to external context. Note: the breakdown does not contain estimates — this skill generates them based on codebase analysis (Phase 2, Step 2c).
2. **Asana project URL** — `app.asana.com/0/<project_gid>/...`

If either input is missing, ask for it before proceeding.

---

## Phase 1: Discovery

Before creating any tasks, gather all context needed to write rich descriptions.

### 1a. Asana Discovery

From the target project:

1. **Fetch the project** to get sections (these map to milestones).
2. **Discover custom field GIDs** by fetching the project's custom field settings. The field names are standard but GIDs vary per project:
   - **Platform** — enum: Backend, Frontend, Design, iOS, Android
   - **Estimate** — number (hours)
   - **Category** — enum: Feature Request, Technical Request, Bug, Customer Support, Documentation
   - **Priority** — enum: P0, P1, P2, P3, P4
   - **Product Status** — enum: Requirements, Sizing, Unassigned, Scheduled, Assigned, Ready, Canceled

   Match fields by name using case-insensitive patterns (same approach as `log-task` Step 3). Record each field's GID and enum option GIDs.

3. **Fetch existing tasks per section** to understand current state — what's done, what exists, what the breakdown says to remove.

### 1b. Codebase Discovery

Read the codebase to inform task descriptions with concrete file paths and patterns:

1. **All files referenced in the breakdown** — spec files, CLAUDE.md files, linked docs.
2. **Source tree structure** — understand what's already built (`ls` key directories).
3. **API contracts** — backend models, routers, schemas (or frontend code if the tasks are backend-focused). These will be referenced in descriptions so `start-task` can read them directly.
4. **Existing code patterns** — architecture conventions, naming, file structure. Identify files that demonstrate patterns tasks should follow.

The point: task descriptions will reference real files by path. Every path you include must exist (or be a new file the task will create based on a clear convention).

---

## Phase 2: Task Preparation

Process each task from the breakdown. For each task:

### 2a. Validation Checks

Run these checks and surface issues to the user:

- **Platform check:** Does this task involve only one platform? If it spans multiple (e.g., backend API + frontend UI), propose splitting into separate tasks with a dependency between them. Recalculate estimates. Ask the user for confirmation before splitting.
- **Size check:** Is the task completable in a single `start-task` session (roughly 0.5–4 hours)? If too large, propose a split with reasoning.
- **Redundancy check:** Does the task duplicate work already done in the codebase? Flag and ask whether to skip or adjust scope.

### 2b. Resolve Ambiguities

Before writing the description, identify genuine ambiguities that `start-task` would otherwise need to ask the user about. These are questions whose answers can't be found in the codebase or spec.

Batch all questions for a task together and ask the user. Examples:
- "The breakdown says 'employee form' — should password be required on edit, or only on create?"
- "This task mentions a 'confirmation dialog' — should that be a shared component or inline?"
- "The API returns user IDs only. Should this task resolve user names, or display IDs?"

The rule: only ask when there's genuine ambiguity. Don't ask for permission on descriptions. Don't ask questions the code or spec already answers.

### 2c. Estimate the Task

Produce an honest estimate of how long an experienced senior software engineer would take to implement this task without AI assistance. This estimate is written to the Asana Estimate custom field (number, in hours).

**Format:** hours as a number, 2 decimal places, in multiples of 0.25 (e.g., 0.25, 0.50, 1.00, 1.25, 1.50, 2.75, 4.00). Never use values like 1.33 or 2.10.

**What to weigh:**

| Factor | Effect |
|--------|--------|
| Follows an existing pattern in the codebase (e.g., "same as users module") | Reduces time — the engineer reads the pattern and replicates |
| New architectural pattern with no precedent | Increases time — design decisions, trial and error |
| Number of files to create or modify | More files = more time |
| Clear API contract already exists to code against | Reduces time |
| UI work with layout/styling decisions | Increases time |
| Complex acceptance criteria (edge cases, error states) | Increases time |
| Dependencies on other tasks' output (needs to understand prior work) | Slight increase — context loading |
| Boilerplate-heavy but straightforward (CRUD, config, wiring) | Low estimate — mechanical work |

**Calibration anchors:**

- 0.25h — a single config change, adding an import, registering a route
- 0.50h — a straightforward file following an exact existing pattern (e.g., "copy users router, change to projects")
- 1.00h — a small feature with 2-3 files, clear pattern to follow, no design decisions
- 2.00h — a feature with 4-6 files, some decisions, moderate acceptance criteria
- 3.00–4.00h — complex feature, new patterns, multiple edge cases, or significant UI work

Estimate honestly. Don't inflate to be safe and don't compress to look efficient. If the task breakdown scoped tasks well (0.5–4h range), most estimates should land between 0.50 and 3.00.

### 2d. Compose the Task Description

Read `references/description-template.md` for the full description structure, formatting rules, and content rules. That file is the canonical reference for how to write task descriptions.

Key principles (details in the reference file):
- Reference source files by path — don't replicate code.
- Point to backend source files for API contracts — never hardcode request/response shapes.
- Be opinionated when conventions exist — don't offer alternatives.
- State technical facts, not predictions about unbuilt code.
- Resolve cross-task design decisions once and reference them in later tasks.

---

## Estimation Review

After preparing all tasks (descriptions + estimates), present a summary table before submitting:

```
Estimates (total: 24.50h):
  T1  Setup employee entity + repository    1.50h  Backend
  T2  Employee CRUD API endpoints           2.00h  Backend
  T3  Employee list page                    2.50h  Frontend
  T4  Employee create/edit form             2.75h  Frontend
  ...

Confirm? [Y/n / type T-label to adjust]
```

Keep it compact — one line per task with T-label, title, estimate, platform. Show the total.

If the user adjusts an estimate, update it and proceed. Don't re-show the table unless multiple changes are requested.

---

## Phase 3: Submit to Asana

Create tasks in **dependency order** — tasks with no dependencies first, then tasks that depend on those, etc. This ensures GIDs are available for wiring dependencies.

### Step 1: Create all tasks (NO dependencies yet)

The Asana `create_task` / `create_tasks` tools do NOT support a dependencies field. Any dependency data passed during creation is silently ignored. Dependencies are wired in a separate step below.

For each task, create it with:
- Name (no platform prefix — Platform is a custom field)
- Description (HTML, composed in Phase 2) — pass as `html_notes` wrapped in `<body>...</body>`
- Section (milestone)
- Custom fields: Platform, Estimate (from Step 2c, confirmed in Estimation Review), Category, Priority (default P3), Product Status (default Unassigned)

Track every returned task GID in a T-label → GID map (e.g., T1 → "1234567890").

### Step 2: Wire dependencies (separate API calls)

After ALL tasks exist, wire dependencies using `asana_set_task_dependencies`. This is a separate tool — not a field on create_task.

For each task that has dependencies in the breakdown:
- Look up the dependency T-labels in the T-label → GID map
- Call `asana_set_task_dependencies` with `task_id` = this task's GID and `dependencies` = array of dependency GIDs

### Task title rules:
- No platform prefix (Platform is a custom field)
- Descriptive, concise — taken from the breakdown but cleaned up if needed

### Section mapping:
- Each milestone in the breakdown maps to a section in the Asana project.
- If the section doesn't exist yet, create it.
- Sections should be ordered to match the milestone order in the breakdown.

### Progress reporting:
After creating each task, report briefly:
> Created: "Task title" (M1, T3) — [Platform]

After all tasks and dependencies are set:
> All N tasks created with dependencies wired. [Project URL]

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

- **Do NOT present each task description for review.** The user won't read N descriptions. Compose them and submit.
- **Ask questions** when there's genuine implementation ambiguity that can't be resolved from the codebase or spec. Batch all questions for a task together.
- **Ask confirmation** for destructive actions only — task deletions, task splits that change the dependency graph.
- **If no questions, proceed silently.** Create the task and move on.
- **Report progress** — brief status updates so the user knows things are moving.

## Related Skills

- `task-breakdown` — produces the input file for this skill
- `start-task` — consumes the output tasks (the "customer" of this skill's output)
- `asana-api` — all Asana API operations route through this skill
- `log-task` — creates individual tasks (this skill creates batches from a breakdown)
