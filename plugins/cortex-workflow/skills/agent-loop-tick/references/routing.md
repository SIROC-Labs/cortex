# Routing

The card is the operator's **inbox**: it says what they must do next, in one of the shapes below and nothing else. The PR is the **record**: what changed, why, the decisions, the evidence. `start-task unattended` writes the PR side; this skill writes the card side.

## Comment shapes

| Verdict | Comment, verbatim shape | Column |
|---|---|---|
| `shipped` | `🤖 [AGENT] Ready for review` · `PR: <url>` · `Needs from you: <line from the verdict>` | `in_review` — the review run in this plugin takes it from there |
| `clarification` | `🤖 [AGENT] Needs clarification` · `Stopped because: <no clear solution | contradiction>` · the numbered questions with proposed defaults · `Established: <one line>` · `Answer here, then move the card back to the queue — top of the column, or a higher Priority, if it should be taken next.` | `blocked` |
| `failed` | `🤖 [AGENT] Blocked — run stopped` · `Needs from you: <line>` · `Evidence: <url>` · `Worktree: <path>` · `Once resolved, move the card back to the queue.` | `blocked` |

A failure before a PR exists has no PR comment to point at; the verdict's `Needs from you` then carries the `Where / What failed / output / What is needed` block, and it goes on the card in full.

Author comments as Markdown and post with `add_comment`; the provider renders.

## Work items

A milestone's work item has no column. Each verdict posts the same comment as the table above, and the work item **stays assigned**: held, with its latest marker naming the step. The operator releases a `Needs clarification` or `Blocked` one by answering and unassigning it, which puts it back in front of the build run; replace the comment's last line with `Answer here, then unassign this card.` In the same step:

1. **Cards row.** `get_task(milestone)` → `agent_loop.py cards --from-json -` with `{"description": <its description>, "row": {"ref": <item>, "state": <state>, "pr": <url or omit>}}` → `set_description(milestone, <output>)`. `state` is `in progress` on claim, `in review` on `shipped`, `needs clarification` or `blocked` on a stop.
2. **Milestone column.** `milestone_tasks(milestone)` with each open item's latest marker → `agent_loop.py aggregate --from-json -` (`{"subtasks": [...]}`) → `move_task(milestone, board, columns[<role>])` when the milestone is not already there. The first claim moves it from `queue` to `in_progress`, and it never returns to `queue`; a stop moves it to `blocked`.

## Mirror rule

For every other board the card is already on (`get_task(card).board` memberships — a work item's product board), `get_board(that board)` and, if it has a column whose name equals the agent board's cached name for the target role, `move_task(card, that board, that column)`. Otherwise skip silently. Never add a card to a board it is not on. This keeps a team sprint board honest without configuring it.

## Every terminal path

Leaves `in_progress`, or for a work item posts a step-naming marker. A card left there, or a work item held by this user whose latest marker is none or `started`, is read as a crashed run and adopted next tick. Then `agent_loop.py last-run <key> write <outcome>` and the one-line verdict.
