# Running the loop

The plugin ships no scheduler. The loop is two kinds of tick, each one non-interactive invocation: the **build tick** (`/agent-loop-tick`) takes a card from the queue, and the **review tick** (`/agent-loop-review-tick`) takes a card from in-review and merges it into its milestone branch. How often they run, and from where, is the operator's. `agent-loop-setup check` is a cheap pre-flight that validates the cache against the live board without asking.

## One tick, per runtime

| Runtime | Build tick | Review tick |
|---|---|---|
| Claude Code | `claude -p '/agent-loop-tick' --permission-mode auto` | `claude -p '/agent-loop-review-tick' --permission-mode auto` |
| OpenCode | `opencode run '/agent-loop-tick'` | `opencode run '/agent-loop-review-tick'` |
| Codex | `codex exec '/agent-loop-tick'` | `codex exec '/agent-loop-review-tick'` |

Run the command from a directory the agent already trusts (a parent of the repositories under `repos_root`), so no trust prompt blocks the run. Alternate the two kinds, review first: a merged card frees dependents in the queue and a handed-back card is rework the next build tick should see.

## Repeating it

- **cron / launchd / systemd timer** — call the review tick, then the build tick, hourly. Redirect output to a log; each tick's last line is its verdict.
- **A long-lived interactive session** — Claude Code: `/loop 1h /agent-loop-review-tick` and `/loop 1h /agent-loop-tick`, offset. Each tick must start with a clear context (`/clear` first, or a fresh session), because inheriting the previous card's context is how one task silently adopts another's assumptions.
- **A cloud routine** — Claude Code: `/schedule` hourly routines whose prompts are `/agent-loop-review-tick` and `/agent-loop-tick`; the environment needs the plugin, the task-manager transport (token or Asana MCP) and `gh` authenticated.

## Runner-side concerns the skill cannot own

- **Single flight, across both kinds.** One tick at a time on this machine, build or review, under one lock file; both mutate the board and the repositories. Or check `~/.cortex/agent-loop/<key>.last-run.json` (build) and `<key>.review.last-run.json` (review): `outcome: "running"` with a recent `started` means a run is in flight. Two concurrent ticks would both read a column before either claims. Other people's ticks on the same board are safe: each takes only its own or unassigned cards.
- **Fresh context per tick.** See above.
- **Cheap pre-flight.** Before paying for a full run: `agent-loop-setup check`, then read the cache and `list_tasks(board, queue)` / `list_tasks(board, in_progress)` (build) or `list_tasks(board, in_review)` (review) with a small model; no incomplete card unassigned or assigned to this user → skip the tick.
- **Permissions.** The run must not stop on a permission prompt; grant what the tick needs (shell, git, `gh`, the task-manager transport, the browser MCP for rung 5) up front.
- **Stuck runs.** A `running` outcome older than your ceiling (a few hours) is wedged. Warn a human; do not kill it blind, the card stays claimed either way and the next tick adopts it.
- **Cost.** A tick that finds nothing costs a model call; the pre-flight above is how you avoid paying it hourly.
