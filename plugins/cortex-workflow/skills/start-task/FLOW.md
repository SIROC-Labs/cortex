# `start-task` — Complete Flow Reference

Usage: `/start-task <url> [brainstorm | feature-dev | fast]`

## Legend

| Symbol | Meaning |
|:---:|---|
| `┌──────┐` / `└──────┘` | action / step |
| `◆` | decision point |
| `▼` | flow direction |
| `■` | terminal state |
| `↺` | loop back |
| `[A]` | jump connector |
| `··` | skips steps (shortcut) |

## Checkpointing

Every run writes to `~/.cortex/cortex-workflow/checkpoints/<task-ref>.md` via `plugins/cortex-workflow/skills/start-task/scripts/checkpoint.sh`. All numbered steps must be recorded — see `references/checkpoints.md` for the full protocol.

## Pause Flow

Fires at any point during the session.

**Trigger phrases:** "park this" · "I'm blocked" · "pause task" · "put this on hold" · "waiting on X" · "blocked by X" · "save my progress" · "need to wait for an answer" · "come back to this later" · "pick this up later"

**Steps:**

1. Verify current branch matches task (warn if merge in progress)
2. `git add -A && git commit` → `WIP: <task-id> — blocked on [reason]`
3. Draft blocking question → **USER MUST APPROVE** wording before posting
4. Post a comment via the task manager (`add_comment`, with @mention of blocker)
5. `checkpoint.sh block <task-ref> <step> <reason>` then `checkpoint.sh append-note <task-ref> <blocking-question + who-to-follow-up-with>`
6. `git push` WIP branch
7. Confirm: commit hash · task comment link · checkpoint path

Task stays **"In Progress"** → ■ PAUSED

## Main Flow

`$ARGUMENTS` is parsed once up front into named flags: **`fast_mode`**, **`workflow_choice`** (`brainstorm` / `feature-dev`). Steps 0–10 and Step 12 run in every mode; only Step 11 changes (skipped when `fast_mode`; every QA row → `State=skipped`).

### Init / Resume (before Step 0)

```
             ┌────────────────────────────────────────────┐
             │  INIT / RESUME  (before Step 0)            │
             │  ls ~/.cortex/cortex-workflow/checkpoints/  │
             │     <task-ref>.md                          │
             └───────────────────┬────────────────────────┘
                                 │
                        ◆ checkpoint exists?
                       ╱                     ╲
                     YES                      NO
                      │                        │
                RESUME FLOW              checkpoint.sh init <task-ref> <url>
                      │                        │
              ┌───────┴────────┐               │
              │ find first     │               │
              │ non-terminal   │               │
              │ row:           │               │
              │   Completed    │               │
              │   != [x] AND   │               │
              │   State !=     │               │
              │   skipped      │               │
              │                │               │
              │ verify branch, │               │
              │ check task     │               │
              │ status, fetch  │               │
              │ new task       │               │
              │ comments since │               │
              │ last_updated   │               │
              │ if row=blocked │               │
              │                │               │
              │ post resume    │               │
              │ comment if     │               │
              │ previous state │               │
              │ was blocked    │               │
              └───────┬────────┘               │
                      │                        │
             ·· [A] SKIP to first              │
                non-terminal step ··           │
                      │                        │
                      └──────────────┬─────────┘
                                     │
```

### Steps 0 – 8

