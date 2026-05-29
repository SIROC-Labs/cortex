# asana-workflow Plugin — Development Guide

## Plugin Structure

```
asana-workflow/
├── CLAUDE.md              ← you are here
├── .claude-plugin/
│   └── plugin.json        ← plugin manifest (name, version, skills array)
├── bin/                   ← executables exposed on PATH (Claude Code auto-prepends <plugin>/bin/). Name files `asana-<verb>.<ext>` where `<ext>` is `sh` or `py` (use whichever fits the script — Python wins once any non-trivial parsing, JSON, or HTTP is involved); invoke by bare command name from skills.
├── references/            ← plugin-wide shared references (board-resolution, qa-routing)
└── skills/
    ├── asana-api/         ← Asana API operations (bundled)
    ├── create-pr/         ← PR creation (bundled)
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
    │   └── references/    ← input resolution, implementation plan template
    ├── submit-breakdown/  ← Faithfully replicate a task breakdown into Asana as Refinement-status tasks (bundled)
    │   └── references/    ← description template (thin), formatting rules
    ├── task-breakdown/    ← Strategic decomposition of specs into milestone-based task roadmaps with rough estimates and validation (bundled)
    │   └── references/    ← discovery guide, decomposition principles, output format
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

task-breakdown
  ├── asana-api          (optional: read existing tasks/projects for context during discovery)
  └── → hands off to submit-breakdown (Phase 7, optional: user confirms transition)

submit-breakdown           (faithful uploader: breakdown → Asana tasks at Product Status = Refinement)
  ├── asana-api          (create tasks, set custom fields incl. Refinement enum, wire dependencies)
  └── → hands off to refine-tasks (tasks created at Refinement status; user runs refine-tasks next)

refine-tasks               (Refinement-status Asana tasks → Unassigned with implementation-plan.md attached)
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
| `superpowers:brainstorming` | `superpowers@claude-plugins-official` | start-task (Step 10, brainstorm workflow) |

## Development Workflow

### Adding a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
2. Add the skill to `.claude-plugin/plugin.json` under `"skills"`
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
