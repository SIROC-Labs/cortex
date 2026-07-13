# cortex-workflow Plugin — Development Guide

## Plugin Structure

```
cortex-workflow/
├── CLAUDE.md              ← you are here
├── .claude-plugin/
│   └── plugin.json        ← plugin manifest (name, version, skills array)
│                          ← (no `bin/`) — helper scripts live skill-local in each skill's `scripts/`, invoked via `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/<skill>/scripts/<name>` (cross-runtime). The plugin deliberately does NOT use a `bin/` PATH dir: Claude Code auto-prepends `<plugin>/bin/`, but OpenCode/Codex do not, so a bare-name `bin/` script would be Claude-Code-only.
├── references/            ← plugin-wide shared references (qa-routing, runtime-bindings)
│   └── workflow/          ← neutral workflow rules: fields, lifecycle, boards
└── skills/
    ├── task-manager/      ← neutral task-manager interface / seam (bundled)
    ├── task-manager-asana/ ← Asana provider implementation (bundled)
    ├── task-manager-jira/ ← Jira provider implementation (bundled)
    ├── backend-qa/        ← Backend (API/service) QA investigation & verification (bundled)
    ├── backend-testing/   ← Backend testing patterns & infrastructure (bundled — extends generic-testing)
    ├── create-pr/         ← PR creation (bundled)
    ├── create-prd/        ← PRD generation from Asana, Notion, Figma, local files, or any URL (bundled)
    ├── product-one-pager/ ← Product one-pager/brief generation & review against a senior-PM + product-owner bar (bundled)
    ├── fix-bug/           ← Bug-fix lifecycle orchestrator (bundled)
    ├── git-check/         ← Git state validation (bundled)
    ├── implement-feature/ ← Non-bug routing orchestrator: plan detection + runtime-bindings resolution (bundled)
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
    ├── task-breakdown/    ← Strategic decomposition of specs into milestone-based task roadmaps with validation (bundled)
    │   └── references/    ← discovery guide, decomposition principles, output format
    ├── web-qa/            ← Web QA investigation & verification (bundled)
    └── work-summary/      ← Session summary (bundled)
```

Each skill follows: `skills/<name>/SKILL.md` + optional `references/` subdirectory.

## Skill Relationships

```
start-task
  ├── task-manager       (fetch task, update status)
  ├── git-check          (validate git state)
  ├── web-qa / mobile-qa / backend-qa (bug QA loop via QA sub-flow; resolution per plugin references/qa-routing.md)
  ├── [external] feature-dev:feature-dev    (route non-bug tasks)
  ├── implement-feature  (route non-bug tasks per plugin references/runtime-bindings.md)
  └── fix-bug                   (route bug tasks through orchestrator)

implement-feature          (thin router: detects implementation-plan.md, resolves capability bindings)
  ├── [external] superpowers:brainstorming                (CREATE_PLAN — all runtimes)
  ├── [external] superpowers:subagent-driven-development  (EXECUTE_PLAN — all runtimes)
  ├── [external] feature-dev:feature-dev                  (CREATE_PLAN / EXECUTE_PLAN — Claude Code only, operator choice)
  ├── (native tools)                                      (EXECUTE_INLINE — all runtimes)
  └── → returns control to its invoker  (from start-task: QA verify + ship; standalone: reports and stops)

fix-bug
  ├── [external] superpowers:systematic-debugging     (DIAGNOSE_AND_FIX_BUG — root cause investigation)
  ├── [external] superpowers:test-driven-development  (APPLY_TDD — TDD hard gate)
  └── → returns to start-task  (for QA verify + ship)

ship-it
  ├── pre-ship-check     (readiness gate, owns QA verification gate)
  ├── work-summary       (session summary)
  └── create-pr          (open PR)

pre-ship-check
  ├── git-check                 (git state)
  └── web-qa / mobile-qa / backend-qa  (QA verification prompt on non-bug tasks; resolution per plugin references/qa-routing.md)

log-task
  ├── task-manager       (create task, set fields, add to boards)
  └── → hands off to start-task (Plan Only) or ship-it (Fix Done) depending on whether the work was planned vs already done

product-one-pager      (standalone: generate or review a product one-pager/brief; no skill dependencies)
  └── → hands off to create-prd (optional: turn the one-pager into a full PRD)

create-prd             (standalone: reads sources, interviews user, writes PRD — no skill dependencies)
  ├── task-manager       (optional: fetch task + attachments when a task URL is provided)
  └── (external MCPs)    (Notion, Figma, Google Drive, WebFetch — used when relevant source URLs are present)

task-breakdown
  ├── task-manager       (optional: read existing tasks/boards for context during discovery)
  └── → hands off to submit-breakdown (Phase 7, optional: user confirms transition)

submit-breakdown           (faithful uploader: breakdown → tasks at Product Status = Refinement)
  ├── task-manager       (create tasks, set fields incl. Refinement status, wire dependencies)
  └── → hands off to refine-tasks (tasks created at Refinement status; user runs refine-tasks next)

refine-tasks               (Refinement-status tasks → Unassigned with implementation-plan.md attached)
  ├── task-manager       (resolve task set, fetch descriptions, upload attachment, set fields, set status)
  └── (codebase read)    (no other skill dependency — runs in the repo)
```

