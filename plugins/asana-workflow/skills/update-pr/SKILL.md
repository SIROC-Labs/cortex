---
name: update-pr
version: 0.1.0
description: >
  Use when the user wants to sync their PR branch with its base branch — "update my PR",
  "merge main into my branch", "my PR is behind", "pull in base branch changes",
  "sync with main", "rebase on main", "resolve conflicts with base". Fetches the base,
  rebases or merges it in, resolves conflicts if needed, and pushes.
---

# Update PR

Sync the current branch with its base branch: fetch → rebase (or merge) → resolve conflicts → push.

## Step 1: Detect Base Branch and Method

```bash
BASE=$(gh pr view --json baseRefName --jq '.baseRefName' 2>/dev/null)
if [ -z "$BASE" ]; then
  BASE=$(git rev-parse --abbrev-ref origin/HEAD | sed 's|origin/||')
fi
```

**Method:** Use rebase by default. Switch to merge only if the user explicitly says "merge" or passes `--merge`.

Tell the user: "Updating `$(git branch --show-current)` from `$BASE` (rebase)." — or "(merge)" if merge was requested.

## Step 2: Fetch Latest

```bash
git fetch origin "$BASE"
```

Check if already up to date:

```bash
BEHIND=$(git rev-list HEAD..origin/"$BASE" --count)
```

If `BEHIND` is 0, tell the user "Already up to date with `$BASE`." and stop.

## Step 3: Rebase (default)

```bash
git rebase origin/"$BASE"
```

**If rebase succeeds:** proceed to Step 5.

**If rebase hits conflicts:** proceed to Step 4.

### Merge (when explicitly requested)

```bash
git merge origin/"$BASE"
```

**If merge succeeds:** proceed to Step 5.

**If merge hits conflicts:** proceed to Step 4 (merge variant).

## Step 4: Resolve Conflicts

List conflicted files:

```bash
git diff --name-only --diff-filter=U
```

For each conflicted file, resolve the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`). Favor the PR branch's intent unless the base branch changes must win (e.g., schema migrations, config values).

After resolving each file:

```bash
git add <file>
```

**Continue rebase:**

```bash
GIT_EDITOR=true git rebase --continue
```

Repeat for each commit if there are multiple conflicts. To abort: `git rebase --abort`.

**Continue merge:**

```bash
GIT_EDITOR=true git merge --continue
```

To abort: `git merge --abort`.

Tell the user "Aborted. Branch is unchanged." on abort.

## Step 5: Push

Rebase rewrites history — a force-push is required and expected:

```bash
git push --force-with-lease
```

After a merge, a regular push suffices:

```bash
git push
```

Never use bare `--force`.

## Step 6: Report

> Branch updated from `$BASE` via rebase. Replayed N commit(s). [PR link if available]

Or for merge:

> Branch updated from `$BASE` via merge. [PR link if available]

List any files where conflicts were resolved.

## Error Handling

- **Not on a branch / detached HEAD** — "You're in a detached HEAD state. Check out a branch first."
- **Uncommitted changes** — Run `git stash` first, complete the operation, then `git stash pop`. Tell the user what was stashed.
- **`gh` not available** — Use the repo default branch as the base. Warn: "No PR found; using default branch `$BASE`."
- **Merge conflict in a generated file** — Prefer the base branch version and re-run the generation step if one exists.
