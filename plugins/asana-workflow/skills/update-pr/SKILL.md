---
name: update-pr
version: 0.1.0
description: >
  Use when the user wants to sync their PR branch with its base branch — "update my PR",
  "merge main into my branch", "my PR is behind", "pull in base branch changes",
  "sync with main", "rebase on main", "resolve conflicts with base". Fetches the base,
  merges it in, resolves conflicts if needed, and pushes.
---

# Update PR

Sync the current branch with its base branch: fetch → merge → resolve conflicts → push.

## Step 1: Detect Base Branch

```bash
# Get the PR's base branch (most reliable when a PR exists)
BASE=$(gh pr view --json baseRefName --jq '.baseRefName' 2>/dev/null)

# Fall back to the repo default branch
if [ -z "$BASE" ]; then
  BASE=$(git rev-parse --abbrev-ref origin/HEAD | sed 's|origin/||')
fi

echo "Base branch: $BASE"
echo "Current branch: $(git branch --show-current)"
```

Tell the user: "Updating from `$BASE` into `$(git branch --show-current)`."

## Step 2: Fetch Latest

```bash
git fetch origin "$BASE"
```

Check if already up to date:

```bash
BEHIND=$(git rev-list HEAD..origin/"$BASE" --count)
```

If `BEHIND` is 0, tell the user "Already up to date with `$BASE`." and stop.

## Step 3: Merge Base into Current Branch

Use merge (not rebase) — the PR already has commits; rebasing rewrites history and requires a force-push which breaks review continuity.

```bash
git merge origin/"$BASE"
```

**If merge succeeds (no conflicts):** proceed to Step 5.

**If merge exits non-zero (conflicts):** proceed to Step 4.

## Step 4: Resolve Conflicts

List conflicted files:

```bash
git diff --name-only --diff-filter=U
```

For each conflicted file, open it and help the user resolve the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`). Apply the correct resolution based on context — favor the PR branch's intent unless the base branch changes must win (e.g., schema migrations, config values).

After resolving each file:

```bash
git add <file>
```

Once all conflicts are resolved:

```bash
git merge --continue
# Accept the default merge commit message (non-interactive):
GIT_EDITOR=true git merge --continue
```

If the user prefers to abort:

```bash
git merge --abort
```

Tell the user: "Merge aborted. Branch is unchanged."

## Step 5: Push

```bash
git push
```

If push is rejected because the remote has diverged (should not happen with merge, but possible):

```bash
git push --force-with-lease
```

Only use `--force-with-lease`, never bare `--force`. Confirm with the user before force-pushing.

## Step 6: Report

Tell the user:

> Branch updated from `$BASE`. Merged N commit(s). [Link to PR if available]

If there were conflicts, list the files that were resolved.

## Error Handling

- **Not on a branch / detached HEAD** — Tell the user: "You're in a detached HEAD state. Check out a branch first."
- **Uncommitted changes** — Run `git stash` first, complete the merge, then `git stash pop`. Tell the user what was stashed.
- **`gh` not available** — Use the repo default branch as the base. Warn: "No PR found; using default branch `$BASE`."
- **Merge conflict in a generated file** — Prefer the base branch version and run the generation step again if one exists.
