# asana-workflow Plugin — Development Guide

## Plugin Structure

```
asana-workflow/
├── CLAUDE.md              ← you are here
├── .claude-plugin/
│   └── plugin.json        ← plugin manifest (name, version, skills array)
├── bin/                   ← executables exposed on PATH (Claude Code auto-prepends <plugin>/bin/). Name files `asana-<verb>.<ext>` where `<ext>` is `sh` or `py` (use whichever fits the script — Python wins once any non-trivial parsing, JSON, or HTTP is involved); invoke by bare command name from skills.
├── references/            ← plugin-wide shared references (board-resolution, qa-routing, asana-custom-field-discovery, implementation-plan-template)
└── skills/
    ├── asana-api/         ← Asana API operations (bundled)
    ├── create-pr/         ← PR creation (bundled)
    ├── create-prd/        ← PRD generation from Asana, Notion, Figma, local files, or any URL (bundled)
    ├── create-spec/       ← Technical-spec generation from a PRD, ticket, design, free-text, or the current folder. Uses superpowers:brainstorming for the interview (bundled)
    │   └── references/    ← output format (heading levels, minimum 7 sections, optional sections)
    ├── fix-bug/           ← Bug-fix lifecycle orchestrator (bundled)
    ├── git-check/         ← Git state validation (bundled)
    ├── generic-qa/        ← Shared QA process & references (not a skill — used by web-qa, mobile-qa)
    ├── frontend-testing/  ← Frontend testing patterns & infrastructure (bundled)
    ├── generic-testing/   ← Shared testing fundamentals & references (not a skill — used by platform-specific testing skills)
    ├── log-task/          ← Create Asana task from conversation-discovered work (bundled)
    ├── mobile-qa/         ← Mobile QA investigation & verification (bundled, mobile-mcp)
    ├── mobile-testing/    ← Mobile testing patterns & infrastructure (bundled — extends generic-testing)
    ├── pre-ship-check/    ← Readiness gate before shipping (bundled)
    ├── ship-it/           ← Shipping orchestrator (bundled)
    ├── start-task/        ← Entry point for dev workflow (bundled)
    │   └── scripts/       ← skill-local helpers (e.g., checkpoint.sh — checkpoint file I/O)
    ├── refine-tasks/      ← Codebase-informed refinement: turn Refinement-status Asana tasks into one-shotters with attached implementation plans (bundled)
    │   └── references/    ← input resolution
    ├── submit-breakdown/  ← Faithfully replicate a task breakdown into Asana — sections, milestone tasks (resource_subtype=milestone), implementation tasks (Refinement-status). Idempotent re-runs. (bundled)
    │   └── references/    ← description template (implementation + milestone), formatting rules
    ├── milestone-breakdown/   ← Strategic decomposition of specs into milestone-based roadmaps. Outputs a folder: `breakdown.md` (thin rich blocks for Asana descriptions) + per-milestone `M{N}-milestone-spec.md` (uploaded as Asana attachments so milestones are atomic). Milestone-first mode only; never authors tasks. (bundled)
    │   └── references/        ← discovery guide (with landscape inspection + protectionism), decomposition principles (milestone design + DAG), output format (templates + parsing contract), validation checklist
    ├── task-breakdown/    ← Task-level subdivision of one coherent scope. Uses `superpowers:brainstorming` for the technical interview at Phase 2. Outputs a folder bundle (`docs/cortex/task-breakdowns/<date>-<slug>/`): `breakdown.md` (T-blocks only, optional `**Target milestone:**` hint) + per-task `T{N}-<slug>-implementation-plan.md` attachments. Never authors milestone content; redirects multi-milestone scopes to `milestone-breakdown` via a seam-check heuristic. Single unified mode. (bundled)
    │   └── references/    ← discovery guide (with seam-check heuristic + off-limits rule), decomposition principles (task-level only), output format (T-block template + `**Target milestone:**` convention)
    ├── web-qa/            ← Web QA investigation & verification (bundled)
    └── work-summary/      ← Session summary (bundled)
```

Each skill follows: `skills/<name>/SKILL.md` + optional `references/` subdirectory.

## Skill Relationships

