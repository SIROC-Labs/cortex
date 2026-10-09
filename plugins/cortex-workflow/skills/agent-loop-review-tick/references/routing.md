# Routing

The card is the operator's **inbox**; the PR is the **record**. This skill writes both.

## Candidate checks

Walked per card in `$AL order --user <me>` order. The first card passing every check is claimed.

| Check | Read from | Fails → |
|---|---|---|
| `🤖 [AGENT] Ready for review` marker with a `PR: <url>` line | `get_comments(card)` | skip, print `stray — <name> (<ref>): no PR` |
| No live review: a `🤖 [REVIEW] started` newer than the last `🤖 [AGENT]` comment with no `🤖 [REVIEW]` verdict after it, and younger than **3 hours** | comments | skip, print `in flight — <name> (<ref>)`; older than 3 h → adopt (print `adopting — <name> (<ref>)`) |
| PR `state == OPEN` | `gh pr view` | `MERGED` with an `🤖 [REVIEW] Approved` verdict as the latest `[REVIEW]` comment → **housekeeping**: comment `🤖 [REVIEW] Merged by you into <base>` · `PR: <url>`, `move_task(card, board, ready)`, mirror, print `merged by operator — <name> (<ref>)`, continue the walk. Any other non-open state → skip, print `stray — <name> (<ref>): PR <state>` |
| Not already approved on this head: no `🤖 [REVIEW] Approved` verdict newer than the last `🤖 [AGENT]` comment whose `Head:` equals `headRefOid`, with no human PR review or comment newer than it | comments, `gh pr view --json headRefOid,reviews,comments` | skip, print `approved — <name> (<ref>) awaiting your merge`. A moved head or a newer human review or comment is a new review |
| Base mode: `baseRefName` equals `main` or the default branch (`gh repo view --json defaultBranchRef`) | `gh pr view`, `gh repo view` | not a failure: **approve mode**. The review, fixes, gates and CI run as for any PR; the terminal step is "Approve and leave" instead of a merge (`references/merging.md`). Never retarget the PR |
| No armed `autoMergeRequest` on any open PR of the head | `gh pr list --head` | **recover**: `gh pr merge <n> --disable-auto`, note it in the review report, continue |
| `statusCheckRollup` has no `PENDING`/`IN_PROGRESS`/`QUEUED` entries | `gh pr view` | skip, print `checks pending — <name> (<ref>)` |

A skipped card is not moved and not commented on. A card assigned to another user never reaches the walk. A recovery is a decision the run records in the PR review; it is never a reason to stop.

## Comment shapes

Author as Markdown, post with `add_comment`. The first line is exact: the build tick's rework gate reads it.

| Outcome | Comment, verbatim shape | Column |
|---|---|---|
| pass, non-default base | `🤖 [REVIEW] Merged into <base>` · `Squash: <sha>` · `PR: <url>` · `Fixed here: <n> findings` · `Left for you: <the card's live check, or "none">` | `ready` |
| pass, default branch | `🤖 [REVIEW] Approved — merge is yours` · `PR: <url>` · `Base: <base>` · `Head: <sha of the reviewed head>` · `Fixed here: <n> findings` · `Auto-merge disarmed` only when one was · `Left for you: merge the PR, then <the card's live check, or "nothing else">` · `Once merged, the next review run moves this card to Ready.` | stays in `in_review` |
| merged by operator | `🤖 [REVIEW] Merged by you into <base>` · `PR: <url>` | `ready` |
| hand back | `🤖 [REVIEW] Changes requested` · `PR: <url>` · numbered findings, one line each: `<kind> — file:line — what is needed` · `Fixed here: <n>` · `Left for rework: <n>` · `The queue takes this card as rework in priority order.` | `queue` |
| no way forward | `🤖 [REVIEW] Blocked — <reason>` · `Stopped because: <no way to reach the goal | contradiction>` · `Needs from you: <one line>` · `PR: <url>` · `Once resolved, move the card back to In Review.` | `blocked` |

**No way forward** is the only route to `blocked`, and it covers two things. *No way to reach the goal*: the repository is missing under `repos_root`; the PR head cannot be fetched; a branch protection or required-reviewer rule rejects the merge after the gates passed. *Contradiction*: the PR's change works against the card's Problem or Goal as written (the reviewer can say which line), or its Definition of done is unreachable from the card's Approach. A PR targeting the default branch is neither: it is reviewed and approved. Everything else has a recovery here or a hand-back to the queue: a drifted worktree is reset to the PR head; a lost commit in the replay is restored from the backup anchor and the rebase retried once, then handed back; a merge that fails because the head moved is re-read and retried once, then skipped for the next run.

## The PR side

- **Hand back**: one review, `event: COMMENT`, with a line-anchored comment per remaining finding (`path`, `line`, `side: RIGHT`, the failing scenario and what is needed) and a top-level body listing the fixes made with their commits. A finding on a file outside the diff goes in the body with its `file:line` written out. A 422 on the review falls back to one `gh pr comment` carrying the same content; never drop a finding.
- **Pass**, merged or approved: one review, `event: COMMENT`, body = the review report (an approval opens with `Approved for merge into <base>; the merge is yours`): per pass found / validated / fixed, the validator verdicts, each fix with its red → green evidence, the per-fix SOUND verdicts, every gate with its command and result, the identity-diff result and base SHA when a gate was red on the base, CI state, rebase pairing when one ran. When fixes changed what the branch contains, refresh the PR body first (`gh pr edit <url> --body-file -`) so the squash records the shipped state.
- `APPROVE` and `REQUEST_CHANGES` are never used: the PR is under the same account, and GitHub rejects them with a 422.

## Mirror rule

For every other board the card is on (`get_task(card).board` memberships), `get_board(that board)`; if it has a column whose name equals the agent board's cached name for the target role, `move_task(card, that board, that column)`. Otherwise skip silently. Never add a card to a board it is not on.

## Every terminal path

Posts its comment, moves the card (an approval leaves it in `in_review`), mirrors, then `$AL last-run <key> write <outcome> --kind review [--task <ref>]` and the one-line verdict. A card left with a `🤖 [REVIEW] started` and no verdict is adopted after 3 hours. An approved card is skipped while its head is unchanged and no human has written on the PR since, and moves to `ready` once its PR is merged.
