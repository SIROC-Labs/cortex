# Sprint-Readiness Validation Rules

Four checks determine whether a task is ready to start. The intent is constant across providers: **do not start work that isn't ready.**

## Run the verdict (code-enforced)

Do **not** reason over the task JSON or apply the checks by hand. Run the neutral seam's readiness script — it resolves the active provider, fetches the data via that provider's primitives (`task get` + `board resolve active-sprint`), and applies siroc's gate policy deterministically:

```
${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/task-manager/scripts/readiness.py check --url <task-url> <task-ref>
```

It prints a verdict JSON and exits `0` whenever a verdict was produced (a non-`ready` verdict is **not** an error — it is the answer); non-zero only on a hard error (provider unresolved, fetch failed). The verdict shape:

```json
{ "ready": true,
  "checks": [
    {"name":"active_sprint","result":"pass|fail","blocking":true,"detail":"…"},
    {"name":"estimate","result":"pass|fail","blocking":true,"detail":"…"},
    {"name":"status","result":"pass|fail","blocking":true,"detail":"…"},
    {"name":"task_key","result":"pass|fail|skip","blocking":false,"detail":"…"}
  ] }
```

`ready` is `true` only when **active_sprint passes, estimate passes, and the status is a not-yet-started state**. Present the verdict to the operator as the checklist below, then branch on it.

## Branching on the verdict

- **`status` pass** → the task is in a not-yet-started state → proceed.
- **`status` fail** (blocking) → the task is **not** in a not-yet-started state (it's active, near-complete like `Ready`, or closed). It is not a fresh-start candidate; offer to move it into the start state (e.g. Product Status `Assigned`) via the task-manager interface, exactly as the original gate did (it required `Product Status == "Assigned"` and offered to set it). The gate does not sub-classify *why* it isn't startable.
- **`active_sprint` fail** (blocking, non-negotiable) → the task is only in an old/completed sprint or no sprint; it must be pulled into the current active sprint **manually** — it cannot be set via the task-manager interface. There is no skip for this.
- **`estimate` fail** (blocking) → offer to set the Estimate field via the task-manager interface:
  > No estimate set — how long do you estimate?
- **`task_key`** (non-blocking, provider-conditional) → `skip` when the provider supplies a native task key — nothing to do. `fail` (provider with no native key, and no `XXX-123` ID-pattern field set) → warn once about traceability, then proceed if the operator opts to skip. **Do not try to set the key through this gate** — the task key may be **provider-managed and read-only** (a provider can auto-assign it and reject writes); if it's genuinely needed it's resolved in the task manager out of band, not by the readiness step. (How a provider manages its key is the provider's concern.)

The provider owns *how* each datum is realized — `readiness.py` composes the provider's `task get` / `board resolve` primitives, so the workflow stays provider-agnostic.

## Failure Display Format

Separate blocking failures from skippable ones. Present them distinctly:

**If any blocking check fails (Active sprint membership, Estimate, Not-yet-started state):**
```
Sprint-Readiness Checks:
- [x] Active sprint membership — the active sprint
- [ ] Estimate — Not set (REQUIRED)
- [ ] Status — "Ready" (needs a not-yet-started state) (REQUIRED)
- [x] Has key: MT251-12

Some required checks did not pass. Want me to resolve them?
```

For active sprint membership: the task must be added to the active sprint manually — it cannot be set via the task-manager interface.
For Estimate: prompt for the estimate, then set it via the task-manager interface.
For the status: offer to set it to the start state (e.g. `Assigned`) via the task-manager interface.

Do not proceed until all blocking checks pass.

**If only the key / ID field fails (skippable, and only for providers without an intrinsic key):**
```
Sprint-Readiness Checks:
- [x] Active sprint membership — the active sprint
- [x] Estimate — 3h
- [x] State — Assigned
- [ ] ID field — Not set

ID is missing. Skip and continue? (The key may be provider-managed — auto-assigned or set out of band in the task manager — not written by this gate.)
```

Warn once about traceability risks, then proceed if skipped.

## Skip Rules

**Active sprint membership, Estimate, Not-yet-started status** — never skippable. Block the workflow. Offer to set Estimate via the task-manager interface and to set the status to the start state (e.g. `Assigned`), but do not proceed until all three are resolved.

**Task key / ID field** — skipped entirely when the provider has an intrinsic key. Otherwise, if the intent is to skip ("just start", "I'll fix the task manager later"), warn once about traceability risks, then proceed.
