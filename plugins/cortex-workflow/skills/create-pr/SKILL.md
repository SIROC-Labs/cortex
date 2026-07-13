---
name: create-pr
version: 0.1.0
description: >
  This skill should be used when the user says "create a PR", "open a pull request", "make a PR",
  "push and create PR", "open PR for this", "submit a PR", "PR this branch", "let's get this reviewed",
  or wants to update an existing PR's description or reviewers. Handles the full PR lifecycle: pre-checks,
  branch pushing, structured descriptions, reviewer assignment, and task linking.
  Works standalone or as a step in the ship-it orchestrator.
---

# Create PR

Full PR lifecycle — from pre-checks through creation to capturing the PR URL for downstream skills. Handles branch pushing, reviewer assignment, and structured PR descriptions.

## Usage Modes

- **Standalone** — The user asks "create a PR" from any branch. Generate the summary from git diff/log and prompt for missing inputs.
- **Orchestrator step** — Called by `ship-it` with `orchestrator: true`. Receives the work summary, task URL, and skips git-check (already done by pre-ship-check).
- **Update mode** — The user asks to update an existing PR's description or reviewers.

## Inputs

All inputs are optional. When missing, derive them automatically or prompt the user.

| Input | Source (orchestrator) | Source (standalone) |
|---|---|---|
| Summary (bullets) | From `work-summary` output | Generated from `git log $BASE..HEAD --oneline` and `git diff $BASE...HEAD --stat` |
| What Changed | From `work-summary` output | Generated from git diff |
| How to Test | From `work-summary` output (may be absent) | Omitted unless obvious from changes |
| Testing / QA evidence | From the QA gate (`✅ QA Verification` posted in session by pre-ship-check / a QA skill) plus `work-summary` test results | Generated from the test/lint/build runs done this session |
| Task URL | Passed by `ship-it` | Prompt user: "Is there a task URL for this? (press Enter to skip)" |
| Reviewers | Passed by caller or from CLAUDE.md defaults | From CLAUDE.md defaults, or prompt user |
| orchestrator | `true` when called from ship-it | absent |

## Step 1: Git Checks

**Skip when `orchestrator: true`** — pre-ship-check already validated git state.

Otherwise, invoke `git-check` before creating the PR. If `git-check` returns blocking issues, stop and resolve them before continuing. Advisory warnings are presented to the user to decide whether to proceed.

## Step 2: Push to Remote

After pre-checks pass, ensure the branch is pushed:

```bash
git rev-parse --abbrev-ref @{u} 2>/dev/null
```

If no upstream exists, push with tracking:

```bash
git push -u origin $(git branch --show-current)
```

If upstream exists but local is ahead, push:

```bash
git push
```

## Step 3: Check for Existing PR

Detect if a PR already exists for the current branch:

```bash
gh pr view --json url,title,isDraft 2>/dev/null
```

**Draft PR from start-task:** If a draft PR exists (created by `start-task`), this is the expected path. Do NOT ask the user — proceed to update its description (Step 4), mark it as ready (Step 6), and assign reviewers (Step 5).

**Non-draft PR:** If a non-draft PR exists, ask:

> A PR already exists for this branch: <url>. Update its description, or skip?

To update, use `gh pr edit` (see Updating Existing PRs below).

## Step 4: Build PR Description

### PR Title

Format: `TASK-ID :: Description`

The task ID prefix is **mandatory** when a task is linked. Resolve it in this priority order:

