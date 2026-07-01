---
name: submit-breakdown
description: >
  Pushes a task breakdown to the task manager by faithfully replicating the
  breakdown markdown into tasks. Use this skill whenever the user wants to submit,
  push, upload, publish, or create tasks from a task-breakdown file —
  "submit this breakdown", "upload this task-breakdown file", "push these tasks",
  "create tasks from the breakdown", "submit breakdown",
  "publish this plan", or after completing a task-breakdown and the user
  says "let's push it". Also triggers when the user provides a breakdown file
  path and a project URL together. Do NOT trigger on requests to create
  a single task, or to start working on an existing task.
---

# Submit Breakdown

Replicate a task breakdown (output of `task-breakdown`) into the task manager as tasks in **Refinement** product status. The skill performs no codebase analysis, resolves no ambiguities, and writes no implementation plans — those happen later during refinement, after the codebase has been read.

The goal: a faithful, low-friction upload so the breakdown is visible in the task manager and ready for refinement.

## Prerequisites

- The `task-manager` interface for all task operations — perform every task operation through it.
- **Perform operations directly via the `task-manager` interface — do not write helper scripts.** It is tempting to wrap the per-task creation loop in a Python or Node script that batches the calls. Don't. The agent has direct access to every operation needed here (create task, set fields, set status, add dependencies, create board groupings, add comments, delete). Wrapping them in a script adds an opaque layer, hides individual failures, makes progress harder to report, and produces an artifact (the script file) that has no reason to persist. Make the operations one by one; report progress per task.
- A task breakdown file (output of `task-breakdown`) — markdown with milestones, tasks, and dependencies.
- A project URL — the target project where tasks will be created.
- The target project must support the **Refinement** lifecycle state (see `plugins/asana-workflow/references/workflow/lifecycle.md`). The skill verifies this before doing anything else and aborts with a clear message if it's missing.

## Inputs

1. **Breakdown file path** — a markdown file from `task-breakdown` containing tasks grouped by milestone, with per-task: title, platform, category, description, dependencies, acceptance criteria, and references.
2. **Project URL** — the target project in the task manager.

If either input is missing, ask for it before proceeding.

---

## Phase 1: Discovery (task manager only)

### 1a. Inspect the project

1. **Resolve the project** from the URL via the `task-manager` interface and read its board groupings (these map to milestones).
2. **Learn which fields the board carries** via `list_fields(board)`. The canonical workflow fields (see `plugins/asana-workflow/references/workflow/fields.md`) this skill sets are:
   - **Platform** — Backend, Frontend, Design, iOS, Android
   - **Category** — Feature Request, Technical Request, Bug, Customer Support, Documentation
   - **Priority** — P0, P1, P2, P3, P4
   - **Product Status** — a lifecycle state (see `plugins/asana-workflow/references/workflow/lifecycle.md`)

3. **Pre-flight check.** Confirm the project supports the `Refinement` lifecycle state. If it does not, abort with:

   > This project does not support the `Refinement` lifecycle state. Add it in the task manager, then re-run submit-breakdown.

   `set_status(task, <name>)` addresses lifecycle states by name; the provider resolves the underlying representation, so the skill never handles status identifiers itself.

4. **Read existing tasks per grouping** to understand current state — what's done, what exists, what the breakdown says to remove.

This skill does **no codebase discovery**. The references embedded in each task description (aggregated by Phase 2) are what the downstream refinement step will read later.

---

## Phase 2: Render Descriptions

For each task in the breakdown, render the task description by aggregating fields from the breakdown.

Read `references/description-template.md` for the full structure, content rules, and formatting rules.

Key principles:
- The description is a faithful render of the breakdown task entry — Purpose, Description, Out of scope (optional), Acceptance Criteria, References.
- References aggregate from three levels (task entry, milestone block, file header) and are deduplicated by URL/path.
- No implementation-plan content. No file paths inferred. No analysis. If the breakdown didn't say it, the description doesn't say it.
- **No T-labels in the task description.** T-labels (`T1`, `T2`, …) are internal to the breakdown markdown only — they exist solely so the breakdown can express dependencies before the task manager assigns its own identifiers. If a T-label appears in prose (e.g., "extends the schema introduced in T1"), replace it with the corresponding task link + title. The `Depends on:` field is **not** rendered into the description at all — dependencies are wired natively via `add_dependency` in Phase 3 Step 2, where they are visible as blocking relationships. Never write the literal `T1`, `T2`, … into the task manager.
- No questions asked of the user during this phase. Any ambiguity is handled later, during the refinement step that reads the codebase.

