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

## Unattended worktree

Worktrees live inside the repository under `.worktrees/`, kept out of git through the local exclude file, never the shared `.gitignore`:

```bash
REPO=<the readiness verdict's repository path>
git -C "$REPO" fetch origin --prune
BRANCH="agent/<task-ref>-<slug>"          # rework: the branch from the start marker
WT="$REPO/.worktrees/agent-<task-ref>-<slug>"
mkdir -p "$REPO/.worktrees"
grep -q '^/\.worktrees/$' "$REPO/.git/info/exclude" || printf '/.worktrees/\n' >> "$REPO/.git/info/exclude"
if [ -d "$WT" ] && git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$WT" pull --ff-only
elif git -C "$REPO" ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git -C "$REPO" worktree add "$WT" --track -b "$BRANCH" "origin/$BRANCH"
else
  git -C "$REPO" worktree add "$WT" -b "$BRANCH" "origin/<base>"
fi
```

Then bootstrap: run `scripts/setup-worktree.sh` when the repo has one, else follow the repo's `CLAUDE.md`/`README` setup. Never run an "initialise env" target that scaffolds blank files from samples. Copy the ignored env files from the primary checkout, matching both `.env`-style dotfiles and `*.env` files at any depth:

```bash
cd "$REPO" && git ls-files --others --ignored --exclude-standard \
  | grep -iE '(^|/)\.env|\.env$|\.env\.' \
  | while IFS= read -r f; do mkdir -p "$WT/$(dirname "$f")" && cp "$REPO/$f" "$WT/$f"; done
```

Verify what landed (`ls`, and the variables the task's tests need). Every git command from here carries `-C "$WT"`. Never `rm -rf` a worktree; `git worktree remove` it. Do not remove it at the end of the run: the reviewer reads from it.

Unattended branch naming is `agent/<task-ref>-<slug>` because the human task key may not exist yet when the branch is cut.
