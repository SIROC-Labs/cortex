# Decomposition Principles

These rules govern how work is broken into milestones and tasks. They exist because decomposition decisions have downstream consequences — a bad ordering creates blockers, a bad scope creates tasks that are either too vague to start or too small to be worth tracking.

## Milestone Design

Each milestone delivers a **usable increment of the product** — not a technical layer.

- **Bad:** "M1: All backend, M2: All frontend" — this means nothing works until M2 is done
- **Good:** "M1: Auth (backend + frontend), M2: User management (backend + frontend)" — each milestone delivers something a user can interact with

However, within a milestone, **tasks are platform-specific** (one task = one platform). The milestone groups them by product value; the tasks separate them by execution context.

**Ordering milestones:** Consider both product value and implementation dependency. The milestone that unblocks the most downstream work should come first, unless there's a compelling product reason to prioritize differently.

**Existing projects:** New tasks may belong in existing milestones. Don't create new milestones if the work fits naturally into the current structure. Propose new milestones only when the work represents a genuinely new product increment. Check for existing milestones in Asana sections or previous task-breakdown files.

### Milestone Content Validation

Before milestones are written to the breakdown md, every milestone must pass:

- **Required fields present** — Purpose, Description, Product Requirements (≥1 use case), Acceptance Criteria (≥1 outcome), References (may be empty list, must be declared).
- **Description is product-language** — same rule as task descriptions: a PM or designer reading it should immediately understand what gets shipped. No class names, endpoints, or framework patterns leading the description.
- **References are non-trivial** — strip references that point to the breakdown md itself, to any `CLAUDE.md`, to the target Asana project URL, or to other trivially-discoverable resources. Same stripping rules as the task-level references list.
- **Self-sufficient for expansion** — re-read the Description + Product Requirements + References. If a future session opening this milestone fresh would not have enough context to expand tasks, add what is missing. Common gaps: which platforms are involved, which spec section the milestone implements, which existing entities it depends on.

Surface failures to the user and resolve them before continuing to task expansion.

## Task Ordering Within Milestones

These ordering rules resolve ambiguity about what should come first. They're not arbitrary — each has a practical reason.

1. **Foundational entities before dependent entities.** If Projects reference Users, build Users first. Otherwise you'll be building the Project form with placeholder user data, then reworking it when Users exist.

2. **Read before write.** List and detail views before create/edit/delete forms, per entity. Read views are simpler, validate the data model, and give immediate visual feedback that the backend is working.

3. **Data before visualization.** Seed data or API endpoints before the UI that displays them. You can't build a chart without data to chart.

4. **Backend before frontend** (when both are new for the same feature). The API must exist before the UI can consume it. Building frontend against a not-yet-built API means mocking everything, then reworking when the real API behaves differently.

