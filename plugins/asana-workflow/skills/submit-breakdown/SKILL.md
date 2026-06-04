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
- The `asana-api` skill must document **Create Milestone Task** and **Detect Milestone Subtype** (see `asana-api/SKILL.md`). submit-breakdown depends on these patterns to create and detect milestone-subtype tasks.

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

6. **Detect existing milestone tasks per section.** For each section, list its tasks with `opt_fields=name,resource_subtype` and identify any task where `resource_subtype == "milestone"`. Build a per-section map: `section_name → milestone_task_gid | None`. This map drives the idempotency check in Phase 3.

This skill does **no codebase discovery**. The references embedded in each task description (aggregated by Phase 2) are what the downstream refinement step will read later.

---

## Phase 2: Render Descriptions

For each task in the breakdown, render the Asana task description by aggregating fields from the breakdown.

Read `references/description-template.md` for the full structure, content rules, and formatting rules.

Key principles:
- The description is a faithful render of the breakdown task entry — Purpose, Description, Out of scope (optional), Acceptance Criteria, References.
- References aggregate from three levels (task entry, milestone block, file header) and are deduplicated by URL/path.
- No implementation-plan content. No file paths inferred. No analysis. If the breakdown didn't say it, the description doesn't say it.
- **No T-labels in the Asana description.** T-labels (`T1`, `T2`, …) are internal to the breakdown markdown only — they exist solely so the breakdown can express dependencies before Asana GIDs exist. If a T-label appears in prose (e.g., "extends the schema introduced in T1"), replace it with the corresponding Asana task link + title. The `Depends on:` field is **not** rendered into the description at all — dependencies are wired natively via `asana_set_task_dependencies` in **Phase 3 Steps 4 and 5**, where they are visible as blocking relationships in Asana. Never write the literal `T1`, `T2`, … into Asana.
- No questions asked of the user during this phase. Any ambiguity is handled later, during the refinement step that reads the codebase.

---

## Phase 3: Submit to Asana

Create objects in **dependency order** — sections first, then milestone tasks, then implementation tasks. Wire dependencies at the end so all GIDs exist.

### Step 1: Ensure each section exists

For each milestone in the breakdown:

- Look up the section by milestone name in the project.
- If missing, create it. Section order follows the milestone order in the breakdown markdown.

### Step 2: Ensure each milestone task exists

For each milestone in the breakdown:

- **Thin milestone block** (no `Purpose:` field, has `Source:` pointing to an existing milestone task):
  - Resolve the existing milestone task GID via the `Source:` URL. If the URL is missing or invalid, fall back to looking up the section's milestone-subtype task from the Phase 1 step-6 map. Record the GID.
  - **Do not create** a new milestone task and **do not update** the existing description.

- **Rich milestone block** (has `Purpose:` field):
  - Look in the section for an existing task where `name == milestone_name AND resource_subtype == "milestone"`.
  - **If found** → reuse the GID. Do not update the description (see "Re-run behavior" below).
  - **If missing** → create with:
    - `name` = milestone name
    - `resource_subtype` = `"milestone"`
    - `html_notes` = rendered milestone description (per `references/description-template.md` → "Milestone Task Description"), wrapped in `<body>...</body>`
    - Add to project, move to the section.
    - Custom fields: **Priority only** (default `P3`; override only if the milestone block explicitly specifies one). Do not set Platform, Category, or Product Status.

Build an M-label → milestone_task_gid map for use in Step 4.

### Step 3: Create implementation tasks

For each implementation task in the breakdown (when present):

- Look in the section for an existing task with `name == task_name AND resource_subtype == "default_task"`.
- **If found** → reuse the GID and skip create (idempotent re-run).
- **If missing** → create with:
  - `name` from the task title (no platform prefix; Platform is a custom field)
  - `html_notes` = rendered implementation task description (per `references/description-template.md` → "Implementation Task Description")
  - Section = the milestone's section
  - Custom fields:
    - Platform — from the breakdown task entry
    - Category — from the breakdown task entry
    - Priority — default `P3`
    - **Product Status** — conditional on Platform:
      - Platform `Design` → `Unassigned`
      - everything else → `Refinement`

Build a T-label → task_gid map.

### Step 4: Wire milestone-level dependencies

For each milestone whose breakdown block has `Depends on: M2, M3`:

```
asana_set_task_dependencies(
  task_id      = M-label → GID map[Mn],
  dependencies = [M-label → GID map[Mi] for each Mi in Depends on]
)
```

