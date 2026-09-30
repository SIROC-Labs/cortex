# Merging

Every git command names its worktree (`git -C <wt>`); the shell resets between calls, and these commands rewrite and delete branches. `<n>` is the PR number, `<base>` the PR's declared `baseRefName`, `<head>` its `headRefName`, `<repo>` the primary checkout under `repos_root`, `<wt>` the card's worktree, `<scratch>` a writable directory outside the repository.

## Read the PR

```bash
gh pr view <url> --json number,url,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,\
mergeStateStatus,autoMergeRequest,statusCheckRollup,reviewDecision
gh pr list --head <head> --state open --json number,autoMergeRequest
```

The base is whatever the PR declares. `<base>` equal to `main` or the repository's default branch (`gh repo view --json defaultBranchRef`) is retargeted to the milestone branch the card's milestone names for this repository (`gh pr edit <n> --base <branch>`); with none, the card has no way forward (`references/routing.md`). An armed `autoMergeRequest` on any open PR on this head is disarmed first (`gh pr merge <n> --disable-auto`): a green push would otherwise merge before the review finished.

## Rebase

Run when `git -C <wt> merge-base --is-ancestor origin/<base> HEAD` is false.

```bash
git -C <wt> fetch origin
test "$(git -C <wt> rev-parse HEAD)" = "<headRefOid>" \
  || git -C <wt> reset --hard "<headRefOid>"                      # the worktree is disposable; the PR head is the truth
git -C <wt> branch -f backup/pr<n>-prerebase HEAD
git -C <wt> tag -f pr<n>-oldbase "$(git -C <wt> merge-base HEAD origin/<base>)"
git -C <wt> rebase origin/<base>                                # conflict → "Conflicts" below
git -C <wt> range-diff pr<n>-oldbase..backup/pr<n>-prerebase origin/<base>..HEAD
git -C <wt> rev-list --count pr<n>-oldbase..backup/pr<n>-prerebase
git -C <wt> rev-list --count origin/<base>..HEAD
```

Every `range-diff` pairing must be `=` or `!`; a `!` needs a one-line justification from the hunk. An unpaired commit is resolved mechanically, never by eye: `git cherry -v origin/<base> <ref>` on both sides, subjects diffed; a subject only on the backup side is a lost commit: `git -C <wt> reset --hard backup/pr<n>-prerebase`, retry the rebase once, and hand back if it is lost again. Commit counts must match unless `git cherry` shows the difference as already upstream. Then run the affected fast suite: `range-diff` proves text, not behaviour.

### Conflicts

A conflict is resolved here when the resolution is clear: the two sides change different things in the same hunk and both belong (keep both, in the order the file already implies); one side is a rename or move the other did not see (apply the rename to the other side's lines); a generated or lock file (regenerate with the repo's own command). Resolve, `git -C <wt> rebase --continue`, and run the affected fast suite; a red suite reverts to the backup anchor and hands back. A conflict whose sides want different behaviour from the same code, or that touches the card's Contract, has no clear resolution: `git -C <wt> rebase --abort` and hand back naming the files and both intents. Every resolution is recorded in the review report.

```bash
git -C <wt> push --force-with-lease --force-if-includes origin <head>
gh pr view <url> --json headRefOid                              # must equal git -C <wt> rev-parse HEAD
```

The anchors (`backup/pr<n>-prerebase`, `pr<n>-oldbase`) are deleted only in cleanup, as separate commands.

## Gates

Through the repository's own entrypoints (the `make` target, CI command or pre-commit entry), never the underlying runner by hand. At minimum: the whole-file quality gate over the touched set, lint, typecheck, `git -C <wt> diff --check origin/<base>..HEAD`, the full affected fast suite, and the declared integration suite with its own containers under an isolated compose project name, torn down on every exit path.

**A gate red on the base too** is attributed by failure identity, not counts:

```bash
git -C <repo> worktree add --detach <scratch>/base-pr<n> origin/<base>
# bootstrap it the way the repo documents; a bare worktree has no deps and no env files
( cd <scratch>/base-pr<n>/<module-dir> && <declared check> 2>&1 | <normalise to "file -> message"> | sort > <scratch>/base.txt ); echo $?
( cd <wt>/<module-dir>                 && <declared check> 2>&1 | <normalise to "file -> message"> | sort > <scratch>/head.txt ); echo $?
diff <scratch>/base.txt <scratch>/head.txt
```

Read both exit statuses: a crashed base run (not 0 or 1) voids the comparison; a clean base means every head finding belongs to this PR. Strip line and column numbers before diffing. The identity diff and the base SHA (`git -C <repo> rev-parse origin/<base>`) go in the report. Remove the base worktree afterwards.

A check that cannot run (no container runtime, missing credential) is named in the report with what is therefore unverified; it is not a pass.

## Push and CI

```bash
gh pr view <url> --json autoMergeRequest                        # re-check right before the push
git -C <wt> push origin <head>
TO=$(command -v timeout || command -v gtimeout)
if [ -n "$TO" ]; then "$TO" 900 gh pr checks <n> --watch; else gh pr checks <n> --watch; fi
gh pr checks <n>
```

Without a `timeout` binary, poll `gh pr checks <n>` at intervals instead of blocking. A repository with no checks is reported as "no checks configured", not left blank. Red after the push is a finding: one more pass through fixing, then hand back.

## Merge and clean up

Only after every gate is green, CI is green on the pushed head, and no finding remains.

```bash
gh pr ready <n>
gh pr merge <n> --squash --delete-branch \
  --subject "<type>(<scope>): <card title> (<card ref>)" \
  --body "Task: <card url>
PR: <pr url>"
git -C <repo> fetch origin --prune
git -C <repo> worktree remove --force <wt>
git -C <repo> branch -D <head> 2>/dev/null || true
git -C <repo> branch -D backup/pr<n>-prerebase 2>/dev/null || true
git -C <repo> tag -d pr<n>-oldbase 2>/dev/null || true
git -C <repo> worktree prune
git -C <repo> rev-parse origin/<base>                            # the squash SHA for the card comment
```

`<type>` follows the branch's commits (`feat`, `fix`, …). `--delete-branch` removes the remote head; the local deletions cover the branch and the anchors in the primary checkout. Nothing here touches `<base>`, `main`, or any branch the primary checkout has checked out. A merge that fails because the head moved is re-read and retried once, then left for the next run; one rejected by a protection rule is a card with no way forward.
