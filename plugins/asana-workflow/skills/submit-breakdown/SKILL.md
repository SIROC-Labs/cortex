---
name: submit-breakdown
description: >
  Pushes a task breakdown to Asana by faithfully replicating the breakdown
  markdown into Asana tasks. Use this skill whenever the user wants to submit,
  push, upload, publish, or create Asana tasks from a task-breakdown file —
  "submit this breakdown", "upload this task-breakdown file", "push these tasks
  to Asana", "create Asana tasks from the breakdown", "submit breakdown to
  Asana", "publish this plan", or after completing a task-breakdown and the user
  says "let's push it". Also triggers when the user provides a breakdown file
  path and an Asana project URL together. Do NOT trigger on requests to create
  a single Asana task, or to start working on an existing task.
---

# Submit Breakdown

Replicate a task breakdown (output of `task-breakdown`) into Asana as tasks in **Refinement** product status. The skill performs no codebase analysis, resolves no ambiguities, and writes no implementation plans — those happen later during refinement, after the codebase has been read.

The goal: a faithful, low-friction upload so the breakdown is visible in Asana and ready for refinement.

## Prerequisites

- `asana-api` skill for all Asana API operations — route every call through it, no raw curl.
- **Execute API calls directly via the `asana-api` skill — do not write helper scripts.** It is tempting to wrap the per-task creation loop in a Python or Node script that batches the calls. Don't. The agent has direct tool access to every Asana operation needed here (create task, set custom fields, set dependencies, create section, post comment, delete). Wrapping them in a script adds an opaque layer, hides individual call failures, makes progress harder to report, and produces an artifact (the script file) that has no reason to persist. Make the calls one by one as tool invocations; report progress per task.
- A task breakdown file (output of `task-breakdown`) — markdown with milestones, tasks, and dependencies.
- An Asana project URL — the target project where tasks will be created.
- The target project's Product Status custom field must include a **Refinement** enum option. The skill verifies this before doing anything else and aborts with a clear message if it's missing.

## Inputs

1. **Breakdown file path** — a markdown file from `task-breakdown` containing tasks grouped by milestone, with per-task: title, platform, category, description, dependencies, acceptance criteria, and references.
2. **Asana project URL** — `app.asana.com/0/<project_gid>/...`

If either input is missing, ask for it before proceeding.

---

## Phase 1: Discovery (Asana only)

### 1a. Fetch project structure

1. **Fetch the project** to get sections (these map to milestones).
2. **Discover custom field GIDs** by fetching the project's custom field settings. The field names are standard but GIDs vary per project:
   - **Platform** — enum: Backend, Frontend, Design, iOS, Android
   - **Category** — enum: Feature Request, Technical Request, Bug, Customer Support, Documentation
   - **Priority** — enum: P0, P1, P2, P3, P4
   - **Product Status** — enum: Requirements, Sizing, **Refinement**, Unassigned, Scheduled, Assigned, Ready, Canceled

   Read **`references/asana-custom-field-discovery.md`** (plugin-level shared reference) for field name matching patterns and how to record GIDs.

3. **Resolve the Product Status enum option GIDs** for `Refinement` and `Unassigned` by name from the field's `enum_options`. Never hardcode option GIDs — they vary per project.

4. **Pre-flight check.** If the Product Status field does not contain a `Refinement` enum option, abort with:

   > Product Status field on this project does not have a `Refinement` enum option. Add `Refinement` as a value on the custom field in Asana, then re-run submit-breakdown.

5. **Fetch existing tasks per section** to understand current state — what's done, what exists, what the breakdown says to remove.

This skill does **no codebase discovery**. The references embedded in each task description (aggregated by Phase 2) are what the downstream refinement step will read later.

---

## Phase 2: Render Descriptions

For each task in the breakdown, render the Asana task description by aggregating fields from the breakdown.

Read `references/description-template.md` for the full structure, content rules, and formatting rules.