1. **Threaded context** — if the caller (ship-it, log-task, start-task) passed a Task ID explicitly, use it verbatim. Do not re-fetch.
2. **Task key from `get_task`** — fetch the task via the `task-manager` interface (`get_task(task)`) and read the surfaced top-level **`task_id`** (the task's human key — `Key` per `plugins/cortex-workflow/references/workflow/fields.md`).
3. **Task name prefix** — if the task name starts with a ticket ID pattern (`XX-NNN`, `XXX-NNN`, or `XXNNN-NNN`, e.g., `MT251-168`, `BI-176`, `PD253-364`), use that.
4. **Branch name prefix** — if the current branch is `<TASK-ID>/<slug>` (the shape created by `log-task`/`start-task`), extract the TASK-ID segment before the first `/`. This is the fallback when `ship-it` runs in a session later than `log-task` and task context has not been re-threaded.
5. **Field-value scan (defensive fallback)** — if `task_id` is still unresolved, scan the task's returned field values for the first match of `^[A-Z][A-Z0-9]*-\d+$` and use it.

Only skip the `TASK-ID :: ` prefix if none of the above resolves a valid ID, or the caller explicitly signalled no ID is available.

Examples:
- `MT251-168 :: Hide Manage Subscription button`
- `BI-176 :: Fix admin page pagination never showing`
- `PD253-364 :: Hinder`

For the description part, derive from:
1. The task name (minus the prefix, if already in the name)
2. The branch name (convert `feat/add-user-export` to "Add user export")
3. The first line of the work summary

If no task is linked, skip the prefix and use just the description. The user can always override.

### PR Body Template

Build the PR body from available sections. **Omit any section that has no content** — never leave a section header with empty content below it.

```markdown
## Summary
<bullet points summarizing the work — from work-summary or git log>

## What changed
<concrete list of changes — files, endpoints, components affected>

## Testing
<QA verification verdict + the test/lint/build evidence that backs it>

## How to test
<step-by-step testing instructions>

## Task
<url>
```

Rules:
- **The PR description is the authoritative record of QA — it must carry the verification evidence, even when the same evidence was posted to the task.** Reviewers read the PR, not the task manager; QA evidence that lives only in a task comment is invisible at review time. The task comment is a notification, the PR `## Testing` section is the record.
- Populate `## Testing` from the QA gate and `work-summary`: name the regression/added tests, the suites run with their pass counts (distinguish integration vs unit — an integration run against real containers is stronger evidence than a unit run), lint/build status, and the QA verdict (e.g. `backend-qa: PASS`). Omit the section only when there is genuinely no test or QA signal — and when omitting, say why in the Summary.
- If no "How to test" content is available, omit the entire section (header and body).
- If no task URL was provided, omit the entire "Task" section.
- Keep bullets concise and specific. Name files, endpoints, components — not vague descriptions.

## Step 5: Reviewer Assignment

### From CLAUDE.md config

Projects can declare default reviewers in their `CLAUDE.md`:

```markdown
## PR Defaults
reviewers: user1,user2
```

When this section exists, use these reviewers automatically. The user can override by specifying different reviewers.

### From user input

If no defaults are configured and the skill is running standalone, ask:

> Any reviewers to assign? (GitHub usernames, comma-separated, or press Enter to skip)

When called from the orchestrator, skip the prompt if no reviewers were passed — the PR can be created without reviewers.

## Step 6: Create or Promote the PR

### New PR (no existing PR)

Use `gh pr create` with a HEREDOC for the body to preserve formatting:

```bash
gh pr create --title "<concise title>" --assignee @me --body "$(cat <<'EOF'
## Summary
- First change bullet
- Second change bullet

## What changed
- Added endpoint GET /admin/foo
- Fixed validation in bar.ts

## Testing
- Added `test_admin_foo_returns_paginated_codes` (integration, against real DB container) — watched fail before the fix, passes after.
- Suites: 42 integration passed (0 skipped); 1027 unit passed. Lint clean.
- backend-qa: PASS — change adequately covered, no regressions.

## How to test
1. Start the server
2. Call the endpoint
3. Verify response

## Task
<task-url>
EOF
)"
```

Add flags as needed:
- `--assignee @me` — always included to self-assign the PR to the creator
- `--reviewer user1,user2` — if reviewers are specified
- `--base $BASE` — if the target branch isn't the default (detect with `git rev-parse --abbrev-ref origin/HEAD | sed 's|origin/||'`)

### Draft PR from start-task (promote to ready)

When a draft PR exists from `start-task`, update it and mark it as ready:

1. Update title and body with the full description:
   ```bash
   gh pr edit <pr-number> --title "<TASK-ID> :: <description>" --body "$(cat <<'EOF'
   <full PR body>
   EOF
   )"
   ```

2. Mark as ready:
   ```bash
   gh pr ready <pr-number>
   ```

3. Self-assign the PR:
   ```bash
   gh pr edit <pr-number> --add-assignee @me
   ```

4. Add reviewers:
   ```bash
   gh pr edit <pr-number> --add-reviewer user1,user2
   ```

## Step 7: Post-Creation

After `gh pr create` succeeds:

1. **Capture the PR URL** from the command output (it prints the URL on success).
2. **Display to user**: "PR created: <url>"
3. **Return the URL** so calling skills (ship-it) can use it.

## Updating Existing PRs

To update an existing PR's body:

```bash
gh pr edit <pr-number> --body "$(cat <<'EOF'
<new body>
EOF
)"
```

Reviewers can also be added to existing PRs:

```bash
gh pr edit <pr-number> --add-reviewer user1
```

## Error Handling

- **`gh` not installed or not authenticated** — Tell the user: "The `gh` CLI is not available or not authenticated. Run `gh auth login` first."
- **`gh pr create` fails** — Check: Is the branch pushed? Are there commits ahead of the base branch? Is there already a PR for this branch? Report the specific error.
- **No commits on branch** — If `git log $BASE..HEAD` is empty, there's nothing to PR. Tell the user.
- **Merge conflicts with base** — Warn the user but don't block PR creation. GitHub will show the conflict status.
- Never silently skip an error. Always report what failed and suggest a fix.
