---
name: submit-breakdown
version: 0.2.0
description: >
  Pushes a task breakdown to the task manager by faithfully replicating the
  breakdown markdown into tasks. Use this skill whenever the user wants to submit,
  push, upload, publish, or create tasks from a task-breakdown file —
  "submit this breakdown", "upload this task-breakdown file", "push these tasks",
  "create tasks from the breakdown", "submit breakdown",
  "publish this plan", or after completing a task-breakdown and the user
  says "let's push it". Also triggers when the user provides a breakdown file
  path and a project URL together. Do NOT trigger on requests to create
  a single task, or to start working on an existing task. Also accepts a
  folder bundle containing `breakdown.md` plus per-milestone / per-task spec
  files (uploaded as task attachments).
---

# Submit Breakdown

Replicate a task breakdown (output of `task-breakdown` / `milestone-breakdown`) into the task manager. Implementation tasks land at **Refinement** product status by default; milestones are created as anchors. The skill performs no codebase analysis, resolves no ambiguities, and writes no implementation plans — those happen later during refinement, after the codebase has been read.

The goal: a faithful, low-friction, **idempotent** upload so the breakdown is visible in the task manager and ready for refinement. Re-running never re-creates or overwrites what already exists.

## Prerequisites

- The `task-manager` interface for all task operations — perform every operation through it. Never name a provider, an API, or an identifier (GID / issue key).
- **Perform operations directly via the `task-manager` interface — do not write helper scripts.** It is tempting to wrap the per-task creation loop in a Python or Node script that batches the calls. Don't. The agent has direct access to every operation needed here (create task, set fields, set status, add dependencies, ensure milestones, upload attachments, add comments, delete). Wrapping them in a script adds an opaque layer, hides individual failures, makes progress harder to report, and produces an artifact with no reason to persist. Make the operations one by one; report progress per task.
- A breakdown input (see Inputs) — markdown with milestones and/or tasks, dependencies, and optional attachments.
- A project URL — the target board where tasks will be created.
- The target board must support the **Refinement** lifecycle state (see `plugins/cortex-workflow/references/workflow/lifecycle.md`). The skill verifies this before doing anything else and aborts if it's missing.

## Inputs

1. **Breakdown input** — either:
   - a markdown file produced by `task-breakdown` (single-file legacy input), or
   - a folder bundle containing `breakdown.md` plus one or more attachment files. Bundle shapes (may be mixed):
     - **Milestone bundle** (from `milestone-breakdown`) — M-blocks only, with per-milestone `milestone-spec.md` attachments.
     - **Task bundle** (from `task-breakdown`) — T-blocks only, with per-task `implementation-plan.md` attachments, and an optional top-level `**Target milestone:**` line pointing at an existing milestone.

   Detection: if the input path resolves to a file, treat as single-file legacy input; if it resolves to a directory, look for `breakdown.md` inside — if present, parse it; otherwise error with: "No `breakdown.md` found in `<path>`. Expected a folder bundle."

   The parser is **polymorphic** — it accepts M-only bundles, T-only bundles (with or without `**Target milestone:**`), or mixed M+T content. The block types present in `breakdown.md` determine which Phase 3 steps run; see `references/breakdown-parser.md`.
2. **Project URL** — the target board in the task manager.

If either input is missing, ask for it before proceeding.

---

## Phase 1: Discovery (task manager only)

### 1a. Inspect the project

1. **Resolve the board** from the URL via `resolve_board` (or by passing the URL through the seam). Read its milestones with `list_milestones(board)` — each returns `{ref, name, expanded}`, where `expanded` means the milestone already has ≥1 member task. This is the landscape used for idempotency and expanded-milestone protection.
2. **Learn which fields the board carries** via `list_fields(board)`. The canonical workflow fields (see `plugins/cortex-workflow/references/workflow/fields.md`) this skill sets on implementation tasks are:
   - **Platform** — Backend, Frontend, Design, iOS, Android
   - **Category** — Feature Request, Technical Request, Bug, Customer Support, Documentation
   - **Priority** — P0, P1, P2, P3, P4
   - **Product Status** — a lifecycle state (see `plugins/cortex-workflow/references/workflow/lifecycle.md`)
