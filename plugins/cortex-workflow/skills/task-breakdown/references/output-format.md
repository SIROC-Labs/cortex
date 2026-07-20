# Output Format

This file defines the canonical layout of the task-breakdown folder bundle: `breakdown.md` (T-blocks only) plus one `T{N}-<slug>-implementation-plan.md` per task. It includes the `breakdown.md` template, the parsing contract that `submit-breakdown` reads against, and the T-block field reference.

## Folder Location

Folder path: `<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<slug>/`

Resolve repo root via `git rev-parse --show-toplevel`. If the folder already exists, append `-v2`, `-v3`, … until the name is free.

Slug heuristic: short, descriptive, all lowercase, hyphen-separated, derived from the scope title. Examples: `auth-redesign-tasks`, `mobile-onboarding-tasks`, `billing-invoice-export`.

Create the folder if it doesn't exist. The folder is a local working artifact — it does not need to be committed; persistence into the task manager is handled by `submit-breakdown`.

## breakdown.md template

```markdown
# Task Breakdown — <Slug>

**Target milestone:** <milestone-task-url>   ← optional metadata; consumed by submit-breakdown

## T1 :: <Task title>

**Purpose:** <one sentence — why this task exists, from the user's perspective>
**Description:** <2–3 sentences in product language — what the user sees or experiences when this is done>
**Acceptance criteria:**
- <observable outcome 1>
- <observable outcome 2>
**References:** Figma - <label>: <url>   ← optional; design/visual links especially
**Depends on:** T2, T3   ← optional
**Attachments:**
- T1-<slug>-implementation-plan.md

## T2 :: <Task title>
...
```

- **No M-blocks.** task-breakdown never authors milestone content.
- **No file-level References block, no rationale paragraphs.** Do not add a top-of-file `## References` section. **Per-task references, however, belong on the T-block as an optional `**References:**` field** — `submit-breakdown` aggregates that field into the task description (as the top "Visual Context" Figma link and the References list). This is the *only* path a task-specific design link reaches the task: the implementation-plan attachment is generated later and is not parsed for references. So a Figma frame that applies to one task must go on that T-block's `**References:**`, not solely in the attachment. Keep the field to genuinely load-bearing, non-obvious links (design frames, external API/doc URLs, a related task) — the same allowed-list `submit-breakdown` applies; do not restate CLAUDE.md, the repo, or the breakdown file.
- **T-labels are sequential across the whole file** (T1, T2, T3 …) and local-only — they carry no meaning outside this file.
- **`**Target milestone:**`** (optional) appears once at the top, immediately after the title. It is **metadata, not a directive** — `submit-breakdown` always confirms with the user before slotting tasks under that milestone.
- **Attachment filenames carry the `T{N}-<slug>-` prefix locally** for ordering. `submit-breakdown` strips that prefix and uploads each file as `implementation-plan.md` on its target task.

## Parsing Contract

| Field | Role | Pushed to task description? |
|---|---|---|
| File-level `**Target milestone:**` (optional) | Routing metadata | No — parsed once at the file level, used to resolve which milestone parents the tasks (user-confirmed) |
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Acceptance criteria:**` | Body | Yes |
| `**References:**` (optional) | Body | Yes — aggregated by `submit-breakdown` into the description's Visual Context (Figma) link and References list |
| `**Depends on:**` (optional) | Dependency metadata | No — parsed for T-labels, used to wire native task dependencies |
| `**Attachments:**` | Attachment metadata | No — file list uploaded as attachments (renamed to `implementation-plan.md` per the upload contract) |

Parsing rules:

- For each `## T{N} :: <Name>` header → one implementation task.
- Collect body fields → render them as the task description, verbatim, in the canonical order: **Purpose → Description → Acceptance criteria → References**. (`submit-breakdown` promotes any Figma URL in References to the top-of-description Visual Context link; see `submit-breakdown/references/description-template.md`.)
- Collect metadata fields → route per the table above.
- The optional file-level `**Target milestone:**` line is parsed once at the top of the file and applies to every T-block. It is not pushed to any task description.

Authoring convention is body fields first, then metadata fields, with `**Attachments:**` last. `submit-breakdown` picks fields by name, so order in the file is not load-bearing — but the convention keeps the file human-readable.

## T-Block Field Reference

### T-labels

T1, T2, T3 … are internal to this document only. They exist solely for expressing dependencies within the bundle. They carry no meaning outside this file and are never used by downstream tools as identifiers.

T-labels are assigned sequentially across the entire bundle, not per-area. If the bundle has 12 tasks, the labels run T1 … T12 in the order tasks appear in `breakdown.md`.

### Purpose

One sentence: why this task exists and what it achieves, from the user's perspective. Pulled through to the task description verbatim.

### Description

2–3 sentences in product language that explain the task to anyone on the team — PM, designer, developer, QA. The test: could a product manager read this and immediately understand what's being built and why it matters to the user?

