# Routing

The card is the operator's **inbox**: it says what they must do next, in one of the shapes below and nothing else. The PR is the **record**: what changed, why, the decisions, the evidence. `start-task unattended` writes the PR side; this skill writes the card side.

## Comment shapes

| Verdict | Comment, verbatim shape | Column |
|---|---|---|
| `shipped` | `🤖 [AGENT] Ready for review` · `PR: <url>` · `Needs from you: <line from the verdict>` | `in_review` |
| `clarification` | `🤖 [AGENT] Needs clarification` · the numbered questions with proposed defaults · `Established: <one line>` · `Answer here, then move the card back to the queue — top of the column, or a higher Priority, if it should be taken next.` | `blocked` |
| `failed` | `🤖 [AGENT] Blocked — run stopped` · `Needs from you: <line>` · `Evidence: <url>` · `Worktree: <path>` · `Once resolved, move the card back to the queue.` | `blocked` |

A failure before a PR exists has no PR comment to point at; the verdict's `Needs from you` then carries the `Where / What failed / output / What is needed` block, and it goes on the card in full.

Author comments as Markdown and post with `add_comment`; the provider renders.

## Mirror rule

For every other board the card is already on (`get_task(card).board` memberships), `get_board(that board)` and, if it has a column whose name equals the agent board's cached name for the target role, `move_task(card, that board, that column)`. Otherwise skip silently. Never add a card to a board it is not on. This keeps a team sprint board honest without configuring it.

## Every terminal path

Leaves `in_progress`. A card left there is read as a crashed run and adopted next tick. Then `agent_loop.py last-run <key> write <outcome>` and the one-line verdict.