3. **Pre-flight check.** Confirm the board supports the `Refinement` lifecycle state. If not, abort with:

   > This project does not support the `Refinement` lifecycle state. Add it in the task manager, then re-run submit-breakdown.

   `set_status(task, <name>)` addresses lifecycle states by name; the provider resolves the underlying representation, so the skill never handles status identifiers itself. Likewise `set_fields` resolves field names and option values by name — the skill never discovers or resolves any provider identifiers by hand.
4. **Read existing tasks per milestone** with `milestone_tasks(<milestone>)` for the milestones that matter, to understand current state — what exists, what the breakdown says to reuse or remove. This drives the idempotency checks in Phase 3.

### 1b. Resolve the optional `**Target milestone:**` line

If `breakdown.md` starts with a top-level `**Target milestone:** <task-url>` line:

1. Resolve the URL to a task handle via `find_task`, then `get_task` it.
2. Verify its `kind == milestone`. If not, abort: "Target milestone URL `<url>` does not point to a milestone."
3. Verify it lives on the supplied board. On mismatch, abort with a clear message.
4. Surface to the user and confirm before any write:

   > These tasks will be slotted under '<milestone name>' in project <project name>. Proceed? [Y/n]

5. On confirmation, store `target_milestone` (its ref) — every T-block in the bundle joins that milestone.

If the line is absent, do not error here — the T-block fallback prompt in Phase 3 Step 3 covers the no-context case.

This skill does **no codebase discovery**. The references embedded in each task description (aggregated by Phase 2) are what the downstream refinement step will read later.

---

## Phase 2: Render Descriptions

For each block in the breakdown, render its description by aggregating fields from the breakdown. A bundle's `breakdown.md` may contain a top-level metadata line, M-blocks, T-blocks, or any mix — the parser handles each independently (see `references/breakdown-parser.md`).

Read `references/description-template.md` for the full structure, content rules, and formatting rules.

Key principles:
- The description is a faithful render of the block — Purpose, Description, Out of scope (optional), Acceptance Criteria, References.
- Author descriptions in **Markdown**; the provider renders them. Do not hand-write provider markup or embed images inline.
- References aggregate from three levels (task entry, milestone block, file header) and are deduplicated by URL/path.
- No implementation-plan content. No file paths inferred. No analysis. If the breakdown didn't say it, the description doesn't say it.
- **No T-labels or M-labels in the description.** They are breakdown-internal identifiers, used only so the markdown can express dependencies before the task manager assigns handles. If a label appears in prose (e.g., "extends the schema introduced in T1"), replace it with the corresponding task link + title. The `Depends on:` field is **not** rendered into the description — dependencies are wired natively via `add_dependency` in Phase 3, where they show as blocking relationships. Never write a literal `T1`/`M2` into the task manager.
- No questions asked of the user during this phase. Any ambiguity is handled later, during the refinement step that reads the codebase.

---

## Phase 3: Submit to the Task Manager

Create objects in **dependency order** — milestones first, then implementation tasks, then wire dependencies once all handles exist.

### Block-presence routing (polymorphic bundle)

Each step is gated on the block types present in `breakdown.md`:

- **M-only bundle:** Steps 1 and 4 run; Steps 3 and 5 are no-ops.
- **T-only bundle:** Step 1 is a no-op (no M-blocks to create/wire); Step 3 (with Phase 1b / interactive parent-milestone resolution) and Step 5 run.
- **Mixed bundle** (incl. legacy single-file): all steps run.

Legacy single-file input is treated as a mixed bundle — implementation tasks sit under each milestone block.

### Step 0: Name-collision check (M-blocks only)

