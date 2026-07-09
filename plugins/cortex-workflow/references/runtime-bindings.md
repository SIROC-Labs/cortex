# Runtime Bindings

Maps abstract development capabilities to the concrete skill that provides them in each supported runtime. Skills must reference capabilities, never runtime-specific skill names — this table is the single place where that mapping lives. Supporting a new runtime = adding a column; swapping a helper skill = editing a cell.

## Detecting the Current Runtime

- **Claude Code** — the `Skill` tool and `CLAUDE_PLUGIN_ROOT` env var are present.
- **OpenCode** — the injected bootstrap context states you are running under OpenCode.
- **Codex** — a Codex CLI session; skills load natively with no Claude/OpenCode markers.

## Capabilities

- **`CREATE_PLAN`** — produce an implementation plan with human interaction (explore intent, requirements, design through dialogue).
- **`EXECUTE_PLAN`** — execute an already-in-place plan. The operator keeps the ability to guide execution; the plan's producer is irrelevant.
- **`EXECUTE_INLINE`** — implement directly from the available info using the agent's native tools, without elaborating a new plan.
- **`DIAGNOSE_AND_FIX_BUG`** — systematic bug investigation: reproduce, isolate, identify the root cause with specificity, and implement the fix.
- **`APPLY_TDD`** — test-driven development: write the test first (failing), implement until the full suite is green. General-purpose; `fix-bug` applies it as a regression-test hard gate.

## Bindings

| Capability | Claude Code | OpenCode | Codex |
|---|---|---|---|
| `CREATE_PLAN` | `superpowers:brainstorming` · `feature-dev:feature-dev` | `superpowers:brainstorming` | `superpowers:brainstorming` |
| `EXECUTE_PLAN` | `superpowers:subagent-driven-development` · `feature-dev:feature-dev` ¹ | `superpowers:subagent-driven-development` | `superpowers:subagent-driven-development` |
| `EXECUTE_INLINE` | native tools | native tools | native tools |
| `DIAGNOSE_AND_FIX_BUG` | `superpowers:systematic-debugging` | `superpowers:systematic-debugging` | `superpowers:systematic-debugging` |
| `APPLY_TDD` | `superpowers:test-driven-development` | `superpowers:test-driven-development` | `superpowers:test-driven-development` |

¹ `feature-dev` runs its full workflow with the attached plan as input context.

**Resolution rules:**
- A cell with **multiple bindings** (separated by `·`) means the operator chooses — ask, don't assume.
- `CREATE_PLAN` bindings may carry through to implementation on their own. After the binding returns, chain into `EXECUTE_PLAN` only if a plan was produced but not yet implemented — judge by outcome, not by which binding ran.

## Plan Artifact Convention

A task "has a plan" when it carries an attachment named `implementation-plan.md` — the canonical name, produced by `refine-tasks` (but any producer is valid: brainstorming output, feature-dev output, hand-written). Failing the canonical name, any attachment whose **content** reads as an implementation plan (ordered steps, affected files/modules, migration notes, test strategy) counts, regardless of filename. Detection is by content, not only by name, and needs no operator confirmation. The plan's producer is irrelevant to consumers; only its presence and content matter.
