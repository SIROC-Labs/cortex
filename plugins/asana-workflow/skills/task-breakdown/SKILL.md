---
name: task-breakdown
description: >
  Decomposes product work into a milestone-based roadmap with first-class milestones (Purpose, Description,
  Product Requirements, Acceptance Criteria, dependencies) and optional task entries per milestone. Use this
  skill whenever the user wants to plan, organize, or structure implementation work — "break down this spec",
  "plan this project", "create a task breakdown", "roadmap this", "/task-breakdown", or provides a spec
  document (markdown, PDF, Asana task/project URL, Figma link) and wants to figure out how to organize the
  implementation. Also triggers when the user provides an Asana milestone-task URL (or a project URL plus a
  milestone name) and wants to expand that milestone's tasks. Works for both greenfield projects (new spec
  to full breakdown) and incremental work on existing projects (change requests, new features, bug batches
  slotted into existing milestones).
---

# Task Breakdown

Decompose product work into a milestone-based roadmap of implementation tasks. The output is a markdown file with **first-class milestone blocks** (rich Purpose, Description, Product Requirements, Acceptance Criteria, References, M-label dependencies) and — when appropriate — task entries under each milestone.

This is about **strategic decomposition**, not detailed task specs. Each task gets a Purpose, Description, and Acceptance criteria — but not implementation plans or file lists. A separate `refine-tasks` step later reads the codebase to produce per-task implementation plans.

The breakdown file is a **bridge document**: it must contain all references (spec files, Asana task URLs, Figma links, external docs) that downstream skills need for full context.

## Mode Detection

`task-breakdown` runs in one of two modes, detected from the input:

| Input | Mode |
|---|---|
| Asana task URL where `resource_subtype == "milestone"` | EXPAND |
| Asana project URL + free-text "expand milestone &lt;name&gt;" | EXPAND |
| Existing breakdown md path + an M-label hint | EXPAND |
| Spec file, project URL, non-milestone Asana task, free text | PLAN |

Mode detection runs first. If EXPAND, jump to `references/expand-mode.md`. If PLAN, run the phases below.

## PLAN Mode

### Phase 1: Discover

Gather all relevant context before proposing any structure. Read **`references/discovery-guide.md`** for the full checklist.

Every URL, file path, and reference discovered here must appear in the output's References section (file header, milestone, or task level — see `references/output-format.md`).

### Phase 2: Effort Assessment & Mode Proposal

Based on discovery, propose one of three sub-modes with rationale. User confirms or overrides.

| Sub-mode | When |
|---|---|
| **(a) Slot into existing milestone(s)** | Small effort, fits inside an existing project's milestones. No new milestone tasks. Tasks use thin milestone blocks pointing to existing Asana milestones. |
| **(b) Direct task breakdown** | Small new effort, one new milestone is enough. Author one rich milestone block + its tasks in this session. |
| **(c) Milestone-first** | Multi-milestone effort. Author rich milestone blocks now; expand tasks now or defer to later sessions. |

Read **`references/discovery-guide.md`** → "Effort Assessment Signals" for the heuristics.

### Phase 3: Author Milestone Block(s)

For each new milestone (skipped entirely in sub-mode a):

- Assign M-label sequentially.
- Write the rationale paragraph (md-only, planning context).
- Fill the rich milestone block: Purpose, Description, Product Requirements, Acceptance Criteria (high-level), References, Out of scope (optional), Depends on (M-labels), Source (optional).

Run **milestone content validation** from `references/decomposition-principles.md` → "Milestone Content Validation" before continuing. Resolve all failures.

### Phase 4: Task Expansion Decision

After milestones are written, the user chooses:

- **Expand now** — pick one or more milestones to expand into tasks in this session. Each expansion runs Phase 5.
- **Stop here** — produce a milestones-only breakdown. Go to Phase 6.

In sub-modes (a) and (b), default to expanding immediately. In sub-mode (c), ask explicitly.

### Phase 5: Task-Level Authoring

For each milestone being expanded:

Break it into platform-specific tasks per `references/decomposition-principles.md` (ordering, scoping, dependencies, cleanup tasks). T-labels are sequential across the entire file. Write tasks in product language per `references/output-format.md` → "Description".

Run **task validation** (Phase 3.5 in earlier versions): platform check, size check, split check, redundancy check. Resolve before continuing.

### Phase 6: Write the Breakdown File

Produce the final markdown file following `references/output-format.md`.

**File location:** `<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<descriptive-name>.md`

Resolve `<repo-root>` from `git rev-parse --show-toplevel`. If a file with the same name exists, append `-v2`, `-v3`, etc. The file is a local working artifact — it does not need to be committed.

### Phase 7: Originating Task Disposition

Same as before — only when input was a single Asana task. Ask the user: Delete or Complete? Write the chosen action into the breakdown file's **Originating Task** section. See `references/output-format.md`.

### Phase 8: Transition to Submit

Offer to call `submit-breakdown`:

> "Breakdown saved to `<file-path>`. Want to submit it to Asana now? [Y/n]"

If yes, invoke `asana-workflow:submit-breakdown` via the Skill tool. Pass the breakdown file path and, if the References contain an Asana project URL, include it.

## EXPAND Mode

See **`references/expand-mode.md`** for the full flow (triggers, pre-flight, context loading, decomposition, output file, submit handoff).

## What This Skill Does NOT Do

- Does not produce implementation plans or file-level specs (those are produced later by `refine-tasks`).
- Does not create Asana tasks or interact with project management tools for writing (that is `submit-breakdown`).
- Does not write code or scaffold projects.
- Does not assign people, set priorities (beyond defaulting to P3), or manage external IDs.
- Does not produce estimates — those come during refinement.

It **does** read from Asana (existing tasks, projects, milestones) during discovery.

## Reference Files

- **`references/discovery-guide.md`** — Discovery checklist, questioning strategy, effort-assessment signals
- **`references/decomposition-principles.md`** — Milestone design, milestone validation, task ordering / scoping / dependencies, cleanup tasks, milestone DAG rules
- **`references/output-format.md`** — Markdown template (rich + thin milestone blocks), field reference for milestone and task levels
- **`references/expand-mode.md`** — Full EXPAND mode flow