Before creating any milestone, compare each M-block's name against the `list_milestones(board)` result **by plain name** — strip a leading `M{n}: ` ordinal prefix from each landscape name (and from the block name if it carries one) before comparing, case-insensitive, so a block named "Zeta" matches an existing "M1: Zeta" (see `references/breakdown-parser.md` → "Milestone matching, ordinal assignment, and label remapping"). On a match, surface to the user:

> "Milestone '<name>' already exists in this project (<expanded|unexpanded>). Reuse / Rename / Abort?"

- **Reuse** → treat it as the existing milestone (Step 1 will reuse its ref; expanded protection in Step 1 still applies).
- **Rename** → prompt for a new name; retry the check.
- **Abort** → cancel the whole run.

Runs before any writes, so no partial state is left. After collision decisions, re-verify that every M-block `**Depends on:**` label still resolves to a milestone in the batch; if any points to a dropped one, ask whether to drop the dependent milestone too, drop the dependency, or abort.

### Step 1: Ensure each milestone (M-blocks only)

**Board naming — `M{n}:` ordinal prefix.** Milestones are named on the board as `M{n}: <Name>`, where `n` is a **board-assigned ordinal**, not the block's local M-label. Before creating anything, read the existing ordinals from the Phase 1 `list_milestones(board)` landscape (parse a leading `M{n}: ` from each name; unprefixed names count as no ordinal). The next ordinal is `max(existing ordinals) + 1` — new milestones continue the board's numbering rather than restarting at M1. Assign ordinals to the M-blocks that need creating in breakdown order, incrementing once per new milestone: a board already holding `M1:`–`M3:` names the first new block `M4:`. Reused milestones keep their existing name and ordinal. See `references/breakdown-parser.md` → "Milestone matching, ordinal assignment, and label remapping".

For each M-block, in breakdown order:

1. Decide reuse-vs-create by matching the block's **plain name** against the landscape (leading `M{n}: ` stripped from both sides, case-insensitive — Step 0). `ensure_milestone(board, <board name>)` — idempotent: for a **new** milestone pass the ordinal-prefixed `M{n}: <Name>`; for a **reused** one pass its existing board name so the same milestone is matched. It creates the milestone if missing, reuses it if present, returns its ref, and never overwrites an existing milestone's description.
2. **New milestone** (was just created — not present in the Phase 1 `list_milestones` landscape): set its description with `set_description(<milestone>, <rendered body>)` (see `references/description-template.md` → milestone body). Set **Priority** only via `set_field` (default `P3`; override only if the block specifies one). Do not set Platform, Category, or Product Status on a milestone.
3. **Existing milestone** (matched by plain name to the landscape, or via Step 0 Reuse):
   - If it is `expanded` (has member tasks per `list_milestones` / `milestone_tasks`), it is **protected**: do not touch its description or attachments. Log a divergence notice if the block body differs, and continue.
   - If it is unexpanded, still **do not overwrite** its description (frozen-on-rerun) — **unless** this block carries a `**Source:**` URL targeting it, which is a deliberate refine (see the Source path below). Log a notice if it has diverged.
4. Upload the block's `**Attachments:**` (renamed to `milestone-spec.md`) per the attachment procedure below — **skip entirely for expanded/protected milestones**.

