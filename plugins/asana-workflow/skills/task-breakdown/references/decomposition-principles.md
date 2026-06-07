# Decomposition Principles

These rules govern how a single coherent scope is broken into implementation tasks. Bad ordering creates blockers; bad scope creates tasks that are either too vague to start or too small to be worth tracking.

This skill never authors milestone content. Milestone design, milestone-level acceptance criteria, the milestone DAG, and milestone validation live exclusively in `milestone-breakdown`. If the scope is genuinely multi-milestone, the seam check in `references/discovery-guide.md` routes the user there.

## Task Ordering

These ordering rules resolve ambiguity about what should come first. They're not arbitrary — each has a practical reason.

1. **Foundational entities before dependent entities.** If Projects reference Users, build Users first. Otherwise you'll be building the Project form with placeholder user data, then reworking it when Users exist.

2. **Read before write.** List and detail views before create / edit / delete forms, per entity. Read views are simpler, validate the data model, and give immediate visual feedback that the backend is working.

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

### When to Split a Task

Three signals that a task should be broken into two or more smaller ones:

1. **The description requires enumeration.** If you can't write the description without a numbered list — "(1) do X, (2) do Y, (3) do Z" — each item is a candidate for its own task. A well-scoped task reads as prose, not a checklist. The `output-format.md` rule against inline enumerations exists precisely because enumeration is a symptom of over-scoping.

2. **Two sub-features have different complexity profiles.** If one part of the task follows an existing pattern (routine, low-risk) and another involves genuine design decisions or unclear behaviour (novel, higher-risk), separate them. Bundling them means the simpler part can't ship or be tested until the harder part is resolved — a developer is blocked on their own task. Split so each part can be completed and verified independently.

3. **The parts aren't testable as a unit.** If you can clearly describe "done" and write acceptance criteria for the first half without the second half existing, they should be separate tasks. Independent testability is the practical test: can a reviewer verify this task is complete without needing another task to be in place first?

When a task triggers one or more of these signals, propose the split with a brief rationale before writing the breakdown. Don't split mechanically — confirm the sub-tasks each have a clear purpose and would genuinely be planned and reviewed separately.

## Cleanup Tasks

The final task in a bundle is often a **cleanup and review pass** — but only when it earns its place.

**When to include a cleanup task:**
- The bundle has 3+ tasks delivering interconnected functionality
- Multiple tasks touch shared concerns (routing, state management, styling)
- The bundle delivers a user-facing increment where consistency matters

**When to skip it:**
- The bundle has 1–2 simple tasks
- The work is purely infrastructure or config with no shared surface
- The tasks are independent and don't create consistency concerns

**What a cleanup task covers:**
- Review work from the bundle for consistency (naming, patterns, error handling)
- Extract shared components or utilities that emerged across tasks
- Fix rough edges, remove dead code, tighten up what was built quickly
- Ensure the bundle delivers a cohesive increment, not a bag of features
- Light testing of cross-task interactions within the bundle

The cleanup task description should reference specific concerns likely to arise from the preceding tasks, not be a generic "clean things up."

## Task Dependencies

Dependencies are between **tasks**, expressed via T-labels (T1, T2, T3...). T-labels are sequential across the entire bundle and are local-only identifiers (they carry no meaning outside the breakdown file).

- Every task's `Depends on:` field is either a list of T-labels or absent.
- **Parallelizable work:** Tasks that don't depend on each other can be done concurrently. Call this out explicitly if it would help the user — it informs staffing and ordering.
- **Blocking risks:** If a task is high-risk or uncertain (e.g., depends on a third-party API with unclear docs, requires a design decision that isn't settled), flag it. High-risk tasks should be prioritized early so surprises surface before they block everything downstream.

## Platform Splits

Exactly one platform per task. The allowed values:

- **Backend** — server-side logic, APIs, database, infrastructure
- **Frontend** — web application UI
- **iOS** — native or cross-platform iOS app
- **Android** — native or cross-platform Android app
- **Design** — Figma files, wireframes, design specs, design system work

A "single feature" that spans Backend + Frontend + Design becomes three tasks. Group related tasks visually in the markdown (sequential T-labels) but never collapse them into one.

## Design-Within-Scope Decomposition

If the scope under task-breakdown legitimately includes design work alongside implementation, follow these rules:

- **Design task before frontend task** that depends on it. Express via `Depends on:`.
- **Design tasks have Platform = Design.** They produce Figma frames, not code.
- **Design-as-you-go is the default for a single scope.** Design tasks are interleaved within the task list, each preceding the implementation task it unblocks.

If the design effort is large enough to warrant its own milestone (e.g., "design the entire feature suite before any implementation"), that's a multi-milestone signal — the seam check should fire and route the user to `milestone-breakdown`.
