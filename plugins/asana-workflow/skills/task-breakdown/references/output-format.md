# Output Format

The breakdown file follows a consistent shape at every level — breakdown, milestone, and task all have: what they deliver, why, and where they came from.

## File Location

Save to: `docs/task-breakdowns/<descriptive-name>-<YYYY-MM-DD>.md`

The descriptive name is a short slug derived from what the breakdown covers:
- `management-features-2026-05-20.md`
- `auth-redesign-2026-05-20.md`
- `mobile-onboarding-2026-05-20.md`

Create the `docs/task-breakdowns/` directory if it doesn't exist.

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

## M1 :: [Milestone Name]

**Delivers:** [One sentence — what product increment becomes usable after this milestone]
**Source:** [Optional — existing Asana section URL, spec section, etc.]

[One paragraph: rationale for why these tasks are grouped together and why this milestone is ordered here in the roadmap]

### T1 — [Platform] — [Category] — [Task Name]
**Purpose:** [One sentence — why this task exists and what it achieves]
**Description:** [2-5 sentences — what needs to be built, key decisions, enough to remove ambiguity]
**Acceptance criteria:**
- [Observable outcome 1]
- [Observable outcome 2]
- ...
**Out of scope:** [Optional — only when there's real risk of scope creep or ambiguity]
**Depends on:** [T-labels or "None"]
**Source:** [Optional — Asana task URL, spec reference, or other originating document]

### T2 — [Platform] — [Category] — [Task Name]
...

## M2 :: [Milestone Name]
...

## Dependency Overview

[Optional section: a text-based summary of the critical path and parallelizable work, if the breakdown is complex enough to warrant it]
```

## Field Reference

### T-labels

T1, T2, T3... are internal to this document only. They exist solely for expressing dependencies within the breakdown. They carry no meaning outside this file and will not be used by downstream tools as identifiers.

T-labels are assigned sequentially across the entire document, not per-milestone. So if M1 has T1–T5, M2 starts at T6.

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

### Depends On

List of T-labels that must be completed before this task can start, or "None."

Dependencies are always between tasks, never between milestones. Cross-milestone dependencies are fine — T12 in M3 can depend on T5 in M2.

### Acceptance Criteria

Observable outcomes that verify the task is complete. These should be checkable by looking at the running system or the code — not by reading the implementer's mind.

Good: "Employee list page displays all employees with name, role, and department columns"
Bad: "Employee list works correctly"

Good: "API returns 404 with error message when employee ID doesn't exist"
Bad: "Error handling is implemented"

## Dependency Overview Section

Include this section when the breakdown has 10+ tasks or non-trivial cross-milestone dependencies. It should summarize:

- The critical path (longest chain of sequential dependencies)
- Major parallelization opportunities
- Blocking risks that should be prioritized

Skip it for simple breakdowns where the dependency structure is obvious from the task list.
