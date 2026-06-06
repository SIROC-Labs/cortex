# Output Format

This file defines the canonical layout of the milestone-breakdown folder bundle: `breakdown.md` (one rich block per milestone, body fields pushed verbatim to Asana) and one `M{N}-milestone-spec.md` per milestone (uploaded as an Asana attachment). It includes the `breakdown.md` file template, the parsing contract that `submit-breakdown` reads against, the per-milestone spec template, and the rules on which references are allowed.

## File Location

Folder path: `<repo-root>/docs/cortex/milestone-breakdown/<YYYY-MM-DD>-<slug>/`

Resolve repo root via `git rev-parse --show-toplevel`. If the folder already exists, append `-v2`, `-v3`, ... until the name is free.

Slug heuristic: short, descriptive, all lowercase, hyphen-separated, derived from the work title — same convention as today's task-breakdowns. Examples: `auth-redesign`, `mobile-onboarding`, `billing-revamp`.

Create the folder if it doesn't exist. The folder is a local working artifact — it does not need to be committed; persistence into Asana is handled by `submit-breakdown`.

## breakdown.md template

```markdown
# <Title> — Milestone Breakdown

**Delivers:** <one sentence>

<file-level rationale paragraph — md-only, ignored by submit-breakdown>

## References

<file-level references — codebase paths, public URLs, Figma URLs only. Md-only header, ignored by submit-breakdown.>

## M1 :: <Milestone Name>

<rationale paragraph — md-only, ignored by submit-breakdown>

**Purpose:** <one sentence>
**Description:** <2–4 sentences, product language>
**Out of scope:** <optional>
**References:** <optional — milestone-specific, allowed-list only>
**Depends on:** <M-labels or "None">
**Source:** <optional — existing Asana milestone URL when refining>
**Attachments:**
- M1-milestone-spec.md

## M2 :: <Milestone Name>
...

## Originating Task

<optional — only when triggered from a single Asana task>
- **Task:** [name](url)
- **Action:** Delete | Complete
```

Each `## M{N} :: <Name>` block represents one Asana milestone task. M-labels in this file are sequential from M1 and local-only (see "## M-label Conventions" below).

## Parsing Contract

| Field | Role | Pushed to Asana description? |
|---|---|---|
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Out of scope:**` (optional) | Body | Yes |
| `**References:**` (optional) | Body | Yes |
| `**Depends on:**` | Dependency metadata | No — parsed for M-labels, used to wire native Asana task dependencies |
| `**Source:**` (optional) | Refine-path metadata | No — parsed to detect "update existing milestone task" instead of "create new" |
| `**Attachments:**` | Attachment metadata | No — file list uploaded as Asana attachments |

Parsing rules:

- For each `## M{N} :: <Name>` header → one milestone task.
- Skip any free-text prose paragraph immediately after the header (rationale, md-only).
- Collect body fields → render them as the Asana task description, verbatim, in the canonical order: **Purpose → Description → Out of scope → References**.
- Collect metadata fields → route per the table above.
- Content under top-level headers `## References` and `## Originating Task` is handled separately and not associated with any milestone block.

Authoring convention is body fields first, then metadata fields, with `**Attachments:**` last. `submit-breakdown` picks fields by name, so order in the file is not load-bearing — but the convention keeps the file human-readable.

## M{N}-milestone-spec.md template

```markdown
# <Milestone Name>

**Status:** Draft
**Date:** YYYY-MM-DD
**Milestone:** M{N}    ← local label only, for ordering

## Product Requirements
- <use case / scenario 1>
- <use case / scenario 2>

## Acceptance Criteria
- <observable, high-level outcome 1>
- <outcome 2>

## Technical Spec

### Summary
<2–5 sentences scoped to this milestone>

### Technical Context
<inlined current-state context relevant to this milestone — restate product rules inline,
 never reference the input PRD by path>

### Architecture Notes
<technical shape for this milestone's scope only>

### Data Model Notes
<when relevant — omit entirely otherwise, no "N/A">

### Testing Strategy
<scoped to this milestone>

### References & Links
<codebase paths, public URLs, Figma URLs only>

### (Optional) Contract Notes / Behavioral State Machines / Error Model / Non-Goals / Open Questions
```

The Technical Spec section nests the create-spec 7-section structure as `###`-level subsections. Product Requirements and Acceptance Criteria sit above because they are milestone-level outcomes — the technical spec describes how to deliver them.

## Allowed References

**Allowed** (in any `**References:**` or `### References & Links` block):
- Codebase paths (files and folders)
- Public documentation URLs (RFCs, vendor docs, library docs)
- Figma URLs (system-of-record for designs)

**Explicitly disallowed:**
- The input PRD / spec file path
- The originating Asana task / ticket URL (cross-context Asana tasks are fine only when strictly necessary)
- Any uncommitted markdown file
- Other planning documents (prior task-breakdowns, prior milestone-breakdowns)

Asana cross-task references are represented natively as Asana task dependencies — no need to restate them in markdown prose unless strictly necessary.

## M-label Conventions

M-labels in `breakdown.md` are sequential from M1 and local-only — they are this file's namespace, not global identifiers.

They are **not** the Asana M-labels. `submit-breakdown` does discovery and remapping at push time: it reads the markdown M-labels, resolves the corresponding Asana milestone tasks (by name or `**Source:**` URL), and wires native Asana task dependencies. Markdown M-labels are renumbered at Asana push if existing Asana milestones use overlapping labels.

Locally, `**Depends on:**` uses markdown M-labels — for example: `**Depends on:** M1, M2`.

## Originating Task

The `## Originating Task` section in `breakdown.md` is optional. It is present only when the breakdown was triggered from a single Asana task. It contains a `**Task:**` link and an `**Action:**` field — one of: Delete | Complete. `submit-breakdown` handles the originating task during its cleanup phase, always with user confirmation before acting. See the task-breakdown documentation for the full disposition semantics.