### Step 5: Wire task-level dependencies

For each implementation task whose entry has `Depends on: T2, T3`:

```
asana_set_task_dependencies(
  task_id      = T-label → GID map[Tn],
  dependencies = [T-label → GID map[Ti] for each Ti in Depends on]
)
```

### Re-run behavior

submit-breakdown is **idempotent and non-destructive on re-run**:

- Existing sections, existing milestone tasks, and existing implementation tasks are detected (by match keys below) and reused — they are never re-created and their descriptions are never overwritten.
- Dependency wiring is re-applied. Asana's `set_task_dependencies` is non-destructive when given the same set, so re-runs are safe.
- If a milestone block in the md has diverged from the existing Asana milestone task description, log a notice (e.g., `M2 milestone task already exists; its description has diverged from the md (skipping)`) but do not act on it. The user has two ways to push md changes back into Asana: delete the Asana task and re-run, or edit the description manually.

### Idempotency match keys

| Object | Match key |
|---|---|
| Section | `name` (within project) |
| Milestone task | `(section, name, resource_subtype == "milestone")` |
| Implementation task | `(section, name, resource_subtype == "default_task")` |

### Pre-flight checks (additions)

- **(Existing)** Product Status field on the project must include the `Refinement` enum option.
- **(New)** The first milestone-task create attempt also acts as a capability probe — if Asana rejects `resource_subtype: "milestone"` with a clear error, abort with: "Asana rejected milestone-subtype task creation. Check project / workspace permissions or contact Asana support." (This rejection is unexpected on standard task types.)

### Progress reporting

Report per object as it is created or reused:

```
Section ready: "Employee Management" (M2)
Created milestone: "Employee Management" (M2) — section "Employee Management"
Reused milestone: "Data Layer" (M1) — already in section
Created: "Setup employee entity" (M2) — Backend · Refinement
Reused: "Employee list page" (M2) — already in section
...
Wired milestone deps: M2 depends on M1
Wired task deps: T7 depends on T3, T4
```

After all objects + dependencies are wired, summarize (adapt to actual counts; omit lines that don't apply):

> All N milestones + M tasks reconciled with Asana.
>   • <K_new> new milestone tasks, <K_existing> reused
>   • <M_new> new implementation tasks at Refinement, <D_new> at Unassigned (Design)
>   • <M_existing> implementation tasks reused
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
curl -X POST https://app.asana.com/api/1.0/attachments \
  -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  -F parent=<task_gid> \
  -F file=@/path/to/screenshot.png
```

Use `curl -F` for multipart uploads — Python's `urllib` doesn't have built-in multipart support and constructing it manually is error-prone. Do NOT write a helper script; make one `curl` invocation per task attachment. The bearer token is required — Asana returns 401 without it.

**Screenshot-to-task mapping heuristic:**
- Wizard step screens → map to all tasks within that milestone (the whole step is one user-facing increment)
- Modal/overlay screens → map to the specific task that builds that modal
- Config forms with multiple sections → map the same screenshot to all tasks that build sections of that form
- Post-publish / terminal state screens → map to the task that builds that state

**Important constraints:**
- `<img>` tags are NOT supported in Asana `html_notes` — do not attempt to embed screenshot URLs inline. Images must be file attachments. See `references/description-template.md` for details.
- Asana attachment view URLs contain `&`-separated query parameters with expiry timestamps (`?e=...&v=0&t=...`). These are signed URLs that Asana re-signs when serving to authenticated users; the expiry in the URL does not affect display within Asana.
- Upload screenshots as attachments *after* the task description is set — the order doesn't affect how Asana displays them, but it keeps the create → enrich flow linear and easier to debug.
- The T-label → GID map built in Phase 3 Step 1 remains valid here — use T-labels internally for screenshot-to-task bookkeeping. The "No T-labels in Asana" rule applies to task description content only, not to in-session mapping.

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
- **Report divergence notices but do not act on them.** If the md has changed and an existing milestone/task description differs, log the notice once per object and continue. Do not prompt the user mid-run.

## Dependencies

- `asana-api` — all Asana API operations route through this skill (fetch project / sections / custom fields, create tasks, set custom fields, wire dependencies, post comments, delete tasks).
- `task-breakdown` — produces the input file this skill consumes. The two skills are intentionally paired: task-breakdown produces a validated markdown roadmap; submit-breakdown faithfully replicates it into Asana.

This skill has no other skill dependencies. Whatever happens to the Asana tasks after submission (refinement, staffing, implementation) is outside this skill's contract.
