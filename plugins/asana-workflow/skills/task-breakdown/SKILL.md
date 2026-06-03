---
name: task-breakdown
description: >
  Decomposes product work into a milestone-based roadmap of implementation tasks. Use this skill
  whenever the user wants to plan, organize, or structure implementation work — "break down this spec",
  "plan this project", "create a task breakdown", "roadmap this", "/task-breakdown", or provides a spec
  document (markdown, PDF, Asana task/project URL, Figma link) and wants to figure out how to organize
  the implementation. Also use when the user wants to restructure, revise, or extend an existing task
  breakdown. Works for both greenfield projects (new spec to full breakdown) AND incremental work on
  existing projects (change requests, new features, bug batches slotted into existing milestones).
---

# Task Breakdown

Decompose product work into a milestone-based roadmap of implementation tasks. The output is a markdown file listing milestones, tasks within each milestone, and — critically — the rationale for why work is divided this way.

This is about **strategic decomposition**, not detailed task specs. Each task gets a purpose, description, and acceptance criteria — but not implementation plans or file lists. A separate downstream skill will later read this breakdown to produce detailed specs and create tasks in project management tools.

The breakdown file is a **bridge document**: it must contain all references (spec files, Asana task URLs, Figma links, external docs) that the downstream skill will need for full context.

## The Flow

This is a conversational skill — not a one-shot generator. Work through these phases in order, but adapt to what the user brings. If they arrive with a complete spec and clear context, move quickly through discovery. If they're still figuring things out, spend more time there.

### Phase 1: Discover

Gather all relevant context before proposing any structure. The goal is a complete picture of what exists, what needs to be built, and across which platforms.

Read **`references/discovery-guide.md`** for the full discovery checklist. The key areas:

1. **Specification sources** — collect every spec, doc, URL, and file path. Read all of them.
2. **Existing project state** — new project or existing? What's already built? Are there existing milestones?
3. **Platform inventory** — which platforms (Backend, Frontend, iOS, Android, Design) are involved and what's their current state?
4. **Design state** — do designs exist? Is a Figma file available? Do designs need to be created before implementation can start?
5. **External dependencies** — third-party APIs, services, infrastructure needs.
6. **Team context** — who's doing the work? This affects task granularity.

Be smart about discovery. Batch related questions. Skip areas that are obviously irrelevant. But never propose a breakdown until you have enough context to make informed decomposition decisions.

**Every URL, file path, and reference discovered here must appear in the output's References section.**

### Phase 2: Propose Milestone Structure

Before breaking down individual tasks, propose the milestone structure and get alignment:

- How many milestones (or which existing milestones to extend)?
- What does each milestone deliver as a usable product increment?
- Why this ordering?

For design-heavy projects, consider whether design needs its own milestone before implementation, or whether design and backend can be parallelized while frontend is deferred.

Present the rationale for your structure. Get user feedback before proceeding.

### Phase 3: Break Down Each Milestone

For each milestone, propose the tasks — their platform, ordering, and scoping. Read **`references/decomposition-principles.md`** for the rules governing:

- **Milestone design** — each milestone delivers a usable increment, not a technical layer
- **Task ordering** — foundational before dependent, read before write, backend before frontend, design before implementation
- **Task scoping** — one platform per task, completable in a single session (`00:30`–`04:00`)
- **Dependencies** — explicit cross-references using T-labels, identify parallelizable work, flag blocking risks
- **Cleanup tasks** — when and why to include a milestone cleanup/review task

Explain the rationale for ordering and scoping decisions. These decisions embody the core value of the breakdown — the "why" matters as much as the "what."

**Write task descriptions in product language.** The `Description:` field must be understandable by anyone on the team — PM, designer, developer, QA — not just the engineer who will implement it. Lead with what the user sees or experiences when this task is done. Do not lead with the implementation approach (which API, which component, which pattern). Those details belong in the refinement step, once the codebase is read. See `references/output-format.md` → "Description" for examples and the full rule.

### Phase 3.5: Validate

After tasks are decomposed and before the user reviews them, walk every task and run these checks:

