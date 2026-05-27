# Task Description Template

Each Asana task description is a **thin, faithful render** of one task entry from the breakdown markdown file, with references aggregated from all three levels of the breakdown so the task is self-contained.

The description does **not** contain an implementation plan. That is produced later by `refine-tasks` and attached as an `implementation-plan.md` file on the same Asana task.

## Description Structure

Use Asana HTML formatting (see Formatting Rules below).

### 1. Purpose

One sentence: why this task exists and what it unlocks. Pull verbatim from the breakdown task entry's `Purpose:` field.

> Implements the employee CRUD API so the frontend can list, create, and edit employees.

### 2. Description

The 2–5 sentence summary from the breakdown task entry's `Description:` field. State what needs to be built; do not list files or implementation steps — that is `refine-tasks`' job.

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

- **Render, don't analyze.** This template renders the breakdown verbatim. Do not infer new content, add file paths the breakdown didn't mention, or speculate about implementation. That is `refine-tasks`' job.
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

### Spacing
- One `\n` between `</ul>` and the next `<strong>`
- Body text starts immediately after the `<strong>` title line
- No extra blank lines anywhere — keep it compact

### Wrapping for Asana API
Always pass descriptions to `asana_create_task` as `html_notes` wrapped in `<body>...</body>`.