generic-qa (shared markdown, not a skill)
  ├── process.md         (universal QA flow)
  └── references/        (reporting, investigation)

web-qa (extends generic-qa)
  └── references/        (Chrome DevTools MCP tooling, URL discovery, DOM/console/network)

mobile-qa (extends generic-qa, mobile-mcp)
  └── references/        (mobile-mcp tooling, app+device discovery, accessibility tree/gestures/logs)

backend-qa (extends generic-qa)
  └── references/        (HTTP/logs/DB tooling, base-URL discovery + manual auth bootstrap, request/log/DB investigation)

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

backend-testing (bundled skill — extends generic-testing; integration-first via testcontainers)
  ├── process.md         (decision rule, DB isolation, test data, async/task orchestration, auth, generic-container tree)
  └── references/
      ├── stack-detection.md    (detect language/runner/container library + orchestration framework)
      ├── contract-testing.md   (spec-driven fakes for external services + drift guard)
      └── infrastructure.md     (heavy-local/light-CI split, test tagging, PR evidence contract)
```

## External Dependencies

Skills NOT bundled — must be installed separately:

| Skill | Plugin | Used By |
|---|---|---|
| `feature-dev:feature-dev` | `feature-dev@claude-plugins-official` | implement-feature (`CREATE_PLAN` / `EXECUTE_PLAN`, Claude Code only) |
| `superpowers:systematic-debugging` | `superpowers@claude-plugins-official` | fix-bug (`DIAGNOSE_AND_FIX_BUG`) |
| `superpowers:test-driven-development` | `superpowers@claude-plugins-official` | fix-bug (`APPLY_TDD`) |
| `superpowers:brainstorming` | `superpowers@claude-plugins-official` | implement-feature (`CREATE_PLAN`) |
| `superpowers:subagent-driven-development` | `superpowers@claude-plugins-official` | implement-feature (`EXECUTE_PLAN`) |

Capability-to-skill resolution per runtime lives in `references/runtime-bindings.md`.

## Task Manager Abstraction

Skills never talk to a task-tracking provider directly. They call the neutral `task-manager` seam (operations like `get_task`, `create_task`, `set_status`, `set_field`, `add_comment`, `upload_attachment`, `get_comments`, `resolve_board`). The seam resolves the active provider by **detection** — per-repo cache provider-marker → task-URL detection → ask the operator — via `resolve_provider.py` (no committed selector file; the marker is persisted in the machine-local `~/.cortex/` cache). It then delegates to the matching `task-manager-<provider>` skill — currently `task-manager-asana` (Asana) or `task-manager-jira` (Jira). This keeps every orchestrator provider-agnostic; swapping or adding a provider touches only the provider skill.

To add a provider, see `skills/task-manager/references/provider-guide.md`. For the full design, see the spec at `docs/superpowers/specs/2026-06-18-task-manager-abstraction-design.md`.

### Working with tasks (keep the abstraction intact)

- **Orchestrators go through the seam.** Any skill that reads/writes a task uses the `task-manager` interface's neutral operations — never a provider skill, an API call, or an identifier (GID / issue key) directly.
- **Who-names-whom (one-way):** orchestrators may name the seam + `references/workflow/*`; the seam names the provider it resolves; providers name only their own mechanics; the neutral workflow refs name nothing downstream (no provider, no GID). Callees never name callers.
- **Field/status/board vocabulary is neutral.** Use the names in `references/workflow/{fields,lifecycle,boards}.md`; never provider terms (Asana "section", Jira "statusCategory") in an orchestrator.
- **Extending the contract:** add an operation by editing `skills/task-manager/SKILL.md` (it's an open/semantic contract); then every provider must map it or degrade per the provider-guide's partial-support rule. Rare provider-specific needs use the documented escape hatch — don't push provider mechanics up into orchestrators.
- **`references/workflow/*` encodes siroc's workflow profile** (status pipeline, field set) — neutral in form but org-shaped; a different org adapts these, not the orchestrators.

## Naming Conventions for Interface Tokens

Three casings, each marking a different *kind* of token — match the kind, don't mix them. Always wrap tokens in backticks; that (plus `()` on operations) is what separates them from prose. Casing signals kind, not emphasis.

| Kind | Casing | Examples | Where it's defined / lives |
|---|---|---|---|
| **Capability** (resolved by *runtime*) | `UPPER_SNAKE` | `CREATE_PLAN`, `APPLY_TDD` | `references/runtime-bindings.md`; abstract slot, invoked as a unit, no signature |
| **Task-manager operation** | `lower_snake()` | `set_status(task, status)`, `add_comment(task, body)` | the contract in `skills/task-manager/SKILL.md`, mirrored by each provider's mapping table. A callable with arguments — orchestrators invoke it *through the seam*, usually described in prose, not written as a literal call |
| **Skill name** | `kebab-case` | `task-manager`, `start-task` | the runtime's skill identifier |

- Don't uppercase operations — they have signatures; `UPPER()` fights the function-vs-constant norm and is unreadable with arguments.
- Don't `()` capabilities or skill names — they aren't called with arguments.
- The task manager resolves its provider by **detection** (per-repo cache marker → task-URL detection → ask), via `resolve_provider.py`, persisted in the machine-local `~/.cortex/` cache marker — **not** from `runtime-bindings.md` (runtime detection). Both are detection-based, but they are separate indirection mechanisms (task-manager provider vs runtime capability bindings).

## Helper Script Conventions

Skills are prose (flexible, judgment); deterministic mechanics are **harnessed by helper scripts** the skill calls (predictable, enforceable). This is deliberately *not* an MCP — scripts run via Bash in every runtime, keep the escape hatch, and are the same logic an MCP would host if one is ever justified. Rules:

- **Language:** Python (stdlib only) once a script touches **JSON, HTTP, dates, or non-trivial parsing**; bash only for trivial git/CLI/text glue. (Examples: `tm.py` (board/fields/task/comment families) → Python; `checkpoint.sh` → bash.)
- **No `curl` for HTTP writes.** Use Python `urllib`. `curl -F` (multipart) and `curl -d "$(…)"` (command-substituted bodies) intermittently fail under the Bash sandbox's restrictive profile (`failed to change group ID`); a single top-level Python process avoids it. Plain `curl GET`/inline-`-d` are fine but prefer the helper.
- **Route task operations through `tm.py` — never hand-write inline `python3 -c`/`curl` for task reads/writes.** The CLI carries the guards (read-only fields like Asana's auto-managed ID field are refused / surfaced, not blindly written), the error-surfacing (an ad-hoc `urllib` call with no `try/except` crashes with an opaque traceback instead of the real API message), and the canonical-field handling. Ad-hoc HTTP is exactly how a forbidden write slips through (e.g. PUT-ing the auto-ID field → `cannot_manually_create_or_update_custom_id_field`).
- **Placement:** provider/skill-specific scripts live skill-local in that skill's `scripts/`, invoked via `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/<skill>/scripts/<name>` (cross-runtime; not the Claude-Code-only `bin/` PATH). They travel with the provider if it ever becomes its own plugin.
- **One CLI per provider:** each provider exposes a single `scripts/tm.py` with `<family> <verb>` subcommands (`board resolve …`, `fields list …`, …). Don't add separate per-op scripts or a separate `client.py` — fold the transport/client inline (a non-invoked, non-shared module only adds import boilerplate). Size is not an agent-token cost (the agent invokes, never reads the script); structure with internal functions.
- **Shared code = `task-manager/scripts/cache_util.py` only** — the one genuinely cross-provider module (cache lifecycle: key/read/write/freshness/provider-marker). It is imported (via a `__file__`-relative `sys.path.insert`), the single justified cross-skill import. Transport stays per-provider in each `tm.py`.
- **`__main__`-guard** every CLI script so it's importable without executing (testable, reusable).
- **Exit-code contract** (uniform across providers): `0` ok / `2` miss / `3` stale / `4` bootstrap-needed / `1` error. Documented per family in `task-manager/references/provider-guide.md`.
- **What stays in the skill (not scripted):** routing, ambiguity, content authoring (comments/PRs/plans), and the rare long-tail op (escape hatch). Script the deterministic column only; over-scripting forfeits the flexibility that's the reason to avoid an MCP.

## Development Workflow

### Adding a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
2. Add the skill to `.claude-plugin/plugin.json` under `"skills"`
3. Add optional `references/` files and reference them from SKILL.md
4. **Update this CLAUDE.md** — add the skill to the Plugin Structure diagram above, and add a Skill Relationships entry if it invokes or hands off to other skills
5. **Update the repo `README.md`** if the skill is user-invokable (has a slash command or responds to user trigger phrases directly) — add a row to the cortex-workflow skill table. Internal helpers like `task-manager`, `task-manager-asana`, or `git-check` stay out of the user-facing table.

### Modifying an existing skill

- SKILL.md body is loaded into context on every trigger — keep it focused
- Use `references/` for large docs (>~100 lines) to avoid bloating context
- Test with `/skill-creator:skill-creator` for iterative refinement
- **Update the Skill Relationships section above** if the change adds, removes, or reroutes a cross-skill interaction (a new dependency, a dropped handoff, a moved responsibility) — the diagram is the canonical map and drifts easily when one skill changes alone

### Testing locally
```bash
# Reload plugin after changes
/plugin reload cortex-workflow

# Test a skill directly
/start-task <task-url>
/ship-it
```

## Environment Requirements

- `ASANA_PERSONAL_ACCESS_TOKEN` — set in `~/.zshrc`
  - Get from: https://app.asana.com/0/my-apps
