# Shipping a milestone member

A task whose `get_task(task)` carries a `parent` is a milestone member (`plugins/cortex-workflow/references/workflow/boards.md`). Its PR targets the milestone branch, and Step 4 settles the PR instead of moving the task to In Review.

## Resolve the milestone and its branch

1. **Milestone** — follow `parent` with `get_task` until the `kind` is `milestone`. Keep its ref, name and description.
2. **Milestone branch** — the `Branch` cell of the row in the description's **Branches** table (`| Repository | Branch | Parent |`) whose repository is the current one (matching rule in `../../../references/workflow/boards.md` → "Milestone branches"). A branch handed over by the invoking workflow wins. No matching row → stop and ask which branch the member targets; never fall back to `main`.

Pass the milestone (ref, name) and the milestone branch to `create-pr` as `milestone` and `base`.

## Step 4 for a member

Read the member's `Dev Status` from a fresh `get_task(member)`.

**PR already merged** into the milestone branch (`gh pr view <pr> --json state,baseRefName` — the owner approved and merged an Owner Review PR): skip the merge and run steps 3–5 of "Any other Dev Status" below, so the member completes and the milestone check runs.

### Owner Review

Leave the PR open and do not call `set_status` — the member stays `Owner Review`. Post the ship comment (SKILL.md Step 4) with this line before the `🤖 Done` footer:

```
Awaiting owner approval — the owner merges this PR into `<milestone branch>`.
```

Stop here; the milestone check below does not run. Once the owner merges the PR, re-running ship-it on the member completes it ("PR already merged" above).

### Any other Dev Status

1. Confirm the PR targets the milestone branch: `gh pr view <pr> --json baseRefName`. A different base → stop and report; never merge it.
2. Squash-merge and delete the member branch:
   ```bash
   gh pr merge <pr> --squash --delete-branch
   ```
   A refused merge (failing checks, conflicts, protection) → stop and report the `gh` output; do not touch the task.
3. `set_status(member, "Done")` — this also completes it.
4. Post the ship comment with `Merged into \`<milestone branch>\`.` before the `🤖 Done` footer.
5. Run the milestone check.

## Milestone check

`milestone_tasks(milestone)`. If any member is not completed, report how many remain and finish.

When every member is completed:

1. `set_status(milestone, "To QA")`.
2. For each row of the Branches table, open the PR from its branch into its parent unless one is open:
   ```bash
   gh pr list --repo <repository> --head <branch> --base <parent> --state open --json url
   gh pr create --repo <repository> --head <branch> --base <parent> --assignee @me \
     --title "<milestone name>" --body "<Goal and Definition of Done from the milestone description>"
   ```
   A bare repository name takes the current repository's owner.
3. `add_comment(milestone, body)`:
   ```
   All members are merged into the milestone branches — ready for human QA.

   PRs:
   - <repository>: <pr-url>

   Definition of Done:
   <the milestone's Definition of Done, verbatim>
   ```

Merging those PRs and moving the milestone on after QA is the owner's.

## Unattended

With `unattended: true` none of this Step 4 runs for a member: no merge, no `set_status`, no comment, no milestone check. The PR stays open against the milestone branch and the invoking workflow routes it (`plugins/cortex-workflow/references/unattended-answers.md` — merging is never done here).

## Recap lines

- `PR merged into <milestone branch>` / `PR left open for owner review`
- `Member set to Done` (or `skipped`)
- `Milestone: N of M members completed` / `Milestone moved to To QA — PRs: <urls>`
