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

If resuming, check out the existing branch and skip branch creation. When a worktree is in use, attach the worktree to that branch instead of creating one:

```bash
git worktree add <path> <existing-branch>
```

If starting fresh, proceed normally.

## Worktree Setup

A worktree is the default. Create it with the first available option:

1. **A native worktree tool, if the agent provides one** — e.g. `EnterWorktree`, `WorktreeCreate`, a `/worktree` command, or a `--worktree` flag.
2. **Otherwise `git worktree add` directly.**

`<path>` must be anchored to the **main repo root** (a sibling of it), never a cwd-relative path — a relative path nests the new worktree inside whichever worktree is currently active:

```bash
MAIN_ROOT="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
WORKTREE_PATH="${MAIN_ROOT}/../<repo>-<task-id>"
```

After creating it, follow the project's documented worktree bootstrap — `CLAUDE.md`, `README`, or a script such as `scripts/setup-worktree.sh` (install deps, copy env files, start local services). A project that documents none is not a failure: say so, suggest adding `scripts/setup-worktree.sh`, and continue.

Creation failures are **blocking** — see start-task Step 6a. Do not silently fall back to the current directory.

## Resolving the Base Branch

The default base is `origin/main`, read from the remote so the local `main` is never checked out or pulled:

```bash
git fetch origin
```

If `origin/main` does not resolve, fall back to the remote's default branch and say which was used:

```bash
git rev-parse --verify --quiet origin/main \
  || git symbolic-ref --quiet refs/remotes/origin/HEAD   # e.g. refs/remotes/origin/master
```

An explicit `base:<branch>` argument overrides both. A bare name resolves against the remote (`base:develop` → `origin/develop`); pass a local ref explicitly if that is what you mean.

## Create Feature Branch

Use the base branch resolved in Step 6b of start-task.

Inform (do not ask) when creating:

> Creating branch `MT251-12/add-export-endpoint` off `origin/main`

```bash
# Default — inside the worktree created in Step 6a
git worktree add <path> -b <task-id>/<slug> <base-branch>

# With no-worktree — in the current directory
git checkout -b <task-id>/<slug> <base-branch>
```

Both forms branch straight from the resolved base ref, so no `checkout` + `pull` of a local base branch is needed.

## Branch Naming Convention

Format: `<task-id>/<slug>`

- **task-id** — the project ID field on the task (e.g., `MT251-12`, `BI-88`)
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