**Keep it brief and high-level.** Do not embed inline enumerations like `(1) Campaign — …; (2) Creative — …`. If a task has multiple components, name them in summary prose and let the Acceptance criteria carry the specifics. A description that lists every domain model, port method, or technical pattern is too long — that detail belongs in the implementation-plan attachment.

**Write in product language, not developer language.**

| Instead of… | Write… |
|---|---|
| "Build a data-fetching layer over GET /v2/parameters" | "When the wizard loads, the app fetches the list of available macro intents and ad servers so the dropdowns in later steps always reflect current options." |
| "Implement POST /campaigns with idempotency key" | "Clicking 'Publish' submits the campaign to the DCO system; the app prevents double-submission if the user clicks twice." |
| "Add useCallback memoization to prevent re-renders" | "The mapping table stays responsive even with 300+ rows — this task optimises it so it doesn't lag as the user types." |

The description explains **what the user sees or does** and **why it matters**. Technical approach (which endpoint, which hook, which pattern) lives in the implementation-plan attachment.

One practical check: if your description only makes sense to a developer who already knows the codebase, rewrite it.

### Acceptance Criteria

Observable outcomes that verify the task is complete. These should be checkable by looking at the running system or the code — not by reading the implementer's mind.

Good: "Employee list page displays all employees with name, role, and department columns"
Bad: "Employee list works correctly"

Good: "API returns 404 with error message when employee ID doesn't exist"
Bad: "Error handling is implemented"

### References (optional)

A short list of genuinely load-bearing, non-obvious links for this specific task — **design/visual frames above all** (Figma, prototype, mockup), plus external API/doc URLs or a related task that provides context the codebase doesn't. Preserve a descriptive label, e.g. `Figma - Onboarding page 3: https://figma.com/…?node-id=4001-9734`.

This is the field that carries a **task-specific** design into the task manager: `submit-breakdown` promotes any Figma URL here to the top-of-description "Visual Context" link and lists the rest under References, and `refine-tasks` then copies them into the plan's Design / Visual references section. A design frame left only inside the implementation-plan attachment never reaches either place — put it here.

Apply the same allowed-list `submit-breakdown` enforces: do **not** list CLAUDE.md files, the repo/project URL, the breakdown document itself, or anything a fresh session would auto-discover. Omit the field entirely when the task has no such links — do not write "None".

### Neutral Fields (Platform / Category / Priority)

Field intent is captured with the neutral names from `plugins/cortex-workflow/references/workflow/fields.md` — never provider terms. task-breakdown does not write fields; `submit-breakdown` maps them through the seam.

- **Platform** — one of Backend / Frontend / iOS / Android / Design (see `references/decomposition-principles.md` → "Platform Splits").
- **Category** — the kind of work (Feature / Technical / Bug), per the `Type / Category` field.
- **Priority** — urgency; left at the workflow default unless the user names one.

### Depends on (optional)

List of T-labels that must be completed before this task can start. Omit the field entirely when the task has no dependencies — do not write "None".

Cross-platform dependencies are normal (a Frontend T depending on a Backend T, an iOS T depending on a Design T).

### Attachments

List of files in the same folder as `breakdown.md` to upload as attachments on this task. The canonical entry is the per-task implementation plan:

```
**Attachments:**
- T{N}-<slug>-implementation-plan.md
```

`submit-breakdown` renames the file to `implementation-plan.md` at upload time (stripping the `T{N}-<slug>-` prefix — local-only ordering). Re-runs match by the renamed filename and replace.

A task with an implementation plan attached lands `Unassigned`. A task with no plan attached lands `Refinement`.

## Target Milestone Convention

The optional `**Target milestone:**` line at the top of `breakdown.md` is metadata that surfaces the user-named milestone into `submit-breakdown` discovery. Shape:

```markdown
**Target milestone:** <milestone-task-url>
```

It is a milestone task URL — resolved through the `task-manager` seam (`get_task`), whose `kind` must be `milestone`. It is not a directive. `submit-breakdown` resolves the URL, surfaces the milestone name, and confirms with the user before slotting any task. If the line is absent and the T-blocks have no other parent context, `submit-breakdown` prompts at upload time: "Which milestone should these N tasks go under?"

Author this line when the input shape made the parent milestone unambiguous (e.g., the user passed a milestone task URL, or named a milestone explicitly during the interview). Omit otherwise — let `submit-breakdown` interactively resolve.

## Implementation-Plan Attachments

Per-task implementation plans live as separate files in the same folder, named `T{N}-<slug>-implementation-plan.md`. They are generated from the shared template at `plugins/cortex-workflow/skills/refine-tasks/references/implementation-plan-template.md`.

The local `T{N}-<slug>-` prefix is for sort order and uniqueness inside the bundle. `submit-breakdown` strips it at upload — every plan lands as `implementation-plan.md` on its task.
