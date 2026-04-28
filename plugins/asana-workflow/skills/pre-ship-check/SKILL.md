---
name: pre-ship-check
version: 0.1.0
description: >
  This skill should be used when the user says "am I ready to ship", "pre-flight check",
  "check before PR", "ready to merge", "pre-ship check", "can I ship this", "is this ready",
  or "run checks". Validates that code is in a shippable state: enforces the QA verification
  gate (blocks bugs without verification, prompts the operator on non-bug tasks without
  verification), runs git-check for branch and working tree validation, then verifies lint,
  build, and tests pass. Works standalone or as the first step in the ship-it orchestrator.
---

# Pre-Ship Check

Readiness gate that validates code is in a shippable state. Combines git state validation (via `git-check`) with project-level build verification.

## Usage Modes

- **Standalone** — The user asks "am I ready to ship?" and wants a full status report.
- **Orchestrator step** — Called by `ship-it` as its first step. Blocking findings halt the pipeline.

## Flow-Completeness Rule

**All four steps must run unless a BLOCKING step stops the flow.** Passing a gate (Step 1) means "this gate passes" — it does **not** mean "pre-ship-check is done." After any step that passes (including long-running ones like the QA skill invocation in Step 1d Yes), always proceed to the next numbered step. pre-ship-check's final report (see Output Format) is only emitted after Step 4 — if you find yourself about to return control without producing that report, you have skipped a step.

## Step 1: QA Verification Gate

**Only applies when a task GID is in context. Skip when no task GID is available.**

**1a. Check context first** — if a `✅ QA Verification` comment was posted in this session, the gate passes. Skip to Step 2.

**1b. Fetch task stories** (via `asana-api`) and search for any comment containing `✅ QA Verification`. A `❌ QA Verification — FAILED` comment does **not** pass the gate.

- **Found** → gate passes. Proceed to Step 2.
- **Not found** → continue to 1c.

**1c. Check QA skill resolution** — if the QA skill resolved to `none` in this session (backend, API, CLI, or library work with no visual UI), the gate passes. Skip to Step 2.

**1d. Determine task category** — check conversation context for the task's Category field. If not in context, fetch the task details (via `asana-api` Fetch Task Details) to read the Category custom field.

- **Bug** → **BLOCKING**. Report:
  > QA verification has not passed for this bug task. The fix must be verified via the QA skill before shipping.
  >
  > This gate cannot be overridden. A bug fix without runtime verification evidence is not shippable.

- **Non-bug** (Feature Request, Tech Debt, etc.) → **INTERACTIVE GATE**. Skip the prompt only if the operator's answer earlier in this session was a **direct response** to the QA verification prompt — either the start-task `QA: Verify Non-Bug` prompt ("Run QA verification? [yes / skip]") or this step's own prompt — OR a literal `skip QA` / `run QA` utterance at any point. An affirmative response to a different question (e.g., ship approval, a generic checklist, "does this look good?") does **NOT** count as an answer to the QA question. When the prior answer is ambiguous, re-ask.

  Otherwise, **always stop and ask the operator. Auto mode's "minimize interruptions" directive does NOT override this step. Inferred triviality is NOT a valid reason to skip asking. Do not generate a static self-certification checklist in place of this prompt.**

  > "No QA verification found for this task. Visually verify the changes before shipping?
  > I'll build, deploy to the simulator/browser, and check the affected flows. A screenshot or video will be uploaded to the Asana task as proof of completion.
  > - **Yes** — run QA verification now
  > - **Skip** — proceed without QA"

  Wait for the operator's answer before continuing.

  - If **Yes** → resolve the QA skill per `plugins/asana-workflow/references/qa-routing.md` ("Resolving the QA Skill") and invoke it with a summary of what was built/changed (from git diff/log). The QA skill posts `✅ QA Verification — Feature Complete` to Asana with evidence. Gate passes — **proceed to Step 2**. pre-ship-check is not complete until Steps 2–4 have also run.
  - If **Skip** → operator has explicitly acknowledged the absence. Gate passes with a note for the final report: `QA skipped by operator` — **proceed to Step 2**. pre-ship-check is not complete until Steps 2–4 have also run.

## Step 2: Git State Validation

Invoke `git-check`. If it returns blocking issues, stop and resolve them before continuing. Advisory warnings are presented to the user to decide whether to proceed.

## Step 3: Resolve Project Commands

Scan CI pipelines to infer test, build, and lint commands (see below), then confirm with the user before running.

### CI Pipeline Inference

When commands are missing, scan for CI pipeline files in this order:
1. `.github/workflows/*.yml` / `.yaml` — look for steps with `run:` containing test/build/lint keywords
2. `.circleci/config.yml` — look for job steps
3. `Makefile` — look for targets named `test`, `build`, `lint`, `check`
4. `package.json` `scripts` — look for keys matching `test`, `build`, `lint`
5. `Taskfile.yml` / `justfile` — look for matching tasks

Extract the most specific matching command for each of `test`, `build`, `lint`. Then present inferred commands to the user for confirmation before running:

> I found these commands from your CI pipeline — confirm or edit before I run them:
> - lint: `yarn lint`
> - build: `yarn build`
> - test: `yarn test`
>
> Proceed with these? (You can skip any.)

If no commands can be inferred for a given check after scanning all sources, mark that check as **SKIPPED (not configured)** — not blocking.

## Step 4: Run Project Commands

Run in this order (cheapest first):

| # | Command | Severity | Notes |
|---|---|---|---|
| 1 | Lint (declared or inferred `lint` command) | ADVISORY | Warn but don't block |
| 2 | Build (declared or inferred `build` command) | BLOCKING | Stop if fails |
| 3 | Tests (declared or inferred `test` command) | BLOCKING | Ask before running (may be slow) |

Before running the test suite, ask:

> The test suite may take a while. Run it now, or skip and mark as unchecked?

## Output Format

Combine findings from the QA gate (Step 1), git-check (Step 2), and project commands (Step 4) into a single report:

```
BLOCKING
  - Build failing: exit code 1

WARNINGS
  - Lint errors on changed files
  - Debug artifact: console.log found in src/utils/helper.ts (line 42)

PASSED
  - QA: verified (or "QA: skipped by operator" / "QA: not applicable (qa-skill=none)" / "QA: no task context")
  - Git checks passed
  - Tests passing
```

The QA row is **mandatory** in the PASSED section — it must explicitly state how Step 1 resolved (verified in this session, skipped, n/a, or no task). A missing QA row is a signal that Step 1 didn't run to completion.

Omit other sections that have no findings. If everything passes:

```
PASSED
  - QA: verified
  - All other checks passed. Ready to ship.
```

## Behavior Rules

1. **Blocking findings** — Stop and report. The user can override with explicit confirmation ("yes, ship anyway"), but make the risk clear.

2. **Advisory warnings only** — List them and ask: "These are non-blocking warnings. Continue anyway?"

3. **All checks pass** — Say so and proceed. No unnecessary friction.

4. **Long-running commands** — Ask before running test suites or builds that may take more than a few seconds. Let the user skip if they've already run them recently.

5. **Error handling** — Never silently skip a check. If a command fails unexpectedly (e.g., command not found), report the failure explicitly and note that the check could not be completed.
