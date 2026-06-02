---
name: log-task
description: >
  Use when the user wants to create a new Asana task from the current conversation — before
  or after doing the work. Triggers: "log this as a task", "create an Asana ticket for this",
  "capture this in Asana", "I want to track this", "let's create a ticket for what we just found",
  "add this to the backlog", "log this bug", "create a task before we start", "quick asana ticket",
  "log this to asana", "asana task for this", or after discovering and fixing an issue together.
  Do NOT trigger on generic logging requests ("log this error", "console.log", "log to Sentry")
  or on requests that reference an existing Asana task URL (those go to start-task or ship-it).
argument-hint: "[sprint: <sprint-url>] [backlog: <backlog-url>]"
---

# Log Task

Take something discovered or completed in conversation and formalize it as an Asana task — then route to the right next step. This skill bridges unplanned work (bugs spotted, issues found, ad-hoc fixes) into the tracked development workflow.

## Prerequisites

- `asana-api` skill for all Asana API operations — route all Asana API calls through it, no raw curl.
- `start-task` and `ship-it` skills available for routing.

---

## Step 0: Parse Arguments for URL Overrides

Before doing anything else, scan `$ARGUMENTS` and the triggering message for Asana project URLs.

Extract GIDs from URLs using the pattern `app.asana.com/0/(\d+)` — the GID is the first path segment after `/0/`.

**Disambiguate sprint vs backlog** using context words near each URL:

| Trigger words (case-insensitive) | Detected as |
|---|---|
| "sprint", "current sprint", "new sprint", "use sprint" | sprint override |
| "backlog", "product backlog", "use backlog", "new backlog" | backlog override |
| No context words | ambiguous — ask: "Is this the sprint board or a backlog board?" |

For each URL detected, resolve the project name and workspace GID via the API (see `references/board-config.md`). Store resolved overrides to merge into the board cache in Step 2.

Multiple backlog URL overrides are supported — each is added to the cache's `backlog_boards` list if not already present (matched by GID).

---

## Step 1: Determine the Variant

Infer from conversation context which of the two paths applies. Proceed silently — do not announce the inferred variant or ask for confirmation unless the signals are genuinely ambiguous.

**Plan Only**: Work has NOT been done yet. The user wants to create the Asana task first, then optionally start working on it.
> Signals: "I want to plan this", "let me log it before we start", "we just figured out what needs to be done", task is still an idea.

**Fix Done**: Work IS already done (or substantially done) in this session. The user wants to create the task retroactively.
> Signals: "we just fixed it", "I already implemented this", "log what we just did", session has meaningful git changes or file edits.

When confident, announce the inferred variant and proceed immediately — do not wait:
- Plan Only: > "Treating this as a plan-only task — I'll create the Asana task and ask if you want to start work after."
- Fix Done: > "Treating this as a completed fix — I'll create the Asana task and set up a branch for shipping."

**If genuinely ambiguous** (no clear signals either way), ask and wait:
> "Is the work already done, or are you planning to start after logging? [done/plan]"

---

## Step 2: Load Board Config

Load the board registry cache following `references/board-config.md`, which delegates to the shared `board-resolution.md` module.

1. Load cache from `~/.claude/asana-workflow/<project-key>.json`
2. If cache missing → Full Discovery runs automatically (queries workspace, classifies all boards, writes cache)
3. If cache exists → sprint freshness check runs automatically (refreshes if `due_on` is past)
4. Merge any URL overrides from Step 0 (see `references/board-config.md` for merge rules)

After loading, you have:
- `active_sprint` — the current sprint board (GID + name)
- `backlog_boards` — all available backlog boards (GID + name each)
- `workspace_gid` — for task creation
- `asana_token_env` — the env var name for the Asana token

---

## Step 3: Discover Custom Fields

Read **`plugins/asana-workflow/references/asana-custom-field-discovery.md`** for field name matching patterns, the discovery API call, and how to record GIDs. Also read `references/asana-api-calls.md` for the current user fetch.

---

## Step 4: Gather Task Details and Pick Defaults

Extract from conversation context as much as possible. Fill gaps with smart defaults:

| Field | Default | Notes |
|-------|---------|-------|
| **Title** | Summarize in ≤ 72 chars | From conversation; make it specific |
| **Description** | Summary of issue/fix/plan | Include root cause if known |
| **Priority** | Highest urgency option | Match semantically: prefer names containing "0", "critical", or "urgent"; or the option with the lowest numeric suffix (P0 < P1 < P2). Fall back to first in list only if no semantic match. |
| **Sizing** | Lowest available option | e.g., XS, 1, S — if Fix Done, use session scope as proxy |
| **Estimate** | Plan Only: blank. Fix Done: `00:00` | See Estimate rules below |
| **Assignee** | Current user (Fix Done) / Unassigned (Plan Only) | |
| **Product Status** | "Assigned" enum option | Match case-insensitively |

**Sizing scale** (assumes a 5-step scale ordered smallest → largest, e.g. XS/S/M/L/XL): 1st = ≤ 8h (1 day), 2nd = ≤ 16h (2 days), 3rd = ≤ 40h (5 days / 1 week), 4th = ≤ 80h (10 days / 2 weeks), 5th = > 80h. Match by position, not name. If the project's scale isn't 5-step, fall back to "err toward smaller."

**Sizing for Fix Done**: estimate session effort in hours and pick the smallest position that fits. Err toward smaller.

**Estimate rules**:
- **Plan Only**: leave the Estimate blank. Do not pick a default.
- **Fix Done**: default to `00:00`. The work is already completed without an estimate.

