# Decomposition Principles

These rules govern how work is broken into milestones and tasks. They exist because decomposition decisions have downstream consequences — a bad ordering creates blockers, a bad scope creates tasks that are either too vague to start or too small to be worth tracking.

## Milestone Design

Each milestone delivers a **usable increment of the product** — not a technical layer.

- **Bad:** "M1: All backend, M2: All frontend" — this means nothing works until M2 is done
- **Good:** "M1: Auth (backend + frontend), M2: User management (backend + frontend)" — each milestone delivers something a user can interact with

However, within a milestone, **tasks are platform-specific** (one task = one platform). The milestone groups them by product value; the tasks separate them by execution context.

**Ordering milestones:** Consider both product value and implementation dependency. The milestone that unblocks the most downstream work should come first, unless there's a compelling product reason to prioritize differently.

**Existing projects:** New tasks may belong in existing milestones. Don't create new milestones if the work fits naturally into the current structure. Propose new milestones only when the work represents a genuinely new product increment. Check for existing milestones in Asana sections or previous task-breakdown files.

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

## Design-Driven Decomposition

When a project is design-heavy and designs don't yet exist:

**Option A: Design-first milestone.** Create M1 as a design milestone with Design-platform tasks for each major UI area. Implementation milestones follow. Choose this when the product vision is unclear and design exploration is needed before committing to implementation.

**Option B: Parallel tracks.** Design and backend proceed in parallel. Frontend tasks are deferred or placed in later milestones with explicit dependencies on the corresponding design tasks. Choose this when the backend architecture is clear and design is mainly about UI specifics.

**Option C: Design-as-you-go.** Design tasks are interleaved within milestones, each preceding its corresponding frontend implementation task. Choose this for projects with an established design system where design work is incremental rather than exploratory.

Discuss the tradeoffs with the user and let them choose. The right approach depends on the project's design maturity and team structure.