- *Platform check* — exactly one platform per task. If a task spans multiple platforms (e.g., backend API + frontend UI), propose splitting into separate tasks with a dependency between them.
- *Size check* — the task is completable in a single session (roughly `00:30`–`04:00`). If a task feels larger, propose a split with reasoning. If much smaller than `00:30`, consider merging with a related task.
- *Split check* — apply the three split signals from `references/decomposition-principles.md` → "When to split a task": (1) does the description require a numbered list? (2) does it bundle a routine sub-feature with a complex/novel one? (3) can the first half be tested without the second half existing? Any "yes" is a reason to propose a split.
- *Redundancy check* — the task does not duplicate work already covered by another task in this breakdown.

Surface any issues to the user and resolve them (split / merge / reword) before proceeding.

### Phase 4: Challenge and Refine

If the user suggests a different ordering or structure, evaluate it against the decomposition principles:

- If it's valid — agree and explain why it works
- If it violates a dependency or principle — push back with clear reasoning ("Projects depend on Users for the assigned_user_ids relationship. Building Users first means the Project detail page can link to real User pages from day one.")

This is collaborative design, not rubber-stamping. The goal is the best decomposition, not the first one.

### Phase 5: Write the Breakdown

Produce the final markdown file following the format in **`references/output-format.md`**.

**File location:** `<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<descriptive-name>.md`

Resolve `<repo-root>` from the git repository root (`git rev-parse --show-toplevel`), not the current working directory. The descriptive name is a short slug derived from what the breakdown covers — all lowercase, hyphen-separated, with the date first so listings sort chronologically (e.g., `2026-05-20-management-features.md`, `2026-05-20-auth-redesign.md`).

If a file with the same name already exists, append `-v2`, `-v3`, etc. until the name is free (e.g., `2026-05-20-management-features-v2.md`).

Create the `docs/cortex/task-breakdowns/` directory if it doesn't exist. The file is written locally as a working artifact — it does **not** need to be committed; `submit-breakdown` embeds every reference directly into each Asana task description.

### Phase 6: Originating Task Disposition

When the breakdown was triggered from a single Asana task (e.g., a requirements-stage task that said "build feature X"), that originating task is now superseded by the breakdown's tasks. It needs to be dealt with.

**When this applies:** The input to task-breakdown was an Asana task URL (not a project URL, not a local spec file). That task is the "originating task."

**When this does NOT apply:** The input was a spec file, a project URL, or multiple sources. Skip this phase.

If an originating task exists, ask the user:

> "The originating task `<task-name>` (`<task-url>`) has been decomposed into T1–TN. What should happen to it?
> 1. **Delete** — remove it entirely
> 2. **Complete** — mark as complete with a comment listing the new tasks
> [1/2]"

Write the user's choice into the breakdown file's **Originating Task** section (see `references/output-format.md`). The `submit-breakdown` skill will execute the chosen action after creating all new tasks.

### Phase 7: Transition to Submit

After writing the breakdown file, offer to push it to Asana:

> "Breakdown saved to `<file-path>`. Want to submit it to Asana now? [Y/n]"

If the user confirms, invoke the `asana-workflow:submit-breakdown` skill using the Skill tool (skill name: `asana-workflow:submit-breakdown`). Pass the breakdown file path and, if the breakdown's References section contains an Asana project URL, include that too.

If the user declines, stop here. They can run `/submit-breakdown` later with the file path.

## What This Skill Does NOT Do

- Does not produce implementation plans or file-level specs (those are produced later, during a separate refinement step that reads the codebase)
- Does not create Asana tasks or interact with project management tools for writing
- Does not write code or scaffold projects
- Does not assign people, set priorities, or manage external IDs
- Does not produce estimates — estimates should come from the team doing the work, after codebase analysis during refinement

It **does** read from Asana (existing tasks, projects, milestones) during discovery to understand current state.

## Reference Files

- **`references/discovery-guide.md`** — Full discovery checklist and questioning strategy
- **`references/decomposition-principles.md`** — Rules for milestone design, task ordering, scoping, dependencies, and cleanup tasks
- **`references/output-format.md`** — Markdown template and field reference for the breakdown file
