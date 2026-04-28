# Checkpoints Reference

Every `start-task` run tracks progress in a checkpoint file so work can be paused and resumed without losing context. The checkpoint is initialized on entry, updated around every step, and deleted after a successful ship.

**All writes go through the helper script** at `${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh` (equivalently `plugins/asana-workflow/skills/start-task/scripts/checkpoint.sh` when the plugin is local). Do not use Edit/Write on checkpoint files directly — the script keeps the format consistent and minimizes conversation noise (one short Bash command per update instead of a full diff). The file format below still applies; the script produces exactly this layout.

---

## File Location

**Path:** `~/.claude/asana-workflow/checkpoints/<task-gid>.md`

The task GID (numeric) comes from the URL — available before any API call. The script creates the directory on first use.

**Never overwrite an existing checkpoint on initialization.** If the file exists, work was already started — load it and resume.

---

## File Format

A checkpoint has frontmatter, a `## Steps` table, and a `## Notes` section.

### Frontmatter Fields

| Field | Description |
|-------|-------------|
| `task_gid` | Asana task GID (numeric, from URL) |
| `task_id` | Project ID custom field (e.g., `MT251-47`) — filled in after Step 2 |
| `asana_url` | Full Asana task URL |
| `branch` | Feature branch name — filled in after Step 7 |
| `base_branch` | Branch the feature branch was created from — filled in after Step 7 |
| `workflow` | `fix-bug`, `brainstorm`, `feature-dev`, or `fast` — filled in after Step 10 |
| `created_at` | ISO 8601 timestamp — set once on initialization |
| `last_updated` | ISO 8601 timestamp — updated after every step |

### Steps Table

Six-column markdown table tracking every step of the workflow.

| Column | Values | Description |
|--------|--------|-------------|
| **Step** | Text | Step number and name |
| **Completed** | `[ ]` / `[x]` | `[x]` only when `State = completed`; `[ ]` for every other state. Visual progress indicator. |
| **Comment** | Text | Key data captured or what happened |
| **Attempts** | Integer | How many times this step has been attempted (starts at 0) |
| **State** | `—` / `in_progress` / `completed` / `blocked` / `skipped` | Current execution state |
| **Auto** | `[ ]` / `[x]` | `[x]` if completed without user input; `[ ]` if user approval was required |

### Template (New Checkpoint)

```markdown
---
task_gid: ""
task_id: ""
asana_url: ""
branch: ""
base_branch: ""
workflow: ""
created_at: "<iso8601>"
last_updated: "<iso8601>"
---

## Steps

| Step | Completed | Comment | Attempts | State | Auto |
|------|-----------|---------|----------|-------|------|
| 0. Dependency Check | [ ] | | 0 | — | [ ] |
| 1. Get Task URL | [ ] | | 0 | — | [x] |
| 2. Fetch Task Details | [ ] | | 0 | — | [x] |
| 3. Validate Sprint-Readiness | [ ] | | 0 | — | [ ] |
| 4. Fetch Subtasks | [ ] | | 0 | — | [x] |
| 5. Fetch Comments & Attachments | [ ] | | 0 | — | [x] |
| 6. Check Existing Work | [ ] | | 0 | — | [x] |
| 6a. Ask About Worktree | [ ] | | 0 | — | [ ] |
| 6b. Confirm Base Branch | [ ] | | 0 | — | [ ] |
| 7. Create Feature Branch | [ ] | | 0 | — | [x] |
| 8. Create Draft PR | [ ] | | 0 | — | [x] |
| 9a. Move to In Progress | [ ] | | 0 | — | [x] |
| 9b. Post Start Comment | [ ] | | 0 | — | [x] |
| 10. Route to Workflow | [ ] | | 0 | — | [ ] |
| QA: Resolve | [ ] | | 0 | — | [ ] |
| QA: Investigate Bug | [ ] | | 0 | — | [ ] |
| QA: Fix Bug | [ ] | | 0 | — | [x] |
| QA: Verify Fix | [ ] | | 0 | — | [ ] |
| QA: Verify Non-Bug | [ ] | | 0 | — | [ ] |
| 12. Ship It | [ ] | | 0 | — | [x] |

## Notes
```

The `QA:` rows are only exercised when their preconditions apply (bug vs non-bug, resolved QA skill != `none`, not in fast mode). Prefer marking non-applicable rows with `State = skipped` and a reason at the time they would have run, rather than leaving them as `State = —`.

---

## Initialization

**This is the very first action `start-task` takes** — before any Asana API call, before any git command.

1. **Extract task GID** from the URL in `$ARGUMENTS`. If no URL is provided, prompt for it now.