Key principles:
- The description is a faithful render of the breakdown task entry — Purpose, Description, Out of scope (optional), Acceptance Criteria, References.
- References aggregate from three levels (task entry, milestone block, file header) and are deduplicated by URL/path.
- No implementation-plan content. No file paths inferred. No analysis. If the breakdown didn't say it, the description doesn't say it.
- **No T-labels in the Asana description.** T-labels (`T1`, `T2`, …) are internal to the breakdown markdown only — they exist solely so the breakdown can express dependencies before Asana GIDs exist. If a T-label appears in prose (e.g., "extends the schema introduced in T1"), replace it with the corresponding Asana task link + title. The `Depends on:` field is **not** rendered into the description at all — dependencies are wired natively via `asana_set_task_dependencies` in Phase 3 Step 2, where they are visible as blocking relationships in Asana. Never write the literal `T1`, `T2`, … into Asana.
- No questions asked of the user during this phase. Any ambiguity is handled later, during the refinement step that reads the codebase.

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
  - Category — from the breakdown task entry
  - Priority — default `P3`
  - **Product Status** — conditional on the task's Platform (using the enum option GIDs resolved in Phase 1a):
    - If **Platform = `Design`** → set Product Status to **`Unassigned`**. Design tasks are not refinable by Claude (the work is producing Figma files, wireframes, design specs, etc. — outside this tooling's reach), so they bypass the Refinement stage and go straight to the staffing pool.
    - For every other platform (Backend, Frontend, iOS, Android) → set Product Status to **`Refinement`** so the downstream refinement step can pick them up.

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

After all tasks are created, enrich them with visual context — Figma links (already in the description) and prototype screenshots (uploaded as attachments). This phase is **conditional**: skip it entirely if neither Figma links nor a prototype source exist.

### Figma links

Already handled in Phase 2. If the aggregated references for a task contained a Figma URL, it was rendered as a `→ View in Figma` link at the top of the description. No further action needed here.

If Figma designs become available after submission (common early in a project), the Figma link can be added to the breakdown file's References and re-submitted, or added directly to the task description later.

### Prototype screenshots

When a working prototype exists (an HTML file, a hosted URL, or screenshots from one), uploading screen-level images as attachments helps developers quickly understand what they're building without needing to run the full prototype themselves.

**When to run this phase:**
- The breakdown's References section links to an Asana task with an HTML prototype attachment, OR
- The user provides a local prototype file or screenshot folder, OR
- The user explicitly asks for screenshots to be added.

**How to render screenshots from an HTML prototype:**
1. Download the prototype HTML file (from an Asana attachment or local path).
2. Open it using the Chrome DevTools MCP (`new_page` with `file://` URL or hosted URL).
3. Navigate the prototype to each relevant screen — use `evaluate_script` to drive the UI (click buttons, advance wizard steps) since prototypes are typically JS-heavy SPAs that don't respond to standard accessibility-tree clicks.
4. Take a `fullPage: true` screenshot per screen and save to a local temp directory within the project working dir (e.g. `docs/cortex/screenshots/`).
5. Map each screenshot to the tasks it covers (one screenshot may apply to multiple tasks — upload it to each one).

**How to upload to Asana tasks:**
```
POST /attachments
Content-Type: multipart/form-data
parent: <task_gid>
file: @/path/to/screenshot.png
```

Use `curl -F` for multipart uploads — Python's `urllib` doesn't have built-in multipart support and constructing it manually is error-prone. Do NOT write a helper script; make one `curl` invocation per task attachment.

**Screenshot-to-task mapping heuristic:**
- Wizard step screens → map to all tasks within that milestone (the whole step is one user-facing increment)
- Modal/overlay screens → map to the specific task that builds that modal
- Config forms with multiple sections → map the same screenshot to all tasks that build sections of that form
- Post-publish / terminal state screens → map to the task that builds that state

**Important constraints:**
- `<img>` tags are NOT supported in Asana `html_notes` — do not attempt to embed screenshot URLs inline. Images must be file attachments. See `references/description-template.md` for details.
- Asana attachment view URLs contain `&`-separated query parameters with expiry timestamps (`?e=...&v=0&t=...`). These are signed URLs that Asana re-signs when serving to authenticated users; the expiry in the URL does not affect display within Asana.
- Upload screenshots as attachments *after* the task description is set — the order doesn't affect how Asana displays them, but it keeps the create → enrich flow linear and easier to debug.

**Progress reporting for this phase:**
> Uploaded screenshot "screen-03-mapping.png" → T4, T5, T6 (3 tasks)
> Uploaded screenshot "screen-04-validate.png" → T7 (1 task)
> Skipped T15 (Backend task — no relevant UI screen)

---

## Phase 4: Cleanup

### Originating Task Disposition

If the breakdown has an **Originating Task** section, handle it based on the specified action:

**Delete:** List the task name and GID, ask for confirmation, then delete.

**Complete:** Mark the task as complete and post a comment listing all newly created tasks via the `asana-api` skill. The comment should include each task's name and Asana URL, grouped by milestone. Author it as Asana rich text (HTML) — Markdown is not interpreted. Example body:

```html
<body>This task has been decomposed into the following implementation tasks:\n\n<strong>M1 :: Core Data Layer</strong><ul><li><a href="task-url">Setup employee entity + repository</a></li><li><a href="task-url">Employee CRUD API endpoints</a></li></ul><strong>M2 :: Employee Management UI</strong><ul><li><a href="task-url">Employee list page</a></li><li>...</li></ul></body>
```

**Both actions require explicit user confirmation** — no exceptions.

### Task Removal

If the breakdown specifies additional tasks to remove (via Source field pointing to existing Asana tasks):

1. List the tasks to be deleted with their names and GIDs.
2. **Ask the user for confirmation before deleting.**
3. Delete only after explicit confirmation.

---

## User Interaction Model

- **Do NOT present each task description for review.** The descriptions render mechanically from the breakdown; the user already approved the breakdown.
- **Do NOT ask implementation-ambiguity questions.** Those are resolved later during refinement.
- **Ask confirmation** only for destructive actions — task deletions in Phase 4.
- **If no questions, proceed silently.** Create the task and move on.
- **Report progress** — brief status updates so the user knows things are moving.

## Dependencies

- `asana-api` — all Asana API operations route through this skill (fetch project / sections / custom fields, create tasks, set custom fields, wire dependencies, post comments, delete tasks).
- `task-breakdown` — produces the input file this skill consumes. The two skills are intentionally paired: task-breakdown produces a markdown roadmap with rough estimates and validation; submit-breakdown faithfully replicates it into Asana.

This skill has no other skill dependencies. Whatever happens to the Asana tasks after submission (refinement, staffing, implementation) is outside this skill's contract.
