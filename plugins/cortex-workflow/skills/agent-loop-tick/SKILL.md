---
name: agent-loop-tick
version: 0.1.0
description: >
  Use when invoked as /agent-loop-tick by a scheduler, or when the user asks to run one task
  from the agent board. Takes exactly one card from the board's queue, gates it, runs it
  through start-task in unattended mode, and routes the card to in-review or blocked. Takes
  only cards that are unassigned or assigned to the current user; a card assigned to someone
  else is theirs. Never asks the operator a question, never runs a live service, never merges.
  An empty queue ends the run.
---

# Agent loop tick

Take **one** card off the agent board, execute it, route it. `AL=${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/agent-loop-setup/scripts/agent_loop.py`. Every task-manager call goes through the `task-manager` interface. The run belongs to one **profile** (`references/running.md` → "What every way must keep"): the name given in the arguments, else `CORTEX_PROJECT`, else the only profile configured. Every script call and seam operation in this run carries `CORTEX_PROJECT=<key>` in its environment.

## The prime directive

**This run is unattended. Never ask a question and wait.** Every gate answers from the card, from the readiness verdict, or from `plugins/cortex-workflow/references/unattended-answers.md`; everything the card leaves open is **this run's decision**, taken from the card, the repository and its conventions and recorded in the PR under "Decisions taken". A card goes to `blocked` only on a stop condition of `agent-loop-readiness`: no clear solution, or a contradiction with the card. If you are about to write "Should I…", decide; if you cannot say why your choice is the one, that is the stop.

## Flow

Each step is idempotent so an interrupted run can be adopted by the next one.

1. **Load.** `$AL key [<name>]` → `<key>`; exit 4 (no profile, or several and none named) → print its message, outcome `unconfigured`. `$AL read <key>`. Exit 4 → print `agent loop not configured — run agent-loop-setup <key>`, go to step 10 with outcome `unconfigured`. `get_current_user()` → `<me>`; the board is shared, and only cards that are unassigned or assigned to `<me>` are this run's (`references/claiming.md` → Ownership).
2. **Rotate.** With a rotation pattern: `list_boards()` → `$AL rotate <key> --from-json -`. `rotate: true` → `get_board(new)`, re-map every role by its cached `column_names` (a missing name → print `board <name> lacks column <name> — run agent-loop-setup`, outcome `unconfigured`), `$AL write`, print `rolled to <name>`. Then `list_tasks(previous, queue)`; print `left behind — <name> (<ref>) on <previous>` per incomplete card. Never claim from the previous board.
3. **Orphan.** `list_tasks(board, in_progress)` → `$AL order --user <me>`. A card assigned to someone else is their live run: print `skipped — <name> (<ref>) assigned to <user>` and leave it. A remaining card is this user's crashed run: adopt the first, `add_comment` `🤖 [AGENT] previous run was interrupted — resuming`, read its mode (`references/claiming.md` → Modes), skip to step 7.
4. **Queue.** `list_tasks(board, queue)` incomplete → `$AL order --user <me>` (cards assigned to others drop out; print one `skipped` line each) → walk in order, `get_dependencies` → `$AL gate` per card (`references/claiming.md`). First pass wins. All gated → print `queue blocked — <n> waiting on dependencies` naming each; outcome `blocked-on-deps`. Nothing claimable → list strays (cards on the board in no role column) as `stray — <name> (<ref>) in <column>`; outcome `queue empty`.
5. **Claim.** `move_task(card, board, in_progress)`; `set_field(card, "Assignee", <me>)`; mirror per `references/routing.md` → Mirror rule.
6. **Mode.** `get_comments(card)`: a `🤖 [AGENT] started` marker → **rework**; none → **fresh**. A `🤖 [REVIEW] Changes requested` comment is the review run handing the card back, so it is always rework.
7. **Gate.** Fresh: invoke `agent-loop-readiness` in audit mode. `NOT READY` (a stop condition met) → clarification stop with its question list verbatim, each naming its stop condition. Rework: check the delta (`references/claiming.md` → Rework gate); no actionable delta → stop with the specific reason.
8. **Run.** Invoke `start-task unattended` (`rework` when in rework mode) with the card URL and, in context: the READY verdict (repository path under `repos_root`, base branch, category, non-live proofs, live checks), the mode, and the full card. Wait for its `UNATTENDED VERDICT` block.
9. **Route** the card by the verdict (`references/routing.md`): `shipped` → `in_review`; `clarification` or `failed` → `blocked`. Comment, move, mirror. Every path leaves `in_progress`.
10. **End.** `$AL last-run <key> write <outcome> [--task <ref>] [--detail <text>]` and print one line: `tick complete — <ref> "<name>" → <in_review | blocked | blocked-on-deps | queue empty | unconfigured>`.

Call `$AL last-run <key> start` right after step 1 succeeds, so a runner can see a run in flight.

## What this skill never does

Ask; run a live service; merge or enable auto-merge (the review run in this plugin merges a card's PR into its milestone branch; this run never does); touch `ready`, `done` or any column outside the six roles; touch a card assigned to someone else; claim from a board other than the agent board; delete a worktree; invent work when the queue is empty.

## References

- `references/claiming.md` — ordering, the dependency gate, modes, the rework gate.
- `references/routing.md` — comment shapes, the mirror rule, what goes on the card versus the PR.
- `references/running.md` — how to schedule ticks per runtime; runner-side concerns.
