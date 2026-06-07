---
name: task-breakdown
description: >
  Subdivides one coherent scope into implementation tasks. Produces a folder bundle —
  `breakdown.md` (T-blocks only) plus one per-task `T{N}-<slug>-implementation-plan.md`
  attachment — ready for `submit-breakdown` to push to Asana with tasks landing
  `Unassigned`. Drives the interview via `superpowers:brainstorming`. Never authors
  milestone content: if the seam check detects multi-milestone scope, redirects the
  user to `milestone-breakdown` (user always has final say). Use this skill whenever
  the user wants to break a single scope into tasks — "break this into tasks",
  "task-breakdown", "/task-breakdown", "plan the tasks under M3", or provides an Asana
  milestone task URL / project URL + milestone name / local spec / free text /
  current directory and wants implementation tasks. Source code + convention files
  only during discovery — never reads prior breakdowns, specs, PRDs, or planning docs.
---

# Task Breakdown

Subdivide one coherent scope into implementation tasks. Output is a folder bundle under
`<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<slug>/`:

- **`breakdown.md`** — optional `**Target milestone:**` metadata line plus one `## T{N} :: <title>` block per task (Purpose, Description, Acceptance criteria, optional Depends on, Attachments).
- **`T{N}-<slug>-implementation-plan.md`** — one per task. Cites real codebase paths and pattern exemplars surfaced during discovery and the brainstorming interview. `submit-breakdown` renames the file to `implementation-plan.md` at upload time.

A bundle produced here is push-ready: every task with a plan attachment lands `Unassigned` in Asana. Tasks without a plan land `Refinement`. No separate `refine-tasks` pass is needed for tasks created via this skill.

## Single Unified Flow

No PLAN / EXPAND modes. No sub-modes. One flow.

### Phase 1 — Ingest, Codebase Discovery, Seam Check

Accept any input shape — Asana milestone task URL, project URL + section, local spec file, free text, current working directory.

Walk the repo for `CLAUDE.md` / `AGENTS.md` plus current source in the areas the work will touch. **Never read prior breakdowns, specs, PRDs, or planning docs** — source code and convention files only. See `references/discovery-guide.md` for the source-detection table, the off-limits paths, and the questioning strategy.

Apply the **seam-check heuristic** (signals: multiple independent feature surfaces, heavy multi-platform scope, named phases / sub-projects, user language referencing "milestones / phases / tracks / roadmap"). If the seam check fires, surface what you detected and offer to redirect to `milestone-breakdown`. The user always has final say. See `references/discovery-guide.md` → "Seam Check".

### Phase 2 — Brainstorming Interview

Drive via `superpowers:brainstorming`. Topic universe scoped to task-level decisions:

- Scope edges — what's in, what's out, where the task list ends
- Pattern selection from the codebase — which existing pattern each task follows
- UX / behavior specifics
- Naming, file structure, module placement
- Migration / backwards compatibility
- Test scope per task
- Trade-offs the user hasn't named

One question at a time. Treat the user as a technical expert. Capture any milestone reference the user names — it becomes the optional `**Target milestone:**` metadata.

### Phase 3 — Task List Proposal & Approval

Synthesize the structured task list: T-labels (sequential across the whole bundle), names, one-line Purpose, Description, Acceptance criteria, Platform, Category, Depends on. See `references/decomposition-principles.md` for ordering, scoping, platform splits, and cleanup-task rules. Present in a single message. Wait for explicit "go". Iterate on push-back.

### Phase 4 — Batch Plan Generation

For each T-task, generate `T{N}-<slug>-implementation-plan.md` from the plugin-level shared template at `plugins/asana-workflow/references/implementation-plan-template.md`. Plans cite real codebase paths and pattern exemplars from Phase 1. The "Resolved decisions" section is sourced from the Phase 2 brainstorm transcript — no re-asking, no re-litigating.

### Phase 5 — Write the Bundle

Write `breakdown.md` plus each `T{N}-<slug>-implementation-plan.md` to `<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<slug>/`. Resolve `<repo-root>` via `git rev-parse --show-toplevel`. If the folder already exists, append `-v2`, `-v3`, ... until the name is free.

See `references/output-format.md` for the `breakdown.md` grammar and the `**Target milestone:**` convention.

### Phase 6 — Self-Review Pass

Validate inline: no placeholders, real file paths in plans, no dangling T-deps, no redundant tasks, no off-limits references (input PRDs, prior breakdowns, `CLAUDE.md`, target Asana project URL). Fix inline before handoff.

### Phase 7 — Handoff

Surface the bundle path and offer `submit-breakdown`:

> "Bundle saved to `<folder>`. Submit to Asana now? [Y/n]"

If yes, invoke `asana-workflow:submit-breakdown` via the Skill tool with the folder path. `submit-breakdown` parses the optional `**Target milestone:**` (confirming with the user before slotting) and uploads each `T{N}-<slug>-implementation-plan.md` as `implementation-plan.md` on its task.

## What This Skill Does NOT Do

- Author milestone content. Milestone blocks (Purpose, Product Requirements, milestone-level Acceptance Criteria, M-label DAG, milestone-spec attachments) belong exclusively to `milestone-breakdown`.
- Validate milestones, enforce milestone DAG rules, or touch any milestone task description.
- Create or modify Asana resources — that is `submit-breakdown`.
- Read prior task-breakdowns, prior milestone-breakdowns, prior PRDs, prior specs, or any planning doc during discovery.
- Write code, scaffold projects, or modify application sources.
- Assign people, set priorities (beyond the existing P3 default), or produce estimates.

## Reference Files

- `references/discovery-guide.md` — source detection, repo walk, seam-check heuristic, off-limits paths, questioning strategy
- `references/decomposition-principles.md` — task ordering, scoping, platform splits, cleanup tasks, task-level dependencies
- `references/output-format.md` — `breakdown.md` grammar (T-blocks + `**Target milestone:**` metadata) and field reference
- `plugins/asana-workflow/references/implementation-plan-template.md` — plugin-level shared per-task plan template (also used by `refine-tasks`)
