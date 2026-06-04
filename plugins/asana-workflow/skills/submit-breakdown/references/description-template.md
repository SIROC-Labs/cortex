# Task Description Template

Each Asana task description is a **thin, faithful render** of one entry from the breakdown markdown — either a task entry (`### Tn ...`) or a milestone block (`## Mn :: ...`). References are aggregated from the levels above so the description is self-contained.

The description does **not** contain an implementation plan. That is produced later during refinement and attached as an `implementation-plan.md` file on the same Asana task. Milestone tasks never have an implementation plan — they are anchors, not work items.

## Two Description Types

`submit-breakdown` renders two kinds of Asana task descriptions:

- **Implementation task description** — for regular tasks (`resource_subtype == "default_task"`). Structure: Visual Context, Purpose, Description, Out of scope (optional), Acceptance Criteria, References. Detailed in "Implementation Task Description" below.
- **Milestone task description** — for milestone tasks (`resource_subtype == "milestone"`). Structure: Purpose, Description, Product Requirements, Out of scope (optional), Acceptance Criteria (milestone-level), References. Detailed in "Milestone Task Description" below.

Use the milestone renderer when the breakdown's milestone block carries the rich fields (Purpose, Description, Product Requirements, Acceptance Criteria, References). Use the implementation-task renderer for entries under `### Tn — ...`.

---

## Milestone Task Description

The Asana milestone task is the canonical context for the milestone — it must be self-sufficient. Render the milestone block's content with this structure (Asana HTML):

```html
<strong>Purpose</strong>
<one sentence from milestone block "Purpose:" field>

<strong>Description</strong>
<paragraph from milestone block "Description:" field>

<strong>Product Requirements</strong>
<ul><li>use case 1</li><li>use case 2</li>...</ul>

<strong>Out of scope</strong>           ← only when milestone block has "Out of scope:"
<ul><li>exclusion 1</li>...</ul>

<strong>Acceptance Criteria</strong>
<ul><li>outcome 1</li><li>outcome 2</li>...</ul>

<strong>References</strong>
<ul><li>...</li></ul>
```

### Milestone reference aggregation

References for a milestone task description aggregate from **two** levels:

1. The milestone block's `References:` field (if present)
2. The file-header `## References` section

Deduplicate by exact URL/path. Preserve order: milestone-specific first, then file-header. Use the same stripping rules as task-level aggregation (no breakdown md, no `CLAUDE.md`, no target project URL, no trivially auto-discoverable refs).

**Never** reference the breakdown markdown file. The milestone task description must remain self-sufficient and portable.

### Milestone description rules

- **No rationale paragraph.** The milestone block's rationale paragraph is md-only — it is not rendered into Asana.
- **No "Depends on" text.** Milestone-to-milestone dependencies are wired natively via `asana_set_task_dependencies` (see `SKILL.md` Phase 3).
- **No T-labels.** Same rule as today — T-labels are breakdown-internal identifiers.
- **Thin milestone blocks render nothing.** A thin milestone block has no `Purpose:` field and points to an existing Asana milestone via `Source:`. submit-breakdown looks up the existing task and skips description rendering entirely. See `SKILL.md` for the lookup procedure.

---

## Implementation Task Description

Use Asana HTML formatting (see Formatting Rules below).

### 0. Visual Context (Figma / Screenshot)

**Only include this section when visual references exist.** It renders before Purpose so a developer opening the task sees the design immediately.

**Figma link:** If a Figma URL exists in the aggregated references (task, milestone, or file header), render it as a standalone link at the very top of the description body, before all other content:

```html
<a href="https://figma.com/...">→ View in Figma</a>
```

Use the label from the breakdown (e.g. "Figma — Mapping step" → `→ Figma — Mapping step`). If the breakdown says "Not yet available" or has no Figma URL, skip this line entirely — do not render a placeholder.

**Screenshots from a prototype:** Asana's `html_notes` does **not** support `<img>` tags — the API returns an XML parsing error if you include one. Screenshots must be uploaded as file attachments via `POST /attachments` with `parent=<task_gid>`. Asana then displays them as image thumbnails visible immediately below the description. See Phase 3.5 in the skill for when and how to upload them.

Do **not** try to embed screenshot URLs inline in the description. It will fail.

### 1. Purpose

One sentence: why this task exists and what it unlocks. Pull verbatim from the breakdown task entry's `Purpose:` field.