```
                                     │
                                     ▼
             ┌────────────────────────────────────────────┐
             │  0 · Skill Dependencies  (mandatory)       │
             │  Claude: feature-dev + superpowers         │
             │  OpenCode/Codex: superpowers + MCPs        │
             └───────────────────┬────────────────────────┘
                                 │
                            ◆ installed?
                           ╱             ╲
                         NO               YES
                          │                │
                    block + setup          │
                    rerun start-task       │
                          │                │
                          └─────X          │
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  1 · Get Task URL                          │
             │  parse $ARGUMENTS → extract task ref       │
             └───────────────────┬────────────────────────┘
                                 │
                            ◆ valid URL?
                           ╱           ╲
                         NO             YES
                          │              │
                        prompt           │
                          └─────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  2 · Fetch Task Details                    │
             │  name · category · sprint · assignee       │
             │  fields · notes · memberships              │
             │  → print summary                           │
             │  checkpoint.sh set <task-ref> task_id      │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  2a · Validate Assignee                    │
             │  get_current_user() → current user         │
             └───────────────────┬────────────────────────┘
                                 │
                        ◆ task.assignee?
                       ╱         │          ╲
                  null        current       other
                   │           user          user
                   │             │             │
              auto-assign        │         ask (BLOCKING):
              → inform           │         "Reassign to you?"
                   │             │          ╱        ╲
                   │             │         YES        NO
                   │             │          │          │
                   │             │     reassign     ■ STOP
                   │             │     via interface
                   └─────────────┴──────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  3 · Validate Sprint-Readiness             │
             │     (readiness.py check → verdict JSON)    │
             │                                            │
             │  ◻ active_sprint        BLOCKING           │
             │  ◻ estimate             BLOCKING  → fix    │
             │  ◻ status               BLOCKING  → fix    │
             │       not-yet-started → go;                │
             │       else → set start state (Assigned)    │
             │  ◻ task_key           WARN/skip (per prov) │
             └───────────────────┬────────────────────────┘
                                 │
                            ◆ all blocking pass?
                           ╱                   ╲
                         NO                     YES
                          │                      │
                   report checklist              │
                   offer fix                 │
                          ↺────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  4 · Fetch Subtasks                        │
             │  group: incomplete (remaining) / done      │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  5 · Fetch Comments & Attachments          │
             │  filter stories → comments                 │
             │  list attachments; download non-image      │
             │  (e.g., implementation-plan.md)            │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  6 · Check for Existing Work               │
             │  git fetch --prune                         │
             │  check branches + open PRs by task ID      │
             └───────────────────┬────────────────────────┘
                                 │
                        ◆ branch / PR exists?
                       ╱                     ╲
                     YES                      NO
                      │                        │
             offer: resume / fresh             │
                 ╱          ╲                 │
            RESUME          FRESH             │
                │              └──────────────┤
         checkout                             │
         existing branch                      │
                │                             │
                ▼                             ▼
             ┌────────────────────────────────────────────┐
             │  6a · Worktree? (BLOCKING)                 │
             │  worktree (isolated) or current dir        │
             └───────────────────┬────────────────────────┘
                                 │
                            ◆ worktree?
                           ╱             ╲
                         YES              NO
                          │                │
                    create worktree        │
                          └───────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  6b · Base Branch? (BLOCKING)              │
             │  main (default) or specify other           │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  7 · Create Feature Branch                 │
             │  <task-id>/<slug>  off base branch         │
             │  inform only — no question                 │
             │  checkpoint.sh set <task-ref> branch/base  │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  8 · Create Draft PR                       │
             │  empty commit → push branch                │
             │  gh pr create --draft                      │
             │  capture PR URL (threaded to ship-it)      │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
```

### Steps 9a – 9b

```
             ┌────────────────────────────────────────────┐
             │  9a · Move to In Progress                  │
             │  set_status(task, "In Progress")           │
             │  if move fails: report, do not block       │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
             ┌────────────────────────────────────────────┐
             │  9b · Post Start Comment                   │
             │  post 🏁 start comment (deduplicate)       │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
```

## Step 10 — Route to Workflow

```
                         ◆ fast_mode?
                        ╱             ╲
                      YES              NO
                       │                │
             ┌─────────┴──────────┐     │
             │  implement inline   │    │
             │  Read · Edit · Bash │    │
             │  no skill invoked   │    │
             │                     │    │
             │  Step 11 (QA):      │    │
             │  checkpoint.sh skip │    │
             │  every QA row with  │    │
             │  reason "fast mode" │    │
             └─────────┬──────────┘     │
                       │                ▼
                       │           ◆ Category?
                       │         ╱     │     ╲
                       │       Bug  Non-bug  missing
                       │        │     │        │
                       │        │     │    ask: bug or non-bug?
                       │        │     │        │
                       │        │     └────┬───┘
                       │        │          │
                       │        │   ┌──────┴────────────────┐
                       │        │   │  implement-feature    │
                       │        │   │  detect plan file →   │
                       │        │   │  resolve binding via  │
                       │        │   │  runtime-bindings.md  │
                       │        │   │  (asks operator when  │
                       │        │   │  several apply;       │
                       │        │   │  workflow_choice      │
                       │        │   │  pre-answers)         │
                       │        │   └──────┬────────────────┘
                       │        │          │
                       │        │     (development skill returns to Step 11)
                       │        │                │
                       │        └────── bug path to Step 11 (QA)
                       │                         │
                       │                         ▼
                       │          ┌──── Step 11 ────┐
                       │          │  QA SUB-FLOW    │
                       │          │  (below)        │
                       │          └────────┬────────┘
                       │                   │
                       └─────────┬─────────┘
                                 │
                                 ▼
                        (to Step 12 · Ship It)
```

