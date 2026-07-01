# Worktree Flow Reference

## 7b-1. Identify what changed

```bash
# Files changed vs main (uncommitted)
git diff --name-only main

# Commits on current branch beyond main
git diff --name-only main...HEAD
```

Save the union of both lists as `<changed_files>`.

**If `<changed_files>` is empty**, stop and ask:
> "I don't see any changes in the working tree relative to main. Are the changes stashed, on a different branch, or not yet saved? Let me know where to find them."

Do not proceed until the changed files are identified.

## 7b-3. Create a git worktree

```bash
# Determine worktree path — sibling to the repo root
REPO_ROOT=$(git rev-parse --show-toplevel)
WORKTREE_PATH="${REPO_ROOT}/../$(basename $REPO_ROOT)-<task-id-slug>"

# Ensure main is up to date
git fetch origin main

# Create worktree on a new branch based on main
git worktree add "$WORKTREE_PATH" -b "<branch_name>" origin/main
```

Report to the user:
> "Created worktree at `../cortex-MT251-182` on branch `MT251-182/fix-csv-export-null-crash`."

If the worktree path already exists, append a counter suffix (`-2`, `-3`) rather than failing.
If `git worktree add` fails because the branch already exists, ask whether to reuse it or pick a new name.

## 7b-4. Copy changes into the worktree

```bash
for f in <changed_files>; do
  mkdir -p "$WORKTREE_PATH/$(dirname $f)"
  cp "$REPO_ROOT/$f" "$WORKTREE_PATH/$f"
done
```

Then stage and commit:

```bash
cd "$WORKTREE_PATH"
git add <changed_files>
git commit -m "<task_id> :: <task-title-slug>"
```

**Do NOT push. Do NOT create a PR. Do NOT update the task's status.** `ship-it` owns all of these.