**`**Source:**` refine path.** When an M-block carries `**Source:** <url>` (from `milestone-breakdown`'s refine mode), resolve the URL via `find_task` and verify `kind == milestone`; it is the explicit reuse target for that block — do not create a new milestone, and keep its existing board name/ordinal (no renumbering). Then:
- If the Source milestone is **expanded**, refuse: "Milestone '<name>' at <url> is expanded; bundle input cannot modify an expanded milestone." Never overwrite a milestone that already has work under it.
- If it is **unexpanded**, refresh its description with `set_description(<milestone>, <rendered body>)`. This is the one reuse case that overwrites a description — `**Source:**` is a deliberate refine request, unlike an incidental name-match on re-run (which stays frozen). Its spec attachment is replaced as usual (point 4).

Build a `local M-label → milestone ref` map for Step 4 — keyed by each block's **local** M-label (M1, M2, … in file order), valued by the resolved ref (whose board ordinal may differ). Always wire dependencies through this map; never assume a local M-label equals a board ordinal.

### Step 2: (reserved — merged into Step 1)

Milestone creation and its description/attachments are handled together in Step 1 via `ensure_milestone` + `set_description`. There is no separate "create section then milestone task" step — that provider-structural detail is internal to the seam.

### Step 3: Create implementation tasks (T-blocks only)

Resolve each T-block's parent milestone first:

- **T-block sits inside a wrapping `## M{N} ::` block in the same `breakdown.md`** → use that milestone's ref (from Step 1).
- **No wrapping M-block, but Phase 1b resolved a `**Target milestone:**`** → use the stored `target_milestone` ref.
- **No wrapping M-block AND no `**Target milestone:**`** → prompt the user once, before any T-task is created:

  > "Which milestone should these N tasks go under?"
  >
  > 1. <milestone name 1>
  > 2. <milestone name 2>
  > ...
  > N. (cancel)

  Build the list from the Phase 1 `list_milestones(board)` result. If the board has no milestones, ask for the project URL first, then re-read. Store the choice as `target_milestone` for the rest of the run.

For each T-block, resolve idempotency by matching its name within `milestone_tasks(<parent milestone>)`:

- **If a task with that name already exists in the milestone** → reuse its ref. **Never overwrite its description.** Still re-run the per-block attachment upload below (attachments are replaced on every submit — see Re-run behavior).
- **If missing** → `create_task(title, description, board, kind=task, milestone=<parent milestone ref>, fields={Platform, Category, Priority})`:
  - `title` — from the breakdown task title (no platform prefix; Platform is a field).
  - `description` — rendered in Phase 2 (Markdown; the provider renders it).
  - `kind=task` and `milestone=<ref>` so the task joins the milestone natively.
  - `fields` — `Platform` and `Category` from the block, `Priority` default `P3`. Prefer this one-shot `fields` map over separate `set_field` calls. (If a board omits a field, the seam skips it gracefully.)

After the task ref is known (created or reused), upload the T-block's `**Attachments:**` (renamed to `implementation-plan.md`) per the attachment procedure below.

Then set **Product Status** via `set_status`, using this matrix (first match wins; lifecycle names from `plugins/cortex-workflow/references/workflow/lifecycle.md`):

- **Platform = `Design`** → `set_status(task, "Unassigned")`. Design work isn't refinable by Claude (producing Figma/wireframes/specs is outside this tooling's reach), so it skips Refinement and goes to the staffing pool.
- **Plan attached** — after the attachment upload, the task has an `implementation-plan.md` attachment (check via `get_attachments`) → `set_status(task, "Unassigned")`. The plan is the refinement output; the task is ready for staffing.
- **Otherwise** → `set_status(task, "Refinement")` so the downstream refinement step picks it up.

Set Product Status *after* the attachment upload so the decision can observe the final attachment list.

Build a `T-label → task ref` map for Step 5.

### Step 4: Wire milestone-level dependencies (M-blocks only)

