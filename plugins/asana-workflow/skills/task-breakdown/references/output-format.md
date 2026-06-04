# Output Format

The breakdown file follows a consistent shape at every level — breakdown, milestone, and task all have: what they deliver, why, and where they came from.

## File Location

Save to: `<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<descriptive-name>.md`

Paths are resolved from the git repository root (`git rev-parse --show-toplevel`), not the current working directory. The descriptive name is a short slug derived from what the breakdown covers — all lowercase, hyphen-separated, with the date first so listings sort chronologically:
- `2026-05-20-management-features.md`
- `2026-05-20-auth-redesign.md`
- `2026-05-20-mobile-onboarding.md`

If a file with the same name already exists, append `-v2`, `-v3`, etc. until the name is free.

Create the `docs/cortex/task-breakdowns/` directory if it doesn't exist. The file is written locally as a working artifact — it does **not** need to be committed; persistence into Asana is handled by `submit-breakdown`.

## Template

```markdown
# [Descriptive Title] — Task Breakdown

**Delivers:** [One sentence — what the overall body of work achieves when all milestones are complete]

[One paragraph: rationale for how this work was decomposed — the key decisions about ordering, grouping, and boundaries]

## References

All source materials that inform this breakdown:

- **Spec:** `docs/spec.md` (or link)
- **Figma:** [URL if applicable]
- **Asana:** [URL if applicable]
- **Other:** [Any other input URLs, documents, or files provided or discovered]

**Only list non-obvious references.** A reference belongs here only when the downstream agent could not reasonably find the material on its own. Skip everything else — it is pure context noise at refinement time. In particular, **never reference**:

- **Other task-breakdown files** (here or in milestone- / task-level References). Meta-documents that bundle every milestone — pointing to one forces refinement to read an entire unrelated breakdown.
- **CLAUDE.md files at any level** — root `CLAUDE.md`, `backend/CLAUDE.md`, `frontend/CLAUDE.md`, etc. Claude auto-loads these from the working directory; listing them as references adds zero information.
- **The target Asana project URL itself** — every task already lives in that project; pointing back to it is tautological. (Other Asana tasks providing context for *separate* related work are fine.)
- **Anything else trivially auto-discoverable** — repo URL, worktree root, generic onboarding pages a fresh session would see. If the agent would find it without being told, leave it out.

Keep references that are genuinely load-bearing: spec documents, Figma frames, external library/API docs, specific Asana tasks giving context not derivable from the project, RFCs, design-system pages, etc. The bar is *"would a reader without this link be missing something they can't otherwise find?"* — if not, drop it. If a prior breakdown informed this one, link to the underlying source materials it referenced (spec, Figma, external docs), never to the breakdown itself.

## M1 :: [Milestone Name]

[One paragraph: rationale for why this milestone exists at this position, ordering and grouping decisions. **Planning context, md-only — NOT pushed to Asana.**]

**Purpose:** [One sentence — why this milestone exists, what it unlocks]

**Description:** [2–4 sentences in product language — what gets built or shipped when this milestone is complete. Rich enough that a future session could expand it into tasks from this + References alone.]

**Product Requirements:**
- [Use case / scenario this milestone covers — e.g., "Admin can create a new employee with name, role, department"]
- [Use case 2]
- ...

**Acceptance Criteria (milestone-level):**
- [Observable, high-level outcome — e.g., "Employee list page is reachable and shows live data from the backend"]
- [Outcome 2]
- ...

**Out of scope:** [Optional — only when there is real scope-creep risk]
- [Explicit exclusion 1]

**References:** [Optional — milestone-specific URLs, repo file paths, specs, Figma frames, external docs. Never the breakdown md file itself.]

**Depends on:** [List of M-labels or "None"]

**Source:** [Optional — existing Asana section URL, spec section, or Asana task URL]

### T1 — [Platform] — [Category] — [Task Name]
**Purpose:** [One sentence — why this task exists and what it achieves, from the user's perspective]
**Description:** [2-3 sentences — what the user sees or experiences when this task is done. Write in product language anyone on the team can understand — PM, designer, developer. Lead with user-facing behaviour, not implementation approach. No inline enumerations like (1)…(2)…(3)… — summarise at a high level; let Acceptance criteria carry the specifics. API endpoints, class names, and technical patterns belong in refinement; not here.]
**Acceptance criteria:**
- [Observable outcome 1]
- [Observable outcome 2]
- ...
**Out of scope:** [Optional — only when there's real risk of scope creep or ambiguity]
**Depends on:** [T-labels or "None"]
**References:** [Optional — task-specific URLs, file paths, docs that go beyond what's in the milestone / file header References]
**Source:** [Optional — Asana task URL, spec reference, or other originating document]

### T2 — [Platform] — [Category] — [Task Name]
...

## M2 :: [Milestone Name]
...

## Originating Task

[Optional — only when the breakdown was triggered from a single Asana task]

- **Task:** [Task name](Asana task URL)
- **Action:** Delete | Complete
```

