# QA Routing Reference

Plugin-level shared reference used by `start-task` (to route QA during a task) and `pre-ship-check` (to gate shipping on QA verification). Covers how to resolve which QA skill to invoke and the QA investigate → fix → verify sub-flow.

**Scope note.** This file is a **how-to reference** — it documents the resolve logic and sub-step invocations. **Enforcement** — the exact operator prompts, the HARD GATE language, anti-patterns, and "must invoke not infer" rules — lives in the consuming skills' always-loaded context: `start-task/SKILL.md` Step 11 and `pre-ship-check/SKILL.md` Step 1. If you're tempted to substitute simpler-looking behavior at the invocation site, stop and re-read those Step sections; this file does not have the authority to relax their rules.

---

## Resolving the QA Skill

Determine which QA skill to invoke. Applies to **all task categories** — bugs use it for investigate/verify, non-bugs use it for completion verification.

Check in order:

1. **CLAUDE.md** — look for a `qa-skill:` declaration (e.g., `qa-skill: web-qa`, `qa-skill: mobile-qa`, or `qa-skill: none`). If found, use it.
2. **Project signals** — infer from project files:
   - `package.json` (without React Native), `vite.config.*`, `next.config.*` → `web-qa`
   - `.xcodeproj`, `.xcworkspace`, `Info.plist` → `mobile-qa`
   - `build.gradle`, `build.gradle.kts`, `AndroidManifest.xml` → `mobile-qa`
   - `app.json` / `app.config.js` with React Native/Expo → `mobile-qa`
   - No UI framework detected (pure backend, CLI, API, library, infrastructure) → `none`
3. **Ambiguous** — ask the operator (blocking):
   > "Which QA skill should I use?
   > 1. `web-qa` (browser-based, Chrome DevTools MCP)
   > 2. `mobile-qa` (simulator/emulator/device, mobile testing MCP)
   > 3. `none` (no visual UI to verify — backend, API, CLI, library)"

Reuse the resolved QA skill for all QA invocations in the task.

**If `none`:** for bug tasks, skip `QA: Investigate Bug` and `QA: Verify Fix` (no visual QA to run) but still run `QA: Fix Bug` with ticket-only context. For non-bug tasks, skip the `QA: Verify Non-Bug`.

---

## QA Sub-flow

The sub-flow runs after the development workflow completes and before ship-it. It is skipped entirely when `fast_mode` is active — fast mode implements inline without QA.

### QA: Resolve

Run the resolution logic above ("Resolving the QA Skill"). Record the result for the rest of the task.

**If the resolved skill is `none` and the task is non-bug:** skip straight to ship-it.

### QA: Investigate Bug

**Bug tasks only, when resolved skill != `none`.**

Invoke the resolved QA skill in **investigate** mode with:
- Bug description from the Asana ticket (as the question)
- SUT identifier (URL or app bundle ID, if known from CLAUDE.md or task notes)

Outcomes:
- **Confirmed** (bug reproduced with evidence) → QA skill posts the report to the Asana task. Proceed to `QA: Fix Bug`, passing the full report as context.
- **Cannot reproduce** → **stop**. Report to operator. Let them decide: fix SUT setup, clarify the bug description, or skip verification and proceed to debugging anyway.

### QA: Fix Bug

**Bug tasks only.**

Invoke `fix-bug` with the QA report from `QA: Investigate Bug` as enriched context (reproduction steps, evidence, root-cause analysis from runtime observation). If `QA: Investigate Bug` was skipped (resolved skill is `none`), invoke `fix-bug` with just the Asana ticket context.

`fix-bug` returns after root-cause investigation + TDD pass. It does **not** verify or ship — that is start-task's responsibility (`QA: Verify Fix` and the ship-it handoff).

### QA: Verify Fix (BLOCKING)

**Bug tasks only, when resolved skill != `none`. Cannot be skipped.**

After `fix-bug` returns, re-invoke the resolved QA skill in **verify** mode with the original reproduction steps from `QA: Investigate Bug`. The QA skill will rebuild, deploy, and replay the steps.

- **Pass** → QA skill posts `✅ QA Verification — PASSED` to Asana with evidence. Proceed to ship-it.
- **Fail** → QA skill posts `❌ QA Verification — FAILED` to Asana with evidence. Return to `QA: Fix Bug` for another debugging pass.

### QA: Verify Non-Bug

**Non-bug tasks only.** Bug tasks already have QA via `QA: Investigate Bug` + `QA: Verify Fix`.

**HARD GATE — always stop and wait for the operator's answer. Auto mode's "minimize interruptions" directive does NOT override this step.**

Skip asking only if the operator has already provided an explicit answer about QA in this session — e.g., passed `skip QA` in the start-task arguments, or said "skip QA" / "run QA" earlier in the conversation. Inferred triviality (small change, simple fix, XS sizing) is NOT a valid reason to skip.

After the development workflow signals completion, ask:

> "Implementation is complete. The changes can be visually verified before shipping — I'll build, deploy to the simulator/browser, and check the affected flows. A screenshot or video will be uploaded to the Asana task as proof of completion.
>
> Run QA verification? [yes / skip]"

Wait for the operator's answer before continuing.

If **yes** — resolve the QA skill if not already resolved (`QA: Resolve`) and invoke it with a summary of what was built/changed. The QA skill verifies the implementation, then posts `✅ QA Verification — Feature Complete` to Asana with evidence.

If **skip** — proceed to ship-it. `pre-ship-check` will offer one more chance if no QA evidence is found at ship time.

---

## Use by pre-ship-check

`pre-ship-check` uses the "Resolving the QA Skill" section above when its QA verification gate finds no QA evidence for a non-bug task and the operator chooses to run QA. Same logic, same order — no redefinition.
