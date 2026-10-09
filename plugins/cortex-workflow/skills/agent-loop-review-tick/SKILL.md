---
name: agent-loop-review-tick
version: 0.1.0
description: >
  Use when invoked as /agent-loop-review-tick by a scheduler, or when the user asks to review
  one card from the agent board. Takes exactly one card from the board's in-review column,
  reviews its PR for completeness, security and simplicity, checks CI and the absence of
  suppressions, fixes what is small, hands back what is large, and squash-merges a passing PR
  into its milestone branch. A PR targeting the repository's default branch gets the same review
  and is approved, not merged: that merge stays the operator's. Never asks the operator a
  question, never runs a live service, never merges into the default branch. Nothing to review
  ends the run.
---

# Agent loop review tick

Take **one** card from `in_review`, review its PR, fix or hand back, merge when it passes, or approve when its base is the default branch. `AL=${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/agent-loop-setup/scripts/agent_loop.py`. Every task-manager call goes through the `task-manager` interface. The run belongs to one **profile** (`../agent-loop-tick/references/running.md` → "What every way must keep"): the name given in the arguments, else `CORTEX_PROJECT`, else the profile whose repository this run was started in, else the only profile configured. Anything else is asked, never guessed. Once known, every script call and seam operation in this run carries `CORTEX_PROJECT=<key>` in its environment.

## The prime directive

**This run is unattended. Never ask a question and wait**, with one exception: which profile to run when it cannot be inferred (step 1). Every decision is this run's, taken from the card, the PR, the repository and the tables in `references/`, and recorded in the PR review. A finding the tables cannot classify is a hand-back to the queue, not a question. A card goes to `blocked` only when there is **no way to reach the goal** from here (the repository or the PR cannot be operated on, a protection rule needs a human) or when something **contradicts the card outright** (the PR builds against the Problem). Everything recoverable is recovered: an armed auto-merge is disarmed, a drifted worktree is reset, a clear rebase conflict is resolved. The PR's base decides only the last step: a milestone or any other non-default branch is merged into; the default branch is never merged into, the PR is approved and left to the operator.

## Flow

Each step is idempotent so an interrupted run can be adopted by the next one.

1. **Load.** `$AL key [<name>]` → `<key>`. Exit 4 with several profiles named → **ask which one** and take the answer as `<name>`; this is the one question this run may ask, because without it there is no board to read, and a run with nobody to answer ends here with outcome `unconfigured`. Exit 4 with none configured → print its message, outcome `unconfigured`. `$AL read <key>`. Exit 4 → print `agent loop not configured — run agent-loop-setup <key>`, outcome `unconfigured`. `get_current_user()`. `$AL last-run <key> start --kind review`.
2. **Candidates.** `list_tasks(board, in_review)` incomplete → `$AL order --user <me>` (a card assigned to someone else is theirs; never touch it). Walk in order and take the first card that passes the candidate checks in `references/routing.md`: a `🤖 [AGENT] Ready for review` marker with a PR URL, no live review in flight, not already approved on this head, PR open, checks settled. Recoverable conditions are fixed on the spot (an armed auto-merge is disarmed); a card with no way forward routes to `blocked` (step 9); one failing a transient check is skipped this run; an approved card whose PR the operator has since merged is moved to `ready` on the way past and the walk continues. None left → outcome `nothing to review`.
3. **Claim.** `add_comment(card, "🤖 [REVIEW] started · PR: <url>")`; `set_field(card, "Assignee", <me>)` when unassigned. The card stays in `in_review`.
4. **Sync.** Locate the worktree named in the card's start marker; absent → recreate it with the build tick's unattended worktree recipe. `git -C <wt> fetch origin`; local HEAD differing from the PR head → reset the worktree to the PR head, it is disposable. Behind `origin/<base>` → rebase per `references/merging.md` → "Rebase", with anchors, `range-diff`, commit counts, the affected fast suite and a lease-protected force-push. A conflict is resolved here when its resolution is clear (`references/merging.md` → "Conflicts"); otherwise abort and hand back naming the files.
5. **Review passes, in parallel.** Three reviewer agents over `origin/<base>...HEAD`, one brief each from `references/reviewing.md`: **completeness** (the card's Definition of done, Verification, Scope boundary and Contract, plus preservation), **security**, **simplify**. Findings only, `file:line` each. Then **one validator** over the merged list: CONFIRMED, PLAUSIBLE or REFUTED. Only CONFIRMED and PLAUSIBLE survive.
6. **Mechanical gates.** `references/reviewing.md` → "Suppression scan" over the diff: every hit is CONFIRMED. `gh pr checks <n>`: red is CONFIRMED with the failing log excerpt.
7. **Fix or hand back.** Classify every surviving finding by `references/fixing.md`. Fix the fixable ones now: a failing regression test first for a behavioural defect, the smallest structural fix, the affected suite green, one commit per pass. A **fresh validator** reads the fix patch and rules SOUND per fix, or names what the fix gave up; a non-SOUND fix is reverted and joins the hand-back list. One hand-back finding hands the card back, after the fixable findings are fixed and pushed.
8. **Verify and push.** The repo's declared gates through their own entrypoints (`references/merging.md` → "Gates"). A gate red on the base too is attributed by failure identity, never by counts. Push once, re-check `autoMergeRequest`, wait for CI bounded. Red → one more pass through step 7, then hand back.
9. **Route** by `references/routing.md`: pass on a non-default base → merge and clean up (`references/merging.md` → "Merge and clean up"), comment, `move_task(card, board, ready)`; pass on the default branch → approve and leave (`references/merging.md` → "Approve and leave"), comment, the card stays in `in_review`; hand back → PR review with line-anchored findings, comment, `move_task(card, board, queue)`; no way forward → comment naming the stop condition, `move_task(card, board, blocked)`. Mirror per the routing rule.
10. **End.** `$AL last-run <key> write <outcome> --kind review [--task <ref>]` and print one line: `review tick complete — <ref> "<name>" → <ready | approved | queue | blocked | nothing to review | unconfigured>`.

## What this skill never does

Ask; run a live service or a paid flow; merge into `main` or a repository's default branch (a PR targeting it is reviewed to the same bar, then approved and left to the operator); retarget a PR to another base; enable auto-merge (disarming one is fine); submit a GitHub approval on its own PR (every review is `event: COMMENT`; "approved" is the card verdict, not a GitHub review state); implement missing functionality; touch a card assigned to someone else; touch `queue` except to hand back, `in_progress`, or `done`; delete the milestone branch or anything in the primary checkout; route to `blocked` a card it could have recovered.

## References

- `references/reviewing.md` — the three pass briefs, the validator brief, the suppression scan.
- `references/fixing.md` — fix-here versus hand-back by complexity, how a fix is proved.
- `references/merging.md` — rebase, gates, CI wait, squash merge and cleanup commands.
- `references/routing.md` — candidate checks and recoveries, comment shapes, columns, the two stop conditions, the in-flight ceiling, the mirror rule.