## Step 11 — QA Sub-flow

Details in `plugins/cortex-workflow/references/qa-routing.md`. Skipped entirely when `fast_mode` (every row → `State=skipped`).

```
             ┌────────────────────────────────────────────┐
             │  QA: Resolve                               │
             │                                            │
             │  1. CLAUDE.md  qa-skill: declaration       │
             │  2. project signals:                       │
             │     package.json (no React Native) /       │
             │     vite.config / next.config → web-qa     │
             │     .xcodeproj / .xcworkspace /            │
             │     Info.plist / build.gradle /            │
             │     build.gradle.kts /                     │
             │     AndroidManifest.xml     → mobile-qa    │
             │     app.json / app.config.js               │
             │     + React Native / Expo   → mobile-qa    │
             │     FastAPI / Express / Spring /           │
             │     openapi.json, API only  → backend-qa   │
             │     no served surface       → none         │
             │  3. ambiguous → ask: web-qa /              │
             │     mobile-qa / backend-qa / none          │
             └───────────────────┬────────────────────────┘
                                 │
                     ◆ resolved skill == none
                       AND non-bug task?
                    ╱                       ╲
                  YES                       NO
                   │                         │
             skip to Step 12                 │
             (nothing to verify)             │
                                             ▼
                                       ◆ Category?
                                     ╱              ╲
                                   Bug            Non-bug
                                    │                │
                                    ▼                │
             ┌───────────────────────────────────┐   │
             │  QA: Investigate Bug              │   │
             │  (skip if skill == none)          │   │
             │  QA skill: investigate mode       │   │
             │  input: bug description + SUT     │   │
             └──────────────┬────────────────────┘   │
                            │                        │
                      ◆ reproduced?                  │
                     ╱               ╲               │
               CONFIRMED          CANNOT REPRODUCE   │
                    │                   │            │
           post QA report to       operator decides: │
           the task                 · fix SUT        │
                    │               · clarify        │
                    │                    → ■ STOP    │
                    │               · skip verify,   │
                    │                 proceed        │
                    │                                │
                    ▼                                │
             ┌───────────────────────────────────┐   │
             │  QA: Fix Bug                      │   │
             │  invoke fix-bug skill             │   │
             │  pass QA report as context        │   │
             └──────────────┬────────────────────┘   │
                            │                        │
                            ▼                        │
             ┌───────────────────────────────────┐   │
             │  QA: Verify Fix  (BLOCKING)       │   │
             │  (skip if skill == none)          │   │
             │  QA skill: verify mode            │   │
             │  input: repro steps from earlier  │   │
             └──────────────┬────────────────────┘   │
                            │                        │
                       ◆ fixed?                      │
                      ╱          ╲                   │
                    PASS         FAIL                │
                     │             │                 │
                     │        ↺ loop back            │
                     │        to QA: Fix Bug         │
                     │                               │
                     └────────────┬──────────────────┘
                                  │
                     (to Step 12 · Ship It)
                                  │
                                  ▼
             ┌───────────────────────────────────┐
             │  QA: Verify Non-Bug  (HARD GATE)  │
             │  asked after development completes│
             │                                   │
             │  "Implementation complete.        │
             │   Run QA verification? [yes/skip]"│
             └──────────────┬────────────────────┘
                            │
                       ◆ operator?
                      ╱              ╲
                    YES              SKIP
                     │                 │
            QA skill: verify       proceed to
            mode. Posts            Step 12 (ship-it
            ✅ QA Feature          → pre-ship-check
            Complete to            will offer one
            the task               more chance)
                     │                 │
                     └────────┬────────┘
                              │
                   (to Step 12 · Ship It)
```

## Step 12 — Ship It

```
             ┌────────────────────────────────────────────┐
             │  12 · Ship It                              │
             │  triggers: QA sub-flow completes / skipped │
             │  or fast mode direct to ship               │
             │  do not wait for user to ask               │
             │                                            │
             │  pre-ship-check  (owns QA gate)            │
             │    · Step 1d: QA verification              │
             │      (prompts operator if no QA evidence   │
             │       for non-bug tasks)                   │
             │    · git state + lint + build + tests      │
             │  work-summary                              │
             │  promote draft PR → ready                  │
             │  move task → "In Review"                   │
             │  post completion comment                   │
             │                                            │
             │  on success:                               │
             │  checkpoint.sh delete <task-ref>           │
             └───────────────────┬────────────────────────┘
                                 │
                                 ▼
                              ■ DONE
```