5. **Design before implementation** (when designs don't exist yet). If a Figma file or design spec is needed for a feature, that task comes before the frontend implementation tasks. You can't build a pixel-perfect UI without knowing what it should look like.

6. **Cross-references after both sides exist.** If Employee detail links to Projects and Project detail links to Employees, add those cross-links as a separate task after both entities are implemented. Building cross-refs early means building against interfaces that don't exist yet.

7. **Aggregation and derived views last.** Summary tables, dashboards, computed metrics come after the raw data and basic views exist. These depend on everything else being in place.

## Task Scoping

Three rules keep tasks at the right granularity:

- **One platform per task.** Never mix Backend + Frontend + Design in a single task. Each platform has different tools, review concerns, and potentially different people doing the work.

- **Completable in a single session.** Typically 0.5–4 hours. If a task feels bigger, it probably has a natural split point — find it. If it feels smaller than 30 minutes, it might be better merged with a related task.

- **Clear purpose boundary.** Each task should have a one-sentence "why" that stands alone. If you can't explain why this task exists without referencing another task's internals, the boundaries are wrong.

**When to split a task:**

Three signals that a task should be broken into two or more smaller ones:

1. **The description requires enumeration.** If you can't write the description without a numbered list — "(1) do X, (2) do Y, (3) do Z" — each item is a candidate for its own task. A well-scoped task reads as prose, not a checklist. The `output-format.md` rule against inline enumerations exists precisely because enumeration is a symptom of over-scoping: if the breakdown itself violates that rule, the task is doing too much.

2. **Two sub-features have different complexity profiles.** If one part of the task follows an existing pattern (routine, low-risk) and another involves genuine design decisions or unclear behaviour (novel, higher-risk), separate them. Bundling them means the simpler part can't ship or be tested until the harder part is resolved — a developer is blocked on their own task. Split so each part can be completed and verified independently.

3. **The parts aren't testable as a unit.** If you can clearly describe "done" and write acceptance criteria for the first half without the second half existing, they should be separate tasks. Independent testability is the practical test: can a reviewer verify this task is complete without needing another task to be in place first?

When a task triggers one or more of these signals, propose the split with a brief rationale before writing the breakdown. Don't split mechanically — confirm the sub-tasks each have a clear purpose and would genuinely be planned and reviewed separately.

## Cleanup Tasks

The final task in a milestone is a **cleanup and review pass** — but only when it earns its place.

**When to include a cleanup task:**
- The milestone has 3+ tasks delivering interconnected functionality
- Multiple tasks touch shared concerns (routing, state management, styling)
- The milestone delivers a user-facing increment where consistency matters

**When to skip it:**
- The milestone has 1–2 simple tasks
- The work is purely infrastructure or config with no shared surface
- The tasks are independent and don't create consistency concerns

**What a cleanup task covers:**
- Review work from the milestone for consistency (naming, patterns, error handling)
- Extract shared components or utilities that emerged across tasks
- Fix rough edges, remove dead code, tighten up what was built quickly
- Ensure the milestone delivers a cohesive increment, not a bag of features
- Light testing of cross-task interactions within the milestone

The cleanup task description should reference specific concerns likely to arise from the preceding tasks, not be a generic "clean things up."

## Dependencies

Dependencies are between **tasks**, never between milestones. Milestones group tasks by product value and effort — they're not dependency nodes. Cross-milestone task dependencies are fine (e.g., T12 in M3 depends on T5 in M2).

**Expressing dependencies:**
- Use T-labels (T1, T2, T3...) purely for cross-referencing within the document
- These are internal labels only — they carry no meaning outside the breakdown file
- Every task's `Depends on:` field is either a list of T-labels or "None"

**Parallelizable work:** Tasks that don't depend on each other can be done concurrently. Call this out explicitly — it helps teams plan and helps solo devs understand where they have flexibility in ordering.

**Blocking risks:** If a task is high-risk or uncertain (e.g., depends on a third-party API with unclear docs, requires a design decision that isn't settled), flag it. High-risk tasks should be prioritized early so surprises surface before they block everything downstream.

### Milestone Dependencies

Milestones form a DAG that is independent of (but consistent with) the task-level DAG. Each milestone declares its `Depends on:` as a list of M-labels (or "None").

- **The milestone DAG is not required to be linear.** A milestone can have multiple parents; the chain may branch.
- **Task-level dependencies inside a milestone may cross milestone boundaries.** A task in M3 may depend on a task in M1. The milestone DAG records the *minimum* required ordering at the milestone level; the task DAG captures the precise execution order.
- **Cycles are invalid.** If M2 depends on M3 and M3 depends on M2, the breakdown is rejected. Validation detects this and asks the user to break the cycle before continuing.

## Design-Driven Decomposition

When a project is design-heavy and designs don't yet exist:

**Option A: Design-first milestone.** Create M1 as a design milestone with Design-platform tasks for each major UI area. Implementation milestones follow. Choose this when the product vision is unclear and design exploration is needed before committing to implementation.

**Option B: Parallel tracks.** Design and backend proceed in parallel. Frontend tasks are deferred or placed in later milestones with explicit dependencies on the corresponding design tasks. Choose this when the backend architecture is clear and design is mainly about UI specifics.

**Option C: Design-as-you-go.** Design tasks are interleaved within milestones, each preceding its corresponding frontend implementation task. Choose this for projects with an established design system where design work is incremental rather than exploratory.

Discuss the tradeoffs with the user and let them choose. The right approach depends on the project's design maturity and team structure.