**Time format**: Always display and submit estimate values in `hh:mm` format (e.g., `00:00`, `00:30`, `01:00`). Never use shorthand like `30m`, `1h`, `1d`.

**Priority**: Default to the highest urgency enum option using semantic matching — do not rely on list position. If the conversation describes something non-critical ("nice to have", "minor cleanup"), drop to a mid-level option instead.

---

## Step 5: Present Full Draft for Confirmation (REQUIRED)

Show everything before creating anything. The user must confirm. This step is non-negotiable.

```
Task draft:
  Title:          Fix null pointer in export pipeline when CSV is empty
  Description:    The CSV exporter crashes when the input DataFrame has zero
                  rows. Root cause: missing empty-check before column iteration.

  Boards:
    Sprint:    ENG | Sprint 26.16  (auto-detected)
    Backlogs:
      [x] ENG | Bugs & Issues  (matched: bug category)

    Confirm boards, or name other boards to add.

  Fields:
    Priority:       P0            [options: P0, P1, P2, P3]
    Sizing:         XS            [options: XS, S, M, L, XL]
    Estimate:       —             [options: 00:00, 00:30, 01:00, 02:00, 04:00] (Plan Only: blank; Fix Done: 00:00)
    Product Status: Assigned      [options: Assigned, In Progress, Done]
    Assignee:       Francisco Javier (you)

  Fields not found in this project: (none)

Create this task? [Y/n / type field name to edit]
```

If a field couldn't be discovered, show it as `— (not available in this project)`. If the user edits a field, update the draft and show it again. Do not create until explicit confirmation.

---

## Step 6: Create the Task

Read `references/asana-api-calls.md` for all curl commands. Execute in this order — do not skip or reorder:

1. **6a** — Create the task (workspace + assignee only, no custom fields)
2. **6b** — Add to the active sprint project
3. **6c** — Add to each user-confirmed backlog board (loop — one `addProject` call per board)
4. **6d** — Set custom fields via PUT (now that the task is in a project)
5. **6d cont** — Fetch the auto-assigned task ID (retry up to 3 times, 10s apart). If still absent after all retries, derive a prefix from context:
   - Bug fix → `fix/<slug>`, Feature → `feat/<slug>`, Tech debt → `chore/<slug>`, Docs → `docs/<slug>`

Report success:
```
✓ Task created: Fix null pointer in export pipeline when CSV is empty
  ID:      MT251-182
  Asana:   https://app.asana.com/0/<active_sprint_gid>/<task_gid>
  Sprint:  ENG | Sprint 26.16
  Boards:  ENG | Bugs & Issues, ENG | MT251 :: Mobile Toolkit
```

**Error handling:**
- Never silently fail an API call — report status code and error.
- If task creation succeeds but adding to a project fails, do not roll back. Report the task URL so the user can add it manually.
- If custom field GIDs can't be resolved, create the task without those fields and list what's missing.

---

## Step 7: Route to the Next Step

### Plan Only

Ask the user whether to proceed:

> "Task logged. Want to start work on it now, or leave it for later? [start/later]"

**Wait for the user's response.**

- If start → invoke `start-task` with `$ARGUMENTS = https://app.asana.com/0/<active_sprint_gid>/<task_gid>`.
- If later (or any non-committal response) → stop here. The user can start later with `/start-task <url>`.

---

### Fix Done: Worktree + Ship

Read `references/worktree-flow.md` for all git commands.

#### 7b-1. Identify what changed
Run the git diff commands from `references/worktree-flow.md`. If `<changed_files>` is empty, stop and ask the user where the changes are before continuing.

#### 7b-2. Ask before touching git

> "Task logged. Want to create a branch and ship now, or leave it for later? [ship/later]"

**Wait for the user's response.**

- If later (or any non-committal response) → stop here. The user can run `/ship-it` whenever ready.
- If ship → continue to 7b-3.

#### 7b-3. Determine the branch name

```
<task_id>/<slug>
# e.g., MT251-182/fix-csv-export-null-crash
```

`<slug>` = task title lowercased, spaces to hyphens, max 40 chars, alphanumeric and hyphens only. If no task ID was resolved, use the type prefix (`fix/`, `feat/`, `chore/`, `docs/`) + slug.

#### 7b-4 & 7b-5. Create worktree and copy changes
Follow the worktree creation and file copy steps in `references/worktree-flow.md`.

#### 7b-6. Invoke ship-it

Thread the full Asana task context so `ship-it` / `create-pr` can skip re-asking and build the correct PR title (`<TASK-ID> :: <description>`):
- Task GID: `<task_gid>`
- Task URL: `https://app.asana.com/0/<active_sprint_gid>/<task_gid>`
- Task ID: `<task_id>` — the project ID prefix (e.g., `MT251-182`) resolved in Step 6d; required for PR title formatting
- Task title: `<task_title>` — used as the PR title description
- Sprint project GID: `<active_sprint_gid>`
- Branch name: `<task_id>/<slug>` — already created in 7b-3

If the task ID could not be resolved in Step 6d (all retries failed), explicitly tell `ship-it` that the PR title must fall back to the type-prefixed branch slug (`fix/…`, `feat/…`) with no `TASK-ID :: ` prefix — do not let `create-pr` guess.

---

## Step 8: Harvest Reminder

> "Don't forget to move any Harvest time logged for this work to **<task_id>: <task_title>**."

Do not attempt to interact with Harvest directly — this step is advisory only.
