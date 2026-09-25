# Running the loop

The plugin ships no scheduler. A tick is one non-interactive invocation of `/agent-loop-tick`; how often it runs, and from where, is the operator's. `agent-loop-setup check` is a cheap pre-flight that validates the cache against the live board without asking.

## One tick, per runtime

| Runtime | One tick |
|---|---|
| Claude Code | `claude -p '/agent-loop-tick' --permission-mode auto` |
| OpenCode | `opencode run '/agent-loop-tick'` |
| Codex | `codex exec '/agent-loop-tick'` |

Run the command from a directory the agent already trusts (a parent of the repositories under `repos_root`), so no trust prompt blocks the run.

## Repeating it

- **cron / launchd / systemd timer** — call the one-tick command hourly. Redirect output to a log; the tick's last line is its verdict.
- **A long-lived interactive session** — Claude Code: `/loop 1h /agent-loop-tick`. Each tick must start with a clear context (`/clear` first, or a fresh session), because inheriting the previous card's context is how one task silently adopts another's assumptions.
- **A cloud routine** — Claude Code: `/schedule` an hourly routine whose prompt is `/agent-loop-tick`; the environment needs the plugin, the task-manager transport (token or Asana MCP) and `gh` authenticated.

## Runner-side concerns the skill cannot own

- **Single flight.** One tick at a time. Use a lock file around the command, or check `~/.cortex/agent-loop/<key>.last-run.json`: `outcome: "running"` with a recent `started` means a run is in flight. Two concurrent ticks would both read the queue before either claims.
- **Fresh context per tick.** See above.
- **Cheap pre-flight.** Before paying for a full run: `agent-loop-setup check`, then read the cache and `list_tasks(board, queue)` / `list_tasks(board, in_progress)` with a small model; no incomplete cards in either → skip the tick.
- **Permissions.** The run must not stop on a permission prompt; grant what the tick needs (shell, git, `gh`, the task-manager transport, the browser MCP for rung 5) up front.
- **Stuck runs.** A `running` outcome older than your ceiling (a few hours) is wedged. Warn a human; do not kill it blind, the card stays claimed either way and the next tick adopts it.
- **Cost.** A tick that finds nothing costs a model call; the pre-flight above is how you avoid paying it hourly.
