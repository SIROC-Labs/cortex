# Claiming

## Ownership

The agent board is shared by several people, each running their own ticks. A card is this run's when its `assignee` is empty or is the current user; a card assigned to anyone else belongs to their run, whatever column it sits in. Such a card is never moved, commented on, reassigned or adopted: it is printed as `skipped — <name> (<ref>) assigned to <user>` and left alone. Claiming sets the assignee, so a claimed card is visibly owned from then on.

## Ordering

`list_tasks(board, queue)` returns the column in native order. Build `{"tasks": [{ref, name, index, priority, assignee}], "priority_order": [...]}` where `index` is the position in that list, `priority` is `fields.Priority`, `assignee` is the task's assignee (`{ref, name}` or `null`), and `priority_order` is the `Priority` field's enum option names from `list_fields(board)`, highest first. `agent_loop.py order --user <me> --from-json -` drops cards assigned to anyone else and prints the claim order: priority first, unset last, native position as the tiebreak. Nothing else contributes: not age, not category, not whether a run touched the card before. The operator moves a card up by raising its priority or dragging it to the top.

## The dependency gate

For each candidate in order, `get_dependencies(card)` and

```
agent_loop.py gate --from-json - <<< '{"blockers": <deps>, "board": "<board ref>", "columns": <cache.columns>, "column_names": <cache.column_names>}'
```

A blocker is satisfied when it is completed, or sits in the agent board's `ready`/`done` column, or sits on another board in a column named like one of them. `in_review` does not satisfy: a card there has an open PR whose work is not yet on the milestone branch a dependent would build from. Everything else blocks, including a column you do not recognise: fail closed, because building on work that was never written is worse than waiting an hour. A gated candidate is skipped, not moved. Dependencies written in prose are not this gate's job; they fall to the readiness audit.

The gate applies to selection only. An adopted orphan skips it: it was claimed and part-built already.

## Modes

The mode is a fact about the card. A `🤖 [AGENT] started` comment exists only because a previous run cut a branch and opened a PR for this card, so its presence is **rework**: the human answered a question or reviewed the PR and handed the card back, or the review run posted `🤖 [REVIEW] Changes requested` and moved it back to the queue. An adopted orphan takes the mode its **latest** marker names (`🤖 [AGENT] rework started` → rework; `🤖 [AGENT] started` → fresh; none → fresh); never re-derive an orphan's mode from the first rule.

## Rework gate

1. **A delta exists**: a human comment, a PR review, or a `🤖 [REVIEW] Changes requested` card comment newer than this system's last `🤖 [AGENT]` comment (`gh pr view <url> --json reviews,comments`; `gh api repos/<org>/<repo>/pulls/<n>/comments`). Nothing new → the card was moved by mistake; stop and say so.
2. **The delta is actionable as written.** An answer that leaves the original question open, or review feedback amounting to "this isn't right", is a stop quoting the part you cannot act on. The review run's findings arrive as a PR review with one line-anchored comment per finding, each naming what is needed; the card comment lists the same findings and which ones the review run already fixed. Rework addresses every remaining finding, and the branch may carry the review run's own fix commits on top of the previous run's, so fetch before building.
3. **The prior work is still there.** The branch exists on `origin`. Deleted → stop; a deleted branch may mean the work was rejected.