## Thin Milestone Block (Slot-Into-Existing Mode)

When the breakdown is adding tasks to an **existing** Asana milestone (PLAN sub-mode "slot into existing milestones"), the milestone block is **thin** — it omits the rich fields because the milestone already exists in Asana and is not being authored or updated.

```markdown
## M1 :: Employee Management
**Source:** https://app.asana.com/.../task/<existing-milestone-task-gid>

### T1 — Backend — Feature Request — ...
...
```

A milestone block is recognized as **thin** by the absence of a `Purpose:` line. `submit-breakdown` looks up the existing milestone task via the `Source:` URL (or by section name as fallback), skips creation, and proceeds to create the implementation tasks under it.

Use thin blocks only when slotting into an existing milestone. New milestones — even when there is only one — use the full rich block.

## Field Reference

### T-labels

T1, T2, T3... are internal to this document only. They exist solely for expressing dependencies within the breakdown. They carry no meaning outside this file and will not be used by downstream tools as identifiers.

T-labels are assigned sequentially across the entire document, not per-milestone. So if M1 has T1–T5, M2 starts at T6.

### M-labels

M1, M2, M3... are internal to this document only. They exist solely for expressing milestone-to-milestone dependencies within the breakdown. They carry no meaning outside this file.

M-labels are assigned sequentially across the milestone list. They are an independent namespace from T-labels — M1 and T1 are not related.

### Milestone Purpose

One sentence: why this milestone exists in the roadmap and what it unlocks. Pull through to the Asana milestone task description verbatim.

### Milestone Description

2–4 sentences in product language describing what gets built or shipped when the milestone is complete. The bar is: a future session reading only this Description plus the milestone References should be able to expand the milestone into tasks. Lead with user-facing behavior, not implementation approach.

### Product Requirements

Bulleted list of use cases / scenarios this milestone covers, drawn from the spec or PRD. This is what makes the milestone description self-sufficient for later expansion — each bullet names a concrete user-facing behavior that any task derivation must collectively cover.

### Acceptance Criteria (milestone-level)

Observable, high-level outcomes a reviewer can check to say "this milestone is done." Distinct from per-task acceptance criteria — milestone-level ACs are about the milestone's product increment, not individual task outcomes.

### Milestone Depends On

List of M-labels that must complete before this milestone can start, or "None." Milestone dependencies form a DAG — they are not required to be linear. Cross-milestone task dependencies (T → T) are independent of milestone dependencies (M → M); both are tracked.

Validation rejects M-label cycles. If a cycle is detected, the breakdown is invalid and must be revised.

### Platform

Exactly one per task:
- **Backend** — server-side logic, APIs, database, infrastructure
- **Frontend** — web application UI
- **iOS** — native or cross-platform iOS app
- **Android** — native or cross-platform Android app
- **Design** — Figma files, wireframes, design specs, design system work

### Category

Exactly one per task:
- **Feature Request** — new functionality that didn't exist before
- **Technical Request** — improves technical context: refactoring, infrastructure, tooling, performance
- **Bug** — fix for broken behavior

### Source

Traces a task or milestone back to its origin. This field serves two purposes:

