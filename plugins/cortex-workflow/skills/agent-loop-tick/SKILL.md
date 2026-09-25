---
name: agent-loop-tick
version: 0.1.0
description: >
  Use when invoked as /agent-loop-tick by a scheduler, or when the user asks to run one task
  from the agent board. Takes exactly one card from the board's queue, gates it, runs it
  through start-task in unattended mode, and routes the card to in-review or blocked. Never
  asks the operator a question, never runs a live service, never merges. An empty queue ends
  the run.
---

# Agent loop tick

Take **one** card off the agent board, execute it, route it. `AL=${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/agent-loop-setup/scripts/agent_loop.py`. Every task-manager call goes through the `task-manager` interface.

## The prime directive

**This run is unattended. Never ask a question and wait.** Every decision comes from the card, from the readiness verdict, or from `plugins/cortex-workflow/references/unattended-answers.md`. Anything else is a **clarification stop** (`references/routing.md`). If you are about to write "Should I…", stop and route instead.

## Flow

Each step is idempotent so an interrupted run can be adopted by the next one.

1. **Load.** `$AL key <provider>` → `$AL read <key>`. Exit 4 → print `agent loop not configured — run agent-loop-setup`, go to step 10 with outcome `unconfigured`.
2. **Rotate.** With a rotation pattern: `list_boards()` → `$AL rotate <key> --from-json -`. `rotate: true` → `get_board(new)`, re-map every role by its cached `column_names` (a missing name → print `board <name> lacks column <name> — run agent-loop-setup`, outcome `unconfigured`), `$AL write`, print `rolled to <name>`. Then `list_tasks(previous, queue)`; print `left behind — <name> (<ref>) on <previous>` per incomplete card. Never claim from the previous board.
3. **Orphan.** `list_tasks(board, in_progress)`. A card there is a crashed run: adopt the first, `add_comment` `🤖 [AGENT] previous run was interrupted — resuming`, read its mode (`references/claiming.md` → Modes), skip to step 7.
4. **Queue.** `list_tasks(board, queue)` incomplete → `$AL order` → walk in order, `get_dependencies` → `$AL gate` per card (`references/claiming.md`). First pass wins. All gated → print `queue blocked — <n> waiting on dependencies` naming each; outcome `blocked-on-deps`. Empty → list strays (cards on the board in no role column) as `stray — <name> (<ref>) in <column>`; outcome `queue empty`.
5. **Claim.** `move_task(card, board, in_progress)`; `set_field(card, "Assignee", <current user>)`; mirror per `references/routing.md` → Mirror rule.
6. **Mode.** `get_comments(card)`: a `🤖 [AGENT] started` marker → **rework**; none → **fresh**.
7. **Gate.** Fresh: invoke `agent-loop-readiness` in audit mode. `NOT READY` → clarification stop with its question list verbatim. Rework: check the delta (`references/claiming.md` → Rework gate); no actionable delta → stop with the specific reason.
8. **Run.** Invoke `start-task unattended` (`rework` when in rework mode) with the card URL and, in context: the READY verdict (repository path under `repos_root`, base branch, category, non-live proofs, live checks), the mode, and the full card. Wait for its `UNATTENDED VERDICT` block.
9. **Route** the card by the verdict (`references/routing.md`): `shipped` → `in_review`; `clarification` or `failed` → `blocked`. Comment, move, mirror. Every path leaves `in_progress`.
10. **End.** `$AL last-run <key> write <outcome> [--task <ref>] [--detail <text>]` and print one line: `tick complete — <ref> "<name>" → <in_review | blocked | blocked-on-deps | queue empty | unconfigured>`.

Call `$AL last-run <key> start` right after step 1 succeeds, so a runner can see a run in flight.

## What this skill never does

Ask; run a live service; merge or enable auto-merge; touch `ready`, `done` or any column outside the six roles; claim from a board other than the agent board; delete a worktree; invent work when the queue is empty.

## References

- `references/claiming.md` — ordering, the dependency gate, modes, the rework gate.
- `references/routing.md` — comment shapes, the mirror rule, what goes on the card versus the PR.
- `references/running.md` — how to schedule ticks per runtime; runner-side concerns.