```
start-task
  ├── asana-api          (fetch task, update status)
  ├── git-check          (validate git state)
  ├── web-qa / mobile-qa (bug QA loop via QA sub-flow; resolution per plugin references/qa-routing.md)
  ├── [external] feature-dev:feature-dev    (route non-bug tasks)
  └── fix-bug                   (route bug tasks through orchestrator)

fix-bug
  ├── [external] superpowers:systematic-debugging  (root cause investigation)
  ├── [external] superpowers:test-driven-development  (TDD hard gate)
  └── → returns to start-task  (for QA verify + ship)

ship-it
  ├── pre-ship-check     (readiness gate, owns QA verification gate)
  ├── work-summary       (session summary)
  └── create-pr          (open PR)

pre-ship-check
  ├── git-check                 (git state)
  └── web-qa / mobile-qa        (QA verification prompt on non-bug tasks; resolution per plugin references/qa-routing.md)

log-task
  ├── asana-api          (create task, set custom fields, add to projects)
  └── → hands off to start-task (Plan Only) or ship-it (Fix Done) depending on whether the work was planned vs already done

create-prd             (standalone: reads sources, interviews user, writes PRD — no skill dependencies)
  ├── asana-api          (optional: fetch task + attachments when Asana URL is provided)
  └── (external MCPs)    (Notion, Figma, Google Drive, WebFetch — used when relevant source URLs are present)

create-spec            (PRD / ticket / design / free-text → technical spec markdown at docs/cortex/specs/)
  ├── [external] superpowers:brainstorming  (interview phase — one question at a time, multiple choice, section-by-section approval)
  ├── asana-api          (optional: fetch task + attachments when Asana URL is provided as the input)
  └── (external MCPs)    (Notion, Figma, Google Drive, WebFetch — used when relevant source URLs are present)

milestone-breakdown        (strategic decomposition: spec → milestone bundle of breakdown.md + per-milestone milestone-spec.md files; milestone-first only)
  ├── asana-api                          (existing-project landscape inspection: fetch sections + milestone tasks; classify expanded vs unexpanded)
  ├── [external] superpowers:brainstorming  (decomposition interview at Phase 3)
  └── → hands off to submit-breakdown    (Phase 8, optional: user confirms transition)

task-breakdown            (task-level subdivision: one scope → folder bundle of breakdown.md + per-task implementation-plan.md files; single unified mode)
  ├── [external] superpowers:brainstorming  (technical interview at Phase 2)
  ├── asana-api                              (read Asana milestone task + attachments when the input names one; resolve project context for the target milestone hint)
  └── → hands off to submit-breakdown        (Phase 7, optional: user confirms transition)

submit-breakdown           (faithful uploader: accepts either a single .md file from task-breakdown OR a folder bundle from milestone-breakdown; creates Asana sections + milestone tasks; uploads milestone-spec.md and per-task implementation-plan.md attachments; idempotent re-runs)
  ├── asana-api          (create tasks, set custom fields, wire dependencies, create milestone-subtype tasks, detect existing milestones, upload attachments)
  └── → T-tasks without an implementation-plan attachment land in Refinement; user may invoke refine-tasks later on those (now optional, not the default path)

refine-tasks               (ad-hoc standalone path: refine Refinement-status Asana tasks into Unassigned with implementation-plan.md attached — for tasks that did NOT come through task-breakdown, e.g. manual log-task, hand-edited descriptions, legacy tasks)
  ├── asana-api          (resolve task set, fetch descriptions, upload attachment, update fields, move status)
  └── (codebase read)    (no other skill dependency — runs in the repo)
```

generic-qa (shared markdown, not a skill)
  ├── process.md         (universal QA flow)
  └── references/        (reporting, investigation)

web-qa (extends generic-qa)
  └── references/        (Chrome DevTools MCP tooling, URL discovery, DOM/console/network)

mobile-qa (extends generic-qa, mobile-mcp)
  └── references/        (mobile-mcp tooling, app+device discovery, accessibility tree/gestures/logs)

generic-testing (shared markdown, not a skill — universal fundamentals)
  ├── process.md         (the 10 non-negotiables: determinism, behavior-over-implementation, AAA, etc.)
  └── references/
      └── infrastructure.md     (CI pipeline, flake detection, benchmarks, reporting — stack-agnostic)

frontend-testing (bundled skill — extends generic-testing)
  ├── process.md         (Testing Library, component patterns, mocking boundaries, E2E)
  └── references/
      ├── stack-detection.md    (detect frontend runner, framework, coverage, package manager)
      └── infrastructure.md     (Jest/Vitest coverage configs, frontend CI pipeline)

mobile-testing (bundled skill — extends generic-testing; scope: unit + integration on native iOS / native Android / KMP)
  ├── process.md         (ViewModels, repos, async/time, mocking, DI)
  └── references/
      └── infrastructure.md     (coverage configs, JVM/Xcode parallelism, toolchain caching)
```

## External Dependencies

Skills NOT bundled — must be installed separately:

| Skill | Plugin | Used By |
|---|---|---|
| `feature-dev:feature-dev` | `feature-dev@claude-plugins-official` | start-task (Step 10, non-bug) |
| `superpowers:systematic-debugging` | `superpowers@claude-plugins-official` | fix-bug (Step 1) |
| `superpowers:brainstorming` | `superpowers@claude-plugins-official` | start-task (Step 10, brainstorm workflow); create-spec (Phase 3, interview); milestone-breakdown (Phase 3, decomposition interview); task-breakdown (Phase 2, interview) |
| `superpowers:using-git-worktrees` | `superpowers@claude-plugins-official` | start-task (Step 6a, optional) |

## Development Workflow

### Adding a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
2. Skills are auto-discovered from the `skills/` directory — no manifest update required. Do NOT edit `plugin.json` or `marketplace.json` version fields (versioning is via the GitHub Action `bump-version.yml`).
3. Add optional `references/` files and reference them from SKILL.md
4. **Update this CLAUDE.md** — add the skill to the Plugin Structure diagram above, and add a Skill Relationships entry if it invokes or hands off to other skills
5. **Update the repo `README.md`** if the skill is user-invokable (has a slash command or responds to user trigger phrases directly) — add a row to the asana-workflow skill table. Internal helpers like `asana-api` or `git-check` stay out of the user-facing table.

### Modifying an existing skill

- SKILL.md body is loaded into context on every trigger — keep it focused
- Use `references/` for large docs (>~100 lines) to avoid bloating context
- Test with `/skill-creator:skill-creator` for iterative refinement
- **Update the Skill Relationships section above** if the change adds, removes, or reroutes a cross-skill interaction (a new dependency, a dropped handoff, a moved responsibility) — the diagram is the canonical map and drifts easily when one skill changes alone

### Testing locally
```bash
# Reload plugin after changes
/plugin reload asana-workflow

# Test a skill directly
/start-task <asana-url>
/ship-it
```

## Environment Requirements

- `ASANA_PERSONAL_ACCESS_TOKEN` — set in `~/.zshrc`
  - Get from: https://app.asana.com/0/my-apps