1. **Context for the downstream skill** — when the breakdown references an Asana task or spec section, the downstream skill can read that source for full detail.
2. **Update vs. create signal** — when the breakdown modifies or replaces an existing task (e.g., splitting one large Asana task into smaller ones), the Source field links back to the original so the downstream skill knows to update/replace rather than create from scratch.

Include Source when:
- The task originated from a specific Asana task URL
- The task maps to a specific section of a spec document
- The task replaces or refines an existing task

Omit Source when the task is net-new work derived from the overall spec.

### Out of Scope

Optional. Only include when there's real risk of scope creep or ambiguity — when someone reading the task might reasonably assume it includes something it doesn't.

Don't use this field to restate boundaries that are already clear from the task name and description.

The same rule applies at the milestone level — only include `**Out of scope:**` on a milestone when there is real scope-creep risk or when boundaries between milestones might be misunderstood.

### Depends On

List of T-labels that must be completed before this task can start, or "None."

Dependencies are always between tasks, never between milestones. Cross-milestone dependencies are fine — T12 in M3 can depend on T5 in M2.

### References (per task)

Optional. Task-specific URLs, file paths, or documents that go beyond what's already listed in the file's top-level References section or the milestone's References. Examples:

- A spec subsection that only this task implements
- A Figma frame URL specific to this task's component
- An external doc the implementer must read for this task only

When `submit-breakdown` builds the Asana task description, it aggregates references from three levels: this task's References, the milestone's References, and the file header's References (deduplicated by URL/path). Repetition across tasks is acceptable — each task is meant to be a complete, self-contained refinement input.

### Description

2–3 sentences that explain the task to anyone on the team — PM, designer, developer, QA. The test: could a product manager read this and immediately understand what's being built and why it matters to the user?

**Keep it brief and high-level.** Do not embed inline enumerations like `(1) Campaign — …; (2) Creative — …`. If a task has multiple components, name them in summary prose and let the Acceptance criteria carry the specifics. A description that lists every domain model, port method, or technical pattern is too long — that detail belongs in refinement.

**Write in product language, not developer language.**

| Instead of… | Write… |
|---|---|
| "Build a data-fetching layer over GET /v2/parameters" | "When the wizard loads, the app fetches the list of available macro intents and ad servers so the dropdowns in later steps always reflect current options." |
| "Implement POST /campaigns with idempotency key" | "Clicking 'Publish' submits the campaign to the DCO system; the app prevents double-submission if the user clicks twice." |
| "Add useCallback memoization to prevent re-renders" | "The mapping table stays responsive even with 300+ rows — this task optimises it so it doesn't lag as the user types." |

The description explains **what the user sees or does** and **why it matters**. Technical approach (which endpoint, which hook, which pattern) is not needed here — that's what refinement is for, once the codebase is read.

One practical check: if your description only makes sense to a developer who already knows the codebase, rewrite it.

### Acceptance Criteria

Observable outcomes that verify the task is complete. These should be checkable by looking at the running system or the code — not by reading the implementer's mind.

Good: "Employee list page displays all employees with name, role, and department columns"
Bad: "Employee list works correctly"

Good: "API returns 404 with error message when employee ID doesn't exist"
Bad: "Error handling is implemented"

### Originating Task

Optional. Present only when the breakdown was triggered from a single Asana task that is now superseded by the breakdown's tasks.

- **Task** — the name and Asana URL of the originating task
- **Action** — what `submit-breakdown` should do with it after creating all new tasks:
  - **Delete** — remove the task from Asana
  - **Complete** — mark the task as complete and post a comment listing all newly created tasks with their Asana URLs

The user chooses the action during Phase 6 of task-breakdown. `submit-breakdown` executes it during its cleanup phase, always with a confirmation prompt before acting.

## Dependency Overview Section

Include this section when the breakdown has 10+ tasks or non-trivial cross-milestone dependencies. It should summarize:

- The critical path (longest chain of sequential dependencies)
- Major parallelization opportunities
- Blocking risks that should be prioritized

Skip it for simple breakdowns where the dependency structure is obvious from the task list.