2. **Check for an existing checkpoint:**
   ```bash
   ls ~/.claude/asana-workflow/checkpoints/<task-gid>.md 2>/dev/null
   ```

3. **If checkpoint found** → this is a resume. Go to **Resume Flow** below.

4. **If no checkpoint** → create it via the helper:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh init <task-gid> <asana-url>
   ```
   The script creates `~/.claude/asana-workflow/checkpoints/` if needed and writes the template with `task_gid`, `asana_url`, `created_at`, `last_updated` pre-filled. No `.gitignore` entry is needed (the file lives outside the repo).

---

## Step Updates

**After every step, update the checkpoint immediately. This is not optional.** All updates go through the helper script — do not Edit/Write the file directly.

**Non-negotiable:** the script must be called for every numbered step in the flow, including trivial ones. If Step N didn't do anything observable (e.g., Step 1 when the URL was already in `$ARGUMENTS`), mark it complete with comment `trivial — already present` and `auto=yes`. Never leave a step as `[ ]` / `—` after advancing past it. A blank row is not "the step was implicit"; it is a checkpoint gap that will cause incorrect behavior on resume.

Abbreviate the helper path as `CP=${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh` mentally; the examples below use the full path for clarity.

### Update Pattern

When a step **starts** (`State → in_progress`, `Attempts += 1`, `last_updated` refreshed):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh start <gid> "<step>"
```

When a step **completes successfully** (`Completed → [x]`, `State → completed`, `Comment` set, `last_updated` refreshed). Add a 4th arg `no` if the step required operator input (so `Auto → [ ]`), else omit (defaults to `yes`):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh complete <gid> "<step>" "<comment>" [yes|no]
```

When a step is **blocked** (cannot complete — waiting on input, external dependency, or a failure that halts progress). Then proceed to **Pause Flow** below:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh block <gid> "<step>" "<reason>"
```

When a step does **not apply** in this run (wrong category, `qa-skill=none`, fast mode, operator opted out). `Completed → [ ]`, `State → skipped`, `Comment → reason`:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh skip <gid> "<step>" "<reason>"
```

A skipped row is terminal. Resume skips over it the same as `[x]`/completed rows.

**Revising a completed step.** Calling `complete` on an already-completed row overwrites it and increments `Attempts` (providing an audit trail). Use this when the operator revises a decision mid-flow — e.g., at Step 10 they pick `brainstorm`, interrupt the sub-skill, and switch to `feature-dev`. Also update any affected frontmatter via `set` (e.g., `checkpoint.sh set <gid> workflow feature-dev`).

The `<step>` argument is the exact label from the Steps table (e.g., `"3. Validate Sprint-Readiness"`, `"QA: Investigate Bug"`). Comments and reasons must not contain `|` or newlines — the script rejects those to preserve the table.

### Comment Content Per Step

| Step | Comment |
|------|---------|
| 0. Dependency Check | `All present` or `Missing: <skill-list>` |
| 1. Get Task URL | `GID: <task-gid>` |
| 2. Fetch Task Details | `<task-id> — <task-name>` |
| 3. Validate Sprint-Readiness | `All checks passed` or `Fixed: <what was set via API>` |
| 4. Fetch Subtasks | `<N> subtasks (<M> complete, <K> remaining)` |
| 5. Fetch Comments & Attachments | `<N> comments, <M> attachments` |
| 6. Check Existing Work | `No existing branch` or `Resumed: <branch-name>` |
| 6a. Ask About Worktree | `worktree` or `current directory` |
| 6b. Confirm Base Branch | `<base-branch>` |
| 7. Create Feature Branch | `<branch-name> off <base>` |
| 8. Create Draft PR | `<pr-url>` |
| 9a. Move to In Progress | `Moved`, `Already in progress`, or `Failed: <reason>` |
| 9b. Post Start Comment | `Posted` or `Skipped (duplicate)` |
| 10. Route to Workflow | `fix-bug`, `brainstorm`, `feature-dev`, or `fast` |
| QA: Resolve | `web-qa`, `mobile-qa`, `none`, or skipped reason |
| QA: Investigate Bug | `Confirmed`, `Cannot reproduce`, or skipped reason |
| QA: Fix Bug | `Fix ready`, `Failed: <reason>`, or skipped reason |
| QA: Verify Fix | `Pass`, `Fail`, or skipped reason |
| QA: Verify Non-Bug | `Passed`, `Failed: <reason>`, or skipped reason |
| 12. Ship It | `Shipped: <pr-url>` |

### Frontmatter Updates

Use the `set` subcommand — it updates the field and refreshes `last_updated`:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh set <gid> <field> "<value>"
```

- After Step 2: set `task_id`
- After Step 7: set `branch` and `base_branch`
- After Step 10: set `workflow`

---

## Pause Flow

Triggered either by an internal `blocked` state (from Step Updates above) or by the operator explicitly asking to pause.

### Trigger Phrases

- "park this", "I'm blocked", "pause task"
- "need to wait for an answer", "put this on hold"
- "waiting on [someone]", "blocked by [someone]"
- "save my progress", "pick this up later", "come back to this later"

### Steps

**1. Verify branch**
Confirm the current branch matches `branch` in checkpoint frontmatter. If on a different branch, warn before proceeding. If a merge is in progress, warn and do not commit.

**2. Commit WIP**
Stage all changes and commit with:

```
WIP: <task-id> — blocked on [short reason]
```

Example: `WIP: MT251-47 — blocked on timezone decision`

**3. Draft blocking question**
Formulate from conversation context. Present for user approval. The user MUST approve the exact wording before it is posted. Never post to Asana without explicit approval.

Example draft:

> "Hey @Sarah Chen — quick question before I can finish the CSV export: should timestamps use the user's local timezone or UTC? This affects how `formatTimestamp()` is implemented."

**4. Post to Asana**
After approval, post via the `asana-api` skill. Include the @mention of the blocking person. See `asana-patterns.md` → "Posting a Blocking Question (Pause)" for the format.

**5. Update checkpoint**

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh block <gid> "<step>" "<who is blocking>"
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh append-note <gid> "<blocking question + who to follow up with>"
```

The `block` call sets `State → blocked` and `Comment → reason`; `append-note` adds a block to the `## Notes` section.

**6. Push branch**
Push the WIP commit to remote.

**7. Confirm**
Report: commit hash, Asana comment link, checkpoint path. Instruct the operator to run `/start-task` with the same URL to resume.

### Asana State

Leave the task status as "In Progress". Do not move the task to a different section.

---

## Resume Flow

Triggered automatically during Initialization when a checkpoint file is found. Also triggered by explicit operator intent ("resume task", "pick up where I left off", "continue [task-id]", "unpause").

### Steps

**1. Load checkpoint** — find the first row that is not terminal. Terminal rows are `Completed = [x]` (completed) or `State = skipped` (non-applicable). Skip terminal rows entirely; resume on the first row that has `Completed = [ ]` AND `State != skipped`.

**2. Present current state** — render the Steps table so the operator sees what's done, what's remaining, and any blocked row.

**3. Check for blocked state** — if the resuming row has `State = blocked`, fetch Asana stories posted after `last_updated` (see `asana-patterns.md` → "Checking for Answers on Resume"). Show new comments as potential answers to the blocking question. If no new comments: offer to resume anyway or keep waiting.

**4. Verify branch exists** — check the branch exists locally or on remote. If deleted: offer to recreate from `base_branch` or start fresh. Starting fresh deletes the checkpoint.

**5. Check task status** — if the task has been completed, reassigned, or moved to a different section since `last_updated`, warn before proceeding.

**6. Post resume comment** (only if the resuming row was `blocked`):

```
Resuming work on branch `<branch>`
```

See `asana-patterns.md` → "Posting a Resume Comment".

**7. Resume work** — check out the branch and continue from the first incomplete row.

---

## Lifecycle End

After Step 12 (Ship It) completes successfully, **delete the checkpoint file** via the helper:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh delete <task-gid>
```

The checkpoint's lifetime is one start → develop → ship pass. Once shipped, the Asana task status moves to "In Review" and the PR is ready for review — any further work on the branch (code-review fixes, reviewer feedback, follow-up commits) is **out of scope** for start-task and is not tracked by this checkpoint. It happens through git + the PR review thread, or via a different skill.

If the checkpoint is not deleted, a stale file may incorrectly trigger a resume the next time `/start-task` is run against the same task GID.

If Step 12 fails partway (e.g., `ship-it` sub-skill error), leave the checkpoint in place with `State → blocked` on the failing row so the operator can retry. Only delete on successful completion of Step 12.

---

## Edge Cases

**Branch deleted since the checkpoint was written** — offer to recreate from `base_branch`, or start fresh (deletes checkpoint).

**Task completed in Asana since last update** — warn: "This task was completed in Asana on [date]. Resume anyway?"

**Task reassigned since last update** — warn: "This task is now assigned to [name]. Resume anyway?"

**Validation fails on resume at Step 3** — re-run validation fresh; present updated results.

**Step 9a or 9b fails on resume** — non-blocking; report and continue. 9a (move) failures leave the task in its prior section; 9b (post start comment) failures mean no 🏁 comment was posted.