For each M-block whose `**Depends on:**` lists other **local** M-labels: resolve each label to a ref via the `local M-label → milestone ref` map from Step 1 (the map absorbs any renumbering — a block's local `M1` may be `M4:` on the board), then `add_dependency(<this milestone>, <depended-on milestone>)`. Wire by ref, never by the literal label.

### Step 5: Wire task-level dependencies (T-blocks only)

For each T-block whose `**Depends on:**` lists T-labels: for each dependency, `add_dependency(<this task>, <depended-on task>)` using the `T-label → ref` map.

`add_dependency` is non-destructive when re-applied with the same set, so re-runs are safe.

### Attachment procedure (shared)

For each file path in a block's `**Attachments:**` list:

1. Resolve the path relative to `breakdown.md`'s folder; verify it exists.
2. Rename on upload — `milestone-spec.md` for M-blocks, `implementation-plan.md` for T-blocks (strip any local `M{N}-` / `T{N}-<slug>-` ordering prefix).
3. **On re-runs (replace, not duplicate):** if an attachment with that target name already exists on the task (`get_attachments`), `remove_attachment(task, <it>)` first, then `upload_attachment(task, <path>)`.

### Re-run behavior

submit-breakdown is **idempotent and non-destructive on re-run**:

- Existing milestones and existing implementation tasks are detected (by the match keys below) and reused — never re-created, and their **descriptions are never overwritten** (frozen-on-rerun). The one exception: an unexpanded milestone targeted by a `**Source:**` refine has its description refreshed (Step 1).
- **Expanded milestones are protected** — an expanded milestone's description and attachments are never touched.
- Dependency wiring is re-applied; `add_dependency` is non-destructive for the same set.
- **Attachments are replaced on every re-run** (remove old by name, upload new) — the local spec/plan file is the source of truth. This is intentionally asymmetric with descriptions (frozen) — attachments track the local file. To also update a frozen description, delete the task and re-run.
- If a block's body has diverged from an existing task's/milestone's description, log a one-time notice (e.g. `Milestone "Billing" already exists; body has diverged (skipping)`) and continue. Do not prompt mid-run.

### Idempotency match keys

| Object | Match key |
|---|---|
| Milestone | plain `name` on the board — leading `M{n}: ` ordinal prefix stripped (via `list_milestones` / Step 0) |
| Implementation task | `name` within its parent milestone (via `milestone_tasks`) |

### Progress reporting

Report per object as it is created or reused:

```
Created milestone: "Employee Management"
Reused milestone: "Data Layer" (already present)
Created: "Setup employee entity" (Employee Management) — Backend · Refinement
Reused: "Employee list page" (Employee Management) — already present
Wired milestone deps: "Employee Management" depends on "Data Layer"
Wired task deps: "Employee list page" depends on "Employee CRUD API"
```

After all objects + dependencies are wired, summarize (adapt to actual counts; omit lines that don't apply):

> All milestones + tasks reconciled with the task manager.
>   • <K_new> new milestones, <K_existing> reused
>   • <M_new> new tasks at Refinement, <U_new> at Unassigned (Design or plan-attached)
>   • <M_existing> tasks reused
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
- The T-label → task map built in Phase 3 Step 3 remains valid here — use T-labels internally for screenshot-to-task bookkeeping. The "No T-labels in the task manager" rule applies to task description content only, not to in-session mapping.

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

**Core Data Layer**
- [Setup employee entity + repository](task-url)
- [Employee CRUD API endpoints](task-url)

**Employee Management UI**
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
- **Ask confirmation** only for: destructive actions (task deletions in Phase 4), milestone name collisions (Phase 3 Step 0), the `**Target milestone:**` confirmation (Phase 1b), and the interactive parent-milestone pick (Phase 3 Step 3).
- **If no questions, proceed silently.** Create the task and move on.
- **Report progress** — brief status updates so the user knows things are moving.
- **Report divergence notices but do not act on them.** If the md has changed and an existing milestone/task description differs, log the notice once per object and continue. Do not prompt mid-run.

## Dependencies

- `task-manager` — all task operations route through this interface (resolve board / milestones / fields, create tasks, ensure milestones, set fields and status, wire dependencies, upload attachments, post comments, delete tasks).
- `task-breakdown` — produces task bundles this skill consumes: a folder of `breakdown.md` (T-blocks, optional `**Target milestone:**`) + per-task `implementation-plan.md` attachments. submit-breakdown replicates them, uploads the attachments, and drives each T-task's Product Status from attachment presence.
- `milestone-breakdown` — produces milestone bundles this skill consumes: a folder of `breakdown.md` (M-blocks) + per-milestone spec files. submit-breakdown replicates them with milestone reuse and attachment upload.

This skill has no other skill dependencies. Whatever happens to the tasks after submission (refinement, staffing, implementation) is outside this skill's contract.
