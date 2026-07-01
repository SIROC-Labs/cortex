# Task Description Template

Each task description is a **thin, faithful render** of one task entry from the breakdown markdown file, with references aggregated from all three levels of the breakdown so the task is self-contained.

The description does **not** contain an implementation plan. That is produced later during refinement and attached as an `implementation-plan.md` file on the same task.

## Description Structure

Author the description in Markdown; the provider renders it (see Formatting Rules below).

### 0. Visual Context (Figma / Screenshot)

**Only include this section when visual references exist.** It renders before Purpose so a developer opening the task sees the design immediately.

**Figma link:** If a Figma URL exists in the aggregated references (task, milestone, or file header), render it as a standalone link at the very top of the description body, before all other content:

```markdown
[→ View in Figma](https://figma.com/...)
```

Use the label from the breakdown (e.g. "Figma — Mapping step" → `→ Figma — Mapping step`). If the breakdown says "Not yet available" or has no Figma URL, skip this line entirely — do not render a placeholder.

**Screenshots from a prototype:** Do not embed screenshot URLs inline in the description — images are added as file attachments, not inline content. Upload them via `upload_attachment(task, <path>)`; the task manager then displays them as image thumbnails below the description. See Phase 3.5 in the skill for when and how to upload them.

Do **not** try to embed screenshot URLs inline in the description.

### 1. Purpose

One sentence: why this task exists and what it unlocks. Pull verbatim from the breakdown task entry's `Purpose:` field.

> Implements the employee CRUD API so the frontend can list, create, and edit employees.

### 2. Description

2–3 sentences from the breakdown task entry's `Description:` field, rendered verbatim (or rewritten per the rule below).

The description must be written in **product language** — what the user sees or experiences, not how it is coded. A PM, designer, or QA engineer reading this task should immediately understand what's being built and why. Implementation details (which endpoint, which hook, which component pattern) are not needed here and will be added during refinement.

**Keep it brief and high-level.** Do not embed inline enumerations like `(1) Campaign — …; (2) Creative — …; (3) Parameters — …`. If a task has multiple components, name them at a summary level in prose and let the Acceptance criteria carry the specifics.

If the breakdown description is too developer-centric (leads with a class name, an API call, or a framework pattern) or too long, rewrite it in product terms before rendering it into the task. This is the one case where submit-breakdown is allowed to rephrase breakdown content — the goal is a description any team member can understand, not a literal transcription of technical shorthand.

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
  - **The target project URL itself** — every task already lives inside that project; pointing back to it is tautological. (Other task URLs that point to *related but separate* work are fine to keep.)
  - **Anything else trivially auto-discoverable** — the repo URL, the worktree root, generic onboarding pointers a fresh session would already see. If the agent would find it without being told, do not reference it.

  Keep references that are genuinely load-bearing: spec docs, Figma frames, external library/API docs, specific tasks providing context not derivable from the project, design system pages, RFC links, etc. The bar is *"would a reader without this link be missing something they can't otherwise find?"* — if the answer is no, drop the line.

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

inside an `M1` milestone with `References: Sprint plan: https://example.com/...` and a file header `References: Spec: docs/spec.md, Figma: https://figma.com/file/abc`, the task description becomes:

```markdown
[→ Figma](https://figma.com/file/abc)

**Purpose**
Implements the employee CRUD API so the frontend can list, create, and edit employees.

**Description**
Adds CRUD endpoints for employees — create, read, update, and soft-delete — so the frontend can manage employee records against a live backend.

**Out of scope**
- Do NOT implement pagination or filtering — that is a separate task.
- Do NOT add role-based access control — that is a separate task.

**Acceptance criteria**
- GET /employees returns all employees with name, role, department
- POST /employees creates and returns entity with generated ID
- GET /employees/{id} returns 404 with error message for nonexistent IDs
- DELETE soft-deletes (sets is_active=false)

**References**
- API style guide: *docs/api-style.md*
- Sprint plan: https://example.com/...
- Spec: *docs/spec.md*
```

---

## Content Rules

- **Render, don't analyze.** This template renders the breakdown verbatim. Do not infer new content, add file paths the breakdown didn't mention, or speculate about implementation. That is handled later during refinement, when the codebase is read.
- **Aggregate references unconditionally.** Even if a milestone has only one task, embed the milestone's references in that task — every task must be self-contained when read in isolation.
- **Preserve labels verbatim.** Reference labels come from the breakdown's References lines exactly. Do not normalize, rename, or "clean up" labels.
- **Skip empty sections.** If the breakdown has no `Out of scope:` or no task-level `References:`, simply omit those bullets — do not render an empty section.
- **No T-labels in the task description.** T-labels (`T1`, `T2`, …) are breakdown-internal identifiers — they only exist so the breakdown markdown can express dependencies before the task manager assigns its own identifiers. Resolve every T-label reference (prose mentions, examples) to the corresponding task link + title. Never write the literal `T1`, `T2`, … into the task description.

---

## Formatting Rules (Markdown)

Author descriptions in Markdown; the provider renders them. These rules produce clean, compact descriptions.

### Conventions to use
- **Bold** (`**…**`) for section titles (Purpose, Description, Out of scope, Acceptance criteria, References)
- *Italic* (`*…*`) for file paths, function names, types, and technical terms
- Bullet lists (`- …`) for Out of scope, Acceptance criteria, and References
- Standard links (`[text](url)`) for Figma URLs, external docs, dependency task links

### Conventions to avoid
- Do not use heading syntax (`#`, `##`, …) for section titles — bold titles render more compactly. Reserve any heavier structure for the breakdown source, not the rendered description.
- **Never embed images inline.** Upload images as file attachments instead (see Phase 3.5) — inline image embedding in the description is not supported.

### Spacing

Two section types, two rules — apply them consistently:

| Section | Body type | Separator before next title |
|---|---|---|
| Figma/screenshot link | inline link | blank line |
| Purpose | plain text | blank line |
| Description | plain text | blank line |
| Out of scope | bullet list | blank line |
| Acceptance criteria | bullet list | blank line |
| References | bullet list (last) | — |

**Rule:** leave a blank line between each section. Body text starts on the line immediately after its bold title — no blank line between the title and the content.

Dependencies are **not** written in the description. They are wired natively via the task dependency graph (Phase 3 Step 2), where they are already visible as blocking relationships. Repeating them in the description text adds no information.
