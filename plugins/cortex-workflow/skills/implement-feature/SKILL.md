---
name: implement-feature
version: 0.1.0
description: >
  Routes non-bug implementation work to the right development skill for the current runtime.
  Detects an available implementation plan, resolves capabilities (CREATE_PLAN, EXECUTE_PLAN,
  EXECUTE_INLINE) via the runtime-bindings table, and asks the operator when more than one
  binding applies. Works standalone — "implement this task", "route this implementation",
  "/implement-feature" — or as a routing step inside a larger workflow, in which case it
  returns control to the invoking workflow when implementation completes.
---

# Implement Feature

Thin routing orchestrator for implementation work. Contains no development logic — it picks the entry capability, hands over the context bundle, and returns control to whoever invoked it. All runtime-specific skill names live in **`plugins/cortex-workflow/references/runtime-bindings.md`**; this skill only expresses policy in terms of the three capabilities:

- `CREATE_PLAN` — produce a plan with human interaction
- `EXECUTE_PLAN` — execute an already-in-place plan (operator can still guide)
- `EXECUTE_INLINE` — implement directly from the available info, no new plan

## Inputs

From the invoking workflow, when there is one:
- Full task context bundle (name, notes, custom fields, subtasks, comments, downloaded attachment contents, fetched external resources, branch name)
- `workflow_choice` flag, if the operator passed `brainstorm` or `feature-dev`

When invoked standalone, build the context from the conversation and repository state; ask the operator for whatever essential context is missing.

## Step 1: Detect a Plan

Check the documents available in the context (e.g. fetched task attachments). `implementation-plan.md` is the canonical name — if present, it is the plan. Otherwise, judge the remaining documents by content: any that reads as an implementation plan (ordered steps, affected files/modules, migration notes, test strategy) counts, regardless of its name. Decide autonomously — do not ask the operator. Who produced the plan does not matter. (See "Plan Artifact Convention" in the bindings reference.)

## Step 2: Pick the Entry Capability

**If `workflow_choice` is `brainstorm`** — enter at `CREATE_PLAN` with the `superpowers:brainstorming` binding (include the plan, if present, as prior design input).

**If `workflow_choice` is `feature-dev`** — use the `feature-dev:feature-dev` binding where the runtime offers it (`EXECUTE_PLAN` with the plan as input, or `CREATE_PLAN` when no plan exists). If the runtime has no feature-dev binding: plan present → `EXECUTE_PLAN`, no plan → `EXECUTE_INLINE`.

**Plan present** (no `workflow_choice`) — enter at `EXECUTE_PLAN`.

**No plan** (no `workflow_choice`) — ask (BLOCKING), flattening the runtime's `CREATE_PLAN` bindings into a single question — one option per binding, plus the inline option. E.g. under Claude Code:
> "How do you want to approach this?
> 1. Brainstorm the design first (`superpowers:brainstorming`)
> 2. Full development workflow (`feature-dev:feature-dev`)
> 3. Implement directly without a plan (`EXECUTE_INLINE`)"

Runtimes with a single `CREATE_PLAN` binding get two options. The chosen binding enters at `CREATE_PLAN`; the last option enters at `EXECUTE_INLINE`.

## Step 3: Resolve the Binding and Invoke

Resolve the chosen capability for the current runtime from the bindings table:

- **Multiple bindings in the cell** — ask the operator which one (BLOCKING), naming each binding and what choosing it means (per the table's footnotes). Skip the ask if the entry question (Step 2) already named the binding.
- **Single binding** — invoke it; inform the operator, no question needed.
- **`EXECUTE_INLINE`** — implement in the current session with native tools; any QA and shipping steps of the invoking workflow still apply.

**Chaining:** when `CREATE_PLAN` returns, judge by outcome: if a plan was produced but not yet implemented, enter `EXECUTE_PLAN` with the freshly produced plan — re-applying the resolution rules above. If the binding already carried through to implementation, do not chain.

When invoking `EXECUTE_PLAN`, pass the plan content (plus spec excerpts from the task notes) explicitly in the handoff — that capability executes plans, it does not write them.

## Step 4: Handoff Instruction

If invoked from a larger workflow, include with whatever skill is invoked:

> "When this workflow is complete, return to the workflow that invoked `implement-feature` so it can continue its remaining steps (e.g. QA verification, shipping). Do not end the session — there are more steps."

If standalone, instruct the downstream skill to report completion back in this session instead.

## Output

Implementation complete on the current branch. Return control to the invoking workflow — it owns whatever follows (QA verification, shipping). When standalone, report what was implemented and stop.
