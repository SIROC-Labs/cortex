# Decomposition Principles

These rules govern how work is broken into milestones. They exist because decomposition decisions at the milestone level have downstream consequences — a bad ordering creates blockers across entire product increments, and a bad scope creates milestones that either deliver nothing usable or conflate unrelated concerns.

## Milestone Design

Each milestone delivers a **usable increment of the product** — not a technical layer.

- **Bad:** "M1: All backend, M2: All frontend" — this means nothing works until M2 is done
- **Good:** "M1: Auth (backend + frontend), M2: User management (backend + frontend)" — each milestone delivers something a user can interact with

**Ordering milestones:** The milestone that unblocks the most downstream work should come first, unless there's a compelling product reason to prioritize differently.

**Existing projects:** New milestones may belong as refinements to unexpanded milestones rather than always creating new ones. Don't create a new milestone if the work fits naturally into an existing unexpanded one. When new milestones are genuinely needed, always append them to the end of the existing M-label sequence — never insert in the middle of the existing numbering.

## Milestone Dependencies (DAG)

Milestones form a DAG. Each milestone declares its `Depends on:` as a list of M-labels (or "None").

- **The milestone DAG is not required to be linear.** A milestone can have multiple parents; the chain may branch.
- **Task-level dependencies inside a milestone may cross milestone boundaries.** A task in M3 may depend on a task in M1. The milestone DAG records the minimum required ordering at the milestone level; precise execution order is a `task-breakdown` concern, not this skill's.
- **Cycles are invalid.** If M2 depends on M3 and M3 depends on M2, the breakdown is rejected. Validation (`references/validation.md`) detects this and asks the user to break the cycle before continuing.

## Design-Driven Decomposition

When a project is design-heavy and designs don't yet exist:

**Option A: Design-first milestone.** M1 is a design milestone with Design-platform tasks for each major UI area. Implementation milestones follow. Choose this when the product vision is unclear and design exploration is needed before committing to implementation.

**Option B: Parallel tracks.** Design and backend proceed in parallel. Frontend milestones are deferred or placed later with explicit dependencies on design milestones. Choose this when the backend architecture is clear and design is mainly about UI specifics.

**Option C: Design-as-you-go.** Design milestones are interleaved within the sequence, each preceding the implementation milestone it unblocks. Choose this for projects with an established design system where design work is incremental rather than exploratory.

Discuss the tradeoffs with the user and let them choose. The right approach depends on the project's design maturity and team structure.

## Infrastructure Milestones

A milestone is **infrastructure-only** when all its acceptance criteria describe invisible technical work — nothing a non-technical stakeholder can observe, use, or demo. Examples: "API client set up", "database schema migrated", "shared service layer implemented".

Infrastructure-only milestones violate the "usable increment" principle from Milestone Design. They fail the demonstrability test: when the milestone closes, there is nothing to show.

**Rule: absorb or justify.** When a proposed milestone is infrastructure-only, choose one of:

1. **Absorb it** into the first milestone that makes the infrastructure visible — that milestone then owns both the plumbing and the user-observable output, and its acceptance criteria can be demonstrated end-to-end.
2. **Justify it explicitly** — if the infrastructure genuinely unblocks multiple parallel milestone tracks that different teams will work on concurrently, a standalone infrastructure milestone may be worth the tradeoff. Call this out, confirm with the user, and require at least one stakeholder-observable criterion (e.g., "staging environment responds to health check", "admin can log in via the new auth layer") so there is something to verify at close.

Never accept "typecheck passes" or "service layer exports types" as the sole acceptance criterion for a milestone.

## What This Skill Does NOT Decompose

- **No task-level decomposition** — that is `task-breakdown` in a later session.
- **No sub-modes (slot tasks into existing milestones / direct task breakdown / milestone-first)** — the milestone-breakdown skill always produces milestones; the "slot tasks into existing milestones" path lives entirely in `task-breakdown`.
- **No implementation tasks under milestones** — milestone-breakdown writes milestone blocks only; task expansion happens later via `task-breakdown`.
