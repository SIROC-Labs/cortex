# Task Description Template

Each Asana task description is a **thin, faithful render** of one task entry from the breakdown markdown file, with references aggregated from all three levels of the breakdown so the task is self-contained.

The description does **not** contain an implementation plan. That is produced later during refinement and attached as an `implementation-plan.md` file on the same Asana task.

## Description Structure

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

The 2–5 sentence summary from the breakdown task entry's `Description:` field. State what needs to be built; do not list files or implementation steps — that is handled later during refinement, when the codebase is read.

### 3. Scope

Pulled from the breakdown task entry's `Description:` and `Out of scope:` fields combined. Two bullet groups:

- **In scope:** what this task delivers
- **Out of scope:** explicit "Do NOT" restrictions from the breakdown's `Out of scope:` field, each suffixed with "— that is a separate task" when it refers to other work in the breakdown

If the breakdown has no `Out of scope:` field, omit the Out of scope bullets entirely.

### 4. Dependencies

Resolved Asana task links — not raw T-labels. Built from the breakdown task entry's `Depends on:` field by looking up each T-label in the T-label → Asana GID map (populated during submit Phase 3 Step 1).

If `Depends on:` is `None`, render this section as `None` (so the reader doesn't wonder whether dependencies were forgotten).

### 5. Acceptance Criteria

The bullet list from the breakdown task entry's `Acceptance criteria:` field, verbatim.

### 6. References (aggregated)

A single bullet list aggregating references from three levels of the breakdown:

1. The task entry's own `References:` field (if present)
2. The milestone block's References (if present)
3. The breakdown file header's References (always present)

Each bullet preserves the descriptive label from the breakdown (e.g., `Spec: docs/spec.md`, `Figma: https://figma.com/…`, `Backend models: src/core/users/`).

**Aggregation rules:**

- Deduplicate by exact URL or file path — a reference repeated at multiple levels appears once.
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
**Estimate:** 02:00
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
Add GET/POST/PUT/DELETE endpoints under /employees. Soft-delete on DELETE. Return 404 with error message for unknown IDs.
<strong>Scope — In scope</strong>
<ul><li>GET/POST/PUT/DELETE endpoints under /employees</li><li>Soft-delete on DELETE</li><li>404 with error message for unknown IDs</li></ul>
<strong>Scope — Out of scope</strong>
<ul><li>Do NOT implement pagination or filtering — that is a separate task.</li><li>Do NOT add role-based access control — that is a separate task.</li></ul>
<strong>Dependencies</strong>
<ul><li><a href="https://app.asana.com/0/1199384720000001/1199384720000123">Setup employee entity + repository</a></li><li><a href="https://app.asana.com/0/1199384720000001/1199384720000124">Employee migration</a></li></ul>
<strong>Acceptance criteria</strong>
<ul><li>GET /employees returns all employees with name, role, department</li><li>POST /employees creates and returns entity with generated ID</li><li>GET /employees/{id} returns 404 with error message for nonexistent IDs</li><li>DELETE soft-deletes (sets is_active=false)</li></ul>
<strong>References</strong>
<ul><li>API style guide: <em>docs/api-style.md</em></li><li>Sprint plan: <a href="https://asana.com/...">https://asana.com/...</a></li><li>Spec: <em>docs/spec.md</em></li><li>Figma: <a href="https://figma.com/file/abc">https://figma.com/file/abc</a></li></ul>
```

---

## Content Rules

- **Render, don't analyze.** This template renders the breakdown verbatim. Do not infer new content, add file paths the breakdown didn't mention, or speculate about implementation. That is handled later during refinement, when the codebase is read.
- **Aggregate references unconditionally.** Even if a milestone has only one task, embed the milestone's references in that task — every task must be self-contained when read in isolation.
- **Preserve labels verbatim.** Reference labels come from the breakdown's References lines exactly. Do not normalize, rename, or "clean up" labels.
- **Skip empty sections.** If the breakdown has no `Out of scope:` or no task-level `References:`, simply omit those bullets — do not render an empty section.
- **No T-labels in the Asana description.** T-labels (`T1`, `T2`, …) are breakdown-internal identifiers — they only exist so the breakdown markdown can express dependencies before Asana GIDs exist. Resolve every T-label reference (Dependencies, prose mentions, examples) to the corresponding Asana task link + title. Never write the literal `T1`, `T2`, … into the Asana task description.

---

## Formatting Rules (Asana HTML)

Asana renders a subset of HTML. These rules produce clean, compact descriptions.

### Tags to use
- `<strong>` for section titles (Purpose, Description, Scope — In scope, etc.)
- `<em>` for file paths, function names, types, and technical terms
- `<ul><li>` for bullet lists
- `<a href="...">` for links (Figma URLs, external docs, dependency Asana links)

### Tags to avoid
- Never use `<h1>`, `<h2>`, or any heading tags — they add excessive whitespace in Asana
- Never use `<code>` or `<pre>` — Asana renders them poorly
- Never use `<br>` between sections — use `\n` only
- **Never use `<img>`** — Asana's `html_notes` parser treats the description as XML and rejects any `<img>` tag (even self-closing `<img />`), returning HTTP 400 `xml_parsing_error`. Upload images as file attachments instead (see Phase 3.5).

### Spacing
- One `\n` between `</ul>` and the next `<strong>`
- Body text starts immediately after the `<strong>` title line
- No extra blank lines anywhere — keep it compact

### Wrapping for Asana API
Always pass descriptions to `asana_create_task` as `html_notes` wrapped in `<body>...</body>`.
