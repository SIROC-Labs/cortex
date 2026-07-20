# Spec Output Format

Detailed formatting conventions for the spec markdown file. SKILL.md covers the high-level structure; this file covers the rules and templates for each section.

---

## Heading levels

- `#` — document title only.
- `##` — top-level sections (Summary, Technical Context, etc.).
- `###` — sub-sections inside a top-level section.
- `####` — rare; only when a sub-section legitimately needs structure.

Do not skip levels (`##` → `####`). If a section feels nested enough to skip a level, it probably belongs as a sibling.

---

## 1. Title & metadata

The first lines of the file.

```markdown
# <Title>

**Author:** <name or handle>
**Date:** <YYYY-MM-DD>
**Status:** Draft | In Review | Approved | Superseded
**Version:** v1 (or v2, v3… on revisions)
```

Status starts at `Draft` for a new spec. Promote to `In Review` only when the user explicitly says so.

The title is the human-readable name of the work — match it to the filename's `<title>` slug (e.g., file `2026-06-05-search-rerank.md` → title "Search Rerank"). Do not date the title; the file is already dated.

---

## 2. Summary

Two to five sentences. What is the work, why it matters, and the one-line technical shape.

A reader who only reads the summary should know:
- What problem this work solves
- Which subsystem(s) it touches
- The headline technical move (e.g., "introduces a new event-sourced projection," or "extends the existing rate limiter with a per-user dimension")

Do not enumerate features here. Do not describe the build order. Keep it tight.

---

## 3. Technical Context

The state of the world this spec is responding to. Short, factual, no decisions yet.

Typical content:

- The current architecture in the affected area (1–2 paragraphs, or a tight bullet list).
- The constraint, requirement, or product rule motivating the work — restated inline, not linked out.
- Existing patterns or modules the work will build on.
- What is already shipped vs. what is new.

This section is where you ground the reader before introducing your proposed changes. If a planner skips this section, they should still be able to act on the rest of the spec — but they will lose the "why."

---

## 4. Architecture Notes

The technical shape of the proposed change. The heart of the spec.

What belongs here:

- The components, modules, or services that change, and how they fit together.
- New boundaries (a new module, a new service, a new event type) and what they own.
- The flow of data or control through the system at a sketch level — diagrams welcome where they earn their space.
- Trade-offs that are decided and the reason. Trade-offs that are still open go to Open Questions.

What does **not** belong here:

- Step-by-step build order ("first do A, then do B"). That is for a plan, not a spec.
- File-level or function-level instructions.
- Ticket-level decomposition.

Diagrams: ASCII art and mermaid both work; prefer whichever the existing specs in the repo use. Keep diagrams small enough to read inline.

---

## 5. Data Model Notes

Include only when the work touches data. Otherwise omit the section entirely (do not write "N/A").

What belongs here:

- New entities, columns, indexes, or schemas.
- Lifecycle rules (when records are created, mutated, deleted, archived).
- Ownership — which service or module is the source of truth.
- Migration considerations at a shape level (forward-compatible? backfill needed? online-safe?). Detailed migration steps belong to the plan, not the spec.

Tables work well for field-level changes:

```markdown
| Entity | Field | Type | Notes |
|---|---|---|---|
| `Order` | `risk_score` | float, nullable | written by scorer; null until first scoring run |
```

---

## 6. Testing Strategy

How the work will be verified. Not test cases — *strategy*.

Cover the kinds of tests this work needs and the boundaries they sit at:

- Unit — for what behaviors, at what layer.
- Integration — across which boundaries (DB, queue, HTTP).
- Contract — if a contract changes, how is the contract verified.
- End-to-end — only if the work demands a user-facing flow that cannot be verified at a lower level.

Also note:

- Fixture or test infrastructure that needs to exist (new factories, new seed data, new mock services).
- Coverage targets only if the repo has an explicit convention. Do not invent targets.

Avoid: enumerated test cases. Those belong in the plan or in the test file itself.

---

## 7. References & Links

Every external resource the spec depends on, with a clickable link.

```markdown
- [Figma — Search Rerank flows](https://figma.com/...)
- [Internal RFC #142 — Indexing pipeline](https://...)
- [GitHub issue siroc/cortex#1234](https://github.com/...)
- Loom walkthrough — *Not yet available*
```

Rules:

- If a reference exists but has no URL yet (design not started, RFC not written), list it explicitly as "Not yet available" — never silently omit it.
- Do not list the PRD here as the source of truth. The spec is self-contained.
- Do not list `CLAUDE.md` / `AGENTS.md` / convention files here unless the spec genuinely depends on a specific section of one.

---

## Optional sections

Add only when the work demands them. Examples:

### Contract Notes

When one or more API / event / message contracts change. Show the change in shape, the versioning approach, and the consumer impact. Tables for fields, prose for behavior.

### Behavioral State Machines

When the work introduces or changes a meaningful state machine. Diagram + a short transitions table.

### Error Model

When the work introduces new error kinds or changes how errors surface. List the error categories, what triggers each, and how they surface to the caller / user.

### Non-Goals

When the work has tempting adjacent scope that is explicitly out. State each non-goal and one sentence of why.

### Open Questions

When the interview produced questions the user explicitly chose not to answer yet.

```markdown
| Question | Owner | Status |
|---|---|---|
| Should retries be at-least-once or at-most-once? | <owner> | Open — pending data review |
```

---

## Style

- Sentence case for headings.
- Prose by default; reach for tables, lists, or diagrams when they are clearly the better representation.
- Code fences for code, config, payloads, schema. Specify the language: ` ```json `, ` ```python `, ` ```sql `.
- One blank line between sections; no trailing whitespace.
- Avoid filler ("Note that…", "It is important to mention…"). Say the thing.
- Do not write in first-person plural ("we will…") as if narrating a plan. The spec describes shape, not action.

---

## What goes where — quick reference

| Information | Section |
|---|---|
| The product rule motivating a choice | Technical Context (inline) |
| The new component and what it owns | Architecture Notes |
| A new column or schema change | Data Model Notes |
| The wire shape of a changing API | Contract Notes (optional) |
| The kinds of tests this work needs | Testing Strategy |
| A confirmed unresolved question | Open Questions (optional) |
| The Figma file URL | References & Links |
| The PRD file path | nowhere — restate inline instead |
| The order in which to build the work | nowhere — that is for the plan |