---

## Phase 3: Submit to the Task Manager

Create tasks in **dependency order** — tasks with no dependencies first, then tasks that depend on those, etc. This ensures each task handle is available for resolving dependency-link references.

### Step 1: Create all tasks (NO dependencies yet)

`create_task` does not take dependencies — they are wired in a separate step below.

For each task, through the `task-manager` interface:
1. Ensure the milestone's board grouping exists (see Milestone groupings below), then `create_task(title, description, board)` filed under that grouping.
2. Set fields via `set_field(task, <field>, <value>)` for each field the board carries (see `plugins/asana-workflow/references/workflow/fields.md`):
   - **Name** — from the breakdown task title (no platform prefix; Platform is a field)
   - **Description** — composed in Phase 2 (authored as Markdown; the provider renders it)
   - Platform — from the breakdown task entry
   - Category — from the breakdown task entry
   - Priority — default `P3`
3. Set **Product Status** via `set_status(task, <name>)`, conditional on the task's Platform (lifecycle names from `plugins/asana-workflow/references/workflow/lifecycle.md`):
   - If **Platform = `Design`** → `set_status(task, "Unassigned")`. Design tasks are not refinable by Claude (the work is producing Figma files, wireframes, design specs, etc. — outside this tooling's reach), so they bypass the Refinement stage and go straight to the staffing pool.
   - For every other platform (Backend, Frontend, iOS, Android) → `set_status(task, "Refinement")` so the downstream refinement step can pick them up.

Track every returned task handle in a T-label → task map (e.g., `T1 → <task handle>`).

### Step 2: Wire dependencies (separate calls)

After ALL tasks exist, wire dependencies via `add_dependency(task, depends_on)`. This is a separate operation — not part of `create_task`.

For each task that has dependencies in the breakdown:
- Look up the dependency T-labels in the T-label → task map
- Call `add_dependency(task, <dependency task>)` once per dependency (the dependent task is marked as blocked by each).

### Task title rules
- No platform prefix (Platform is a field)
- Descriptive, concise — taken from the breakdown but cleaned up if needed

### Milestone groupings
- Each milestone in the breakdown maps to a grouping on the target board.
- Creating board groupings is a provider-structural operation. Create the milestone groupings on the target board via the `task-manager` interface; if a grouping doesn't exist yet, create it.
- Groupings should be ordered to match the milestone order in the breakdown.

### Progress reporting
After creating each task, report briefly. Reflect the actual Product Status set (Design → Unassigned, everything else → Refinement):

> Created: "Task title" (M1) — Backend · Refinement
> Created: "Wireframe employee list" (M1) — Design · Unassigned

After all tasks and dependencies are set, summarize so the user knows which tasks need refinement next. Adapt the wording to the actual counts (omit the Design line when there are no Design tasks):

> All N tasks created with dependencies wired.
>   • M tasks at Refinement (next step: run the refinement workflow to add implementation plans before staffing)
>   • K Design-platform tasks at Unassigned (Claude can't refine Design work — staff them through your normal design workflow)
> [Project URL]

---

## Phase 3.5: Visual Assets

After all tasks are created, enrich them with visual context — Figma links (already in the description) and prototype screenshots (uploaded as attachments). This phase is **conditional**: skip it entirely if no prototype source exists. Figma links alone don't require this phase — they were already rendered into descriptions in Phase 2.

### Figma links

Already handled in Phase 2. If the aggregated references for a task contained a Figma URL, it was rendered as a `→ View in Figma` link at the top of the description. No further action needed here.

If Figma designs become available after submission (common early in a project), the Figma link can be added to the breakdown file's References and re-submitted, or added directly to the task description later.

### Prototype screenshots

When a working prototype exists (an HTML file, a hosted URL, or screenshots from one), uploading screen-level images as attachments helps developers quickly understand what they're building without needing to run the full prototype themselves.

**When to run this phase:**
- The breakdown's References section links to a task with an HTML prototype attachment, OR
- The user provides a local prototype file or screenshot folder, OR
- The user explicitly asks for screenshots to be added.

**How to render screenshots from an HTML prototype:**
1. Download the prototype HTML file (from a task attachment or local path).
2. Open it using the Chrome DevTools MCP (`new_page` with `file://` URL or hosted URL).
3. Navigate the prototype to each relevant screen — use `evaluate_script` to drive the UI (click buttons, advance wizard steps) since prototypes are typically JS-heavy SPAs that don't respond to standard accessibility-tree clicks.
4. Take a `fullPage: true` screenshot per screen and save to a local temp directory within the project working dir (e.g. `docs/cortex/screenshots/`).
5. Map each screenshot to the tasks it covers (one screenshot may apply to multiple tasks — upload it to each one).

**How to upload to tasks:**

Upload each screenshot to its task via `upload_attachment(task, <screenshot path>)`. Do NOT write a helper script; perform one upload per task attachment.

**Screenshot-to-task mapping heuristic:**
- Wizard step screens → map to all tasks within that milestone (the whole step is one user-facing increment)
- Modal/overlay screens → map to the specific task that builds that modal
- Config forms with multiple sections → map the same screenshot to all tasks that build sections of that form
- Post-publish / terminal state screens → map to the task that builds that state

**Important constraints:**
- Do not embed screenshot URLs inline in the description — images are added as file attachments, not inline content. Upload them via `upload_attachment`. See `references/description-template.md` for details.
- Upload screenshots as attachments *after* the task description is set — the order doesn't affect how they display, but it keeps the create → enrich flow linear and easier to debug.
- The T-label → task map built in Phase 3 Step 1 remains valid here — use T-labels internally for screenshot-to-task bookkeeping. The "No T-labels in the task manager" rule applies to task description content only, not to in-session mapping.

**Progress reporting for this phase:**
> Uploaded screenshot "screen-03-mapping.png" → T4, T5, T6 (3 tasks)
> Uploaded screenshot "screen-04-validate.png" → T7 (1 task)
> Skipped T15 (Backend task — no relevant UI screen)

---

## Phase 4: Cleanup

### Originating Task Disposition

If the breakdown has an **Originating Task** section, handle it based on the specified action:

**Delete:** List the task name and handle, ask for confirmation, then delete it through the task manager.

**Complete:** Mark the task as complete and post a comment via `add_comment(task, body)` listing all newly created tasks. The comment should include each task's name and URL, grouped by milestone. Author the body as Markdown; the provider renders it. Example body:

```markdown
This task has been decomposed into the following implementation tasks:

**M1 :: Core Data Layer**
- [Setup employee entity + repository](task-url)
- [Employee CRUD API endpoints](task-url)

**M2 :: Employee Management UI**
- [Employee list page](task-url)
- ...
```

**Both actions require explicit user confirmation** — no exceptions.

### Task Removal

If the breakdown specifies additional tasks to remove (via Source field pointing to existing tasks):

1. List the tasks to be deleted with their names and handles.
2. **Ask the user for confirmation before deleting.**
3. Delete only after explicit confirmation, through the task manager.

---

## User Interaction Model

- **Do NOT present each task description for review.** The descriptions render mechanically from the breakdown; the user already approved the breakdown.
- **Do NOT ask implementation-ambiguity questions.** Those are resolved later during refinement.
- **Ask confirmation** only for destructive actions — task deletions in Phase 4.
- **If no questions, proceed silently.** Create the task and move on.
- **Report progress** — brief status updates so the user knows things are moving.

## Dependencies

- `task-manager` — all task operations route through this interface (resolve project / groupings / fields, create tasks, set fields and status, wire dependencies, post comments, delete tasks).
- `task-breakdown` — produces the input file this skill consumes. The two skills are intentionally paired: task-breakdown produces a validated markdown roadmap; submit-breakdown faithfully replicates it into the task manager.

This skill has no other skill dependencies. Whatever happens to the tasks after submission (refinement, staffing, implementation) is outside this skill's contract.
