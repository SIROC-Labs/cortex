---
name: fix-bug
version: 0.1.0
description: >
  Handles bug-fix investigation and testing when start-task routes a Bug category Asana task.
  Orchestrates root cause investigation (superpowers:systematic-debugging) and a TDD hard gate
  to prevent recurrence (superpowers:test-driven-development). Returns to start-task for
  QA verification and shipping. Always called from start-task; never invoked directly.
---

# Fix Bug

Focused orchestrator for bug investigation and fix. Contains no debugging or testing logic —
sequences two sub-skills with explicit gates, then returns to start-task for QA verification
and shipping. Always called from start-task, never directly.

## Inputs

Receives full task context from start-task:
- Task name, notes, custom fields (category, task ID, sprint)
- Subtasks (incomplete = remaining work, completed = done)
- Comments and attachments
- QA investigation report (from start-task's `QA: Investigate Bug`)
- Branch name (already created and checked out)
- Asana task URL

## Step 1: Root Cause Investigation

Invoke `superpowers:systematic-debugging` with the full task context as the bug report.

Do not proceed to Step 2 until systematic-debugging confirms both:
- Root cause identified with specificity (not "it was broken")
- Fix implemented on the current branch

## Step 2: TDD Hard Gate

**This step cannot be skipped under any circumstance.**

After systematic-debugging declares the fix ready, invoke `superpowers:test-driven-development`
with these explicit requirements:

1. **Write a regression test** that:
   - Would fail if the fix were reverted
   - Has a name that makes the bug recognizable (e.g., `test_session_expiry_uses_utc_not_local`)

2. **Run the full test suite.** All three must be true before completing:
   - The new regression test passes
   - No previously-passing tests are now failing
   - Any pre-existing failures are documented as pre-existing

**If the gate cannot be satisfied** (tests stay red, no meaningful test can be written):
- Do NOT return to start-task
- Return to `superpowers:systematic-debugging` Phase 1 — the fix is not considered complete
- If the gate still cannot be satisfied after a second pass, halt and surface the blocker
  to the user with a summary of what was attempted

## Output

When both steps pass, return to start-task with:
- Summary of root cause and fix (from systematic-debugging)
- Regression test name and file path
- Test run output confirming all green

Start-task handles QA verification (`QA: Verify Fix`) and shipping (Step 12) from here.