> Implements the employee CRUD API so the frontend can list, create, and edit employees.

### 2. Description

2–3 sentences from the breakdown task entry's `Description:` field, rendered verbatim (or rewritten per the rule below).

The description must be written in **product language** — what the user sees or experiences, not how it is coded. A PM, designer, or QA engineer reading this task should immediately understand what's being built and why. Implementation details (which endpoint, which hook, which component pattern) are not needed here and will be added during refinement.

**Keep it brief and high-level.** Do not embed inline enumerations like `(1) Campaign — …; (2) Creative — …; (3) Parameters — …`. If a task has multiple components, name them at a summary level in prose and let the Acceptance criteria carry the specifics.

If the breakdown description is too developer-centric (leads with a class name, an API call, or a framework pattern) or too long, rewrite it in product terms before rendering it into the Asana task. This is the one case where submit-breakdown is allowed to rephrase breakdown content — the goal is a description any team member can understand, not a literal transcription of technical shorthand.

### 3. Out of scope

Optional. Only render this section when the breakdown task entry has an `Out of scope:` field. Each restriction is a bullet, each suffixed with "— that is a separate task" when it refers to other work in the breakdown.

Omit this section entirely when the breakdown has no `Out of scope:` field.

### 4. Acceptance Criteria

The bullet list from the breakdown task entry's `Acceptance criteria:` field, verbatim.

### 5. References (aggregated)

A single bullet list aggregating references from three levels of the breakdown:

1. The task entry's own `References:` field (if present)
2. The milestone block's References (if present)
3. The breakdown file header's References (always present)

Each bullet preserves the descriptive label from the breakdown (e.g., `Spec: docs/spec.md`, `Figma: https://figma.com/…`, `Backend models: src/core/users/`).

**Aggregation rules:**

- Deduplicate by exact URL or file path — a reference repeated at multiple levels appears once.
- **Drop the section-0 Figma URL.** If a Figma URL was rendered as the section-0 visual context link at the top of the description, exclude it from the References list — otherwise it appears twice. Any other Figma URLs (not used in section 0) still belong in References.
- Preserve order: task-specific first, then milestone-level, then file-header references. (This puts the most-specific source at the top.)
- Labels come verbatim from the breakdown; do not paraphrase.
- Repetition *across* tasks in the same milestone is expected and acceptable. Every task is meant to be a complete, self-contained refinement input.
- **Only carry non-obvious references.** A reference is worth carrying only when it points to material the downstream agent could not reasonably find on its own. Strip everything else during aggregation — it is pure context noise. Specifically, **always exclude**:
  - **Task-breakdown files** — the breakdown being submitted, or any other one. Recognize them by path (e.g., anything under `docs/cortex/*.md`) or by label (`Task Breakdown:`, `Breakdown:`, or any label that names another breakdown document). They are meta-documents that bundle every milestone and task in scope; if a downstream step follows the reference, the entire breakdown gets pulled in.
  - **CLAUDE.md files at any level** — root `CLAUDE.md`, `backend/CLAUDE.md`, `frontend/CLAUDE.md`, `mobile/CLAUDE.md`, etc. Claude auto-loads these from the working directory; calling them out as references adds zero information and clutters the description. Strip them regardless of label (`Backend conventions:`, `Root conventions:`, `Frontend conventions:`, etc.).
  - **The target Asana project URL itself** — every task already lives inside that project; pointing back to it is tautological. (Other Asana task URLs that point to *related but separate* work are fine to keep.)
  - **Anything else trivially auto-discoverable** — the repo URL, the worktree root, generic onboarding pointers a fresh session would already see. If the agent would find it without being told, do not reference it.

  Keep references that are genuinely load-bearing: spec docs, Figma frames, external library/API docs, specific Asana tasks providing context not derivable from the project, design system pages, RFC links, etc. The bar is *"would a reader without this link be missing something they can't otherwise find?"* — if the answer is no, drop the line.

---

## Example

For a task entry in the breakdown that looks like:

```markdown
### T3 — Backend — Feature Request — Employee CRUD API endpoints
**Purpose:** Implements the employee CRUD API so the frontend can list, create, and edit employees.
**Description:** Add GET/POST/PUT/DELETE endpoints under /employees. Soft-delete on DELETE. Return 404 with error message for unknown IDs.
**Acceptance criteria:**
- GET /employees returns all employees with name, role, department
- POST /employees creates and returns entity with generated ID
- GET /employees/{id} returns 404 with error message for nonexistent IDs
- DELETE soft-deletes (sets is_active=false)
**Out of scope:** Do NOT implement pagination or filtering. Do NOT add role-based access control.
**Depends on:** T1, T2
**References:**
  - API style guide: docs/api-style.md
```

