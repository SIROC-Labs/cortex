# Git Workflow

## Check for Existing Work

Before creating a new branch, check if work already exists for this task:

```bash
# Sync remote branch info
git fetch --prune

# Check for existing branches with the task ID
git branch --list "*<task-id>*"
git branch -r --list "*<task-id>*"

# Check for open PRs (skip if gh CLI is not installed)
gh pr list --search "<task-id>" --state open
```

**If a branch or PR exists**, present the finding:

> Found existing branch `MT251-12/add-user-endpoint`. Resume that work, or start fresh?

If resuming, check out the existing branch and skip branch creation. If starting fresh, proceed normally.

## Create Feature Branch

Use the base branch confirmed by the user in Step 6b of start-task. Do not assume `main` — always use the explicitly chosen base.

Inform (do not ask) when creating:

> Creating branch `MT251-12/add-export-endpoint` off `main`

```bash
git checkout <base-branch>
git pull origin <base-branch>
git checkout -b <task-id>/<slug>
```

## Branch Naming Convention

Format: `<task-id>/<slug>`

- **task-id** — the project ID from the Asana custom field (e.g., `MT251-12`, `BI-88`)
- **slug** — short, lowercase, hyphenated version of the task name (e.g., `add-export-endpoint`)

Examples:
- `MT251-47/add-csv-export`
- `BI-88/login-fails-silently`
- `PD253-7/add-dark-mode-toggle`

The task ID should also appear in commit messages for traceability.

## WIP Commit Convention (Pause)

When pausing a task, stage all changes and commit with this format:

```bash
git add -A
git commit -m "WIP: <task-id> — blocked on [short reason]"
git push origin $(git branch --show-current)
```

Examples:
- `WIP: MT251-47 — blocked on CSV export format decision`
- `WIP: BI-88 — blocked on repro steps from QA`

## Branch Verification Before Pause

Before committing WIP, verify the current branch matches the task:

```bash
git branch --show-current
```

If the current branch does not contain the task ID, warn:
> Current branch is `main`, but the task branch is `MT251-47/add-csv-export`. Switch to the task branch first?

If a merge is in progress (`git status` shows "You have unmerged paths"), warn and ask how to proceed before committing.