inside an `M1` milestone with `References: Sprint plan: https://asana.com/...` and a file header `References: Spec: docs/spec.md, Figma: https://figma.com/file/abc`, the Asana task description becomes:

```html
<a href="https://figma.com/file/abc">→ Figma</a>

<strong>Purpose</strong>
Implements the employee CRUD API so the frontend can list, create, and edit employees.

<strong>Description</strong>
Adds CRUD endpoints for employees — create, read, update, and soft-delete — so the frontend can manage employee records against a live backend.

<strong>Out of scope</strong>
<ul><li>Do NOT implement pagination or filtering — that is a separate task.</li><li>Do NOT add role-based access control — that is a separate task.</li></ul>
<strong>Acceptance criteria</strong>
<ul><li>GET /employees returns all employees with name, role, department</li><li>POST /employees creates and returns entity with generated ID</li><li>GET /employees/{id} returns 404 with error message for nonexistent IDs</li><li>DELETE soft-deletes (sets is_active=false)</li></ul>
<strong>References</strong>
<ul><li>API style guide: <em>docs/api-style.md</em></li><li>Sprint plan: <a href="https://asana.com/...">https://asana.com/...</a></li><li>Spec: <em>docs/spec.md</em></li></ul>
```

---

## Content Rules

- **Render, don't analyze.** This template renders the breakdown verbatim. Do not infer new content, add file paths the breakdown didn't mention, or speculate about implementation. That is handled later during refinement, when the codebase is read.
- **Aggregate references unconditionally.** Even if a milestone has only one task, embed the milestone's references in that task — every task must be self-contained when read in isolation.
- **Preserve labels verbatim.** Reference labels come from the breakdown's References lines exactly. Do not normalize, rename, or "clean up" labels.
- **Skip empty sections.** If the breakdown has no `Out of scope:` or no task-level `References:`, simply omit those bullets — do not render an empty section.
- **No T-labels in the Asana description.** T-labels (`T1`, `T2`, …) are breakdown-internal identifiers — they only exist so the breakdown markdown can express dependencies before Asana GIDs exist. Resolve every T-label reference (prose mentions, examples) to the corresponding Asana task link + title. Never write the literal `T1`, `T2`, … into the Asana task description.

---

## Formatting Rules (Asana HTML)

Asana renders a subset of HTML. These rules produce clean, compact descriptions.

### Tags to use
- `<strong>` for section titles (Purpose, Description, Out of scope, Acceptance criteria, References)
- `<em>` for file paths, function names, types, and technical terms
- `<ul><li>` for bullet lists
- `<a href="...">` for links (Figma URLs, external docs, dependency Asana links)

### Tags to avoid
- Never use `<h1>`, `<h2>`, or any heading tags — they add excessive whitespace in Asana
- Never use `<code>` or `<pre>` — Asana renders them poorly
- Never use `<br>` between sections — use `\n` only
- **Never use `<img>`** — Asana's `html_notes` parser treats the description as XML and rejects any `<img>` tag (even self-closing `<img />`), returning HTTP 400 `xml_parsing_error`. Upload images as file attachments instead (see Phase 3.5).

### Spacing

Two section types, two rules — apply them consistently:

| Section | Body type | Separator before next `<strong>` |
|---|---|---|
| Figma/screenshot link | inline `<a>` | `\n\n` |
| Purpose | plain text | `\n\n` |
| Description | plain text | `\n\n` |
| Out of scope | `<ul>` | `\n` |
| Acceptance criteria | `<ul>` | `\n` |
| References | `<ul>` (last — no trailing separator) | — |

**Rule:** `\n\n` after plain text, `\n` after `</ul>`. Body text starts on the line immediately after its `<strong>` title — no blank line between the heading and the content.

Dependencies are **not** written in the description. They are wired natively in Asana via the task dependency graph (**Phase 3 Steps 4 and 5**), where they are already visible as blocking relationships. Repeating them in the description text adds no information.

### Wrapping for Asana API
Always pass descriptions to `asana_create_task` as `html_notes` wrapped in `<body>...</body>`.
