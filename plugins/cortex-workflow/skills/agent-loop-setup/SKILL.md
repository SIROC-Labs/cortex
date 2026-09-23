---
name: agent-loop-setup
version: 0.1.0
description: >
  Use when configuring or repairing the agent board an unattended agent loop runs from —
  "set up the agent loop", "/agent-loop-setup", "configure the agent board", "map the agent
  board columns", or when an unattended run reports that its cache is missing or invalid.
  Finds or creates the board through the task-manager interface, maps its columns to the
  six roles, records the repos root and the board's rotation rule, and writes the
  machine-local cache. Attended: it asks. Also "agent-loop-setup check" to validate the
  cache against the live board without asking.
---

# Agent loop setup

Configure the **agent board** (`plugins/cortex-workflow/references/workflow/boards.md` → "The agent board") and write `~/.cortex/agent-loop/<provider>.json` through `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/agent-loop-setup/scripts/agent_loop.py`. One agent board per provider per machine. Every task-manager call goes through the `task-manager` interface.

## Steps

1. **Provider and user.** Resolve the provider through the seam (`resolve_provider.py`; ask when it exits 4). `get_current_user()`. The cache key is `agent_loop.py key <provider>`.
2. **Board.** Ask for a board URL or "create one".
   - URL → `find_task`-style parsing is not for boards; take the board ref from the URL as the provider documents it, then `get_board(board)`.
   - Create → ask for the name; `ensure_board(name, ["Queue", "In Progress", "Blocked", "In Review", "Ready", "Done"])`, then `get_board`.
   - Ask whether the board is a series (a sprint number in its name). Yes → propose a rotation pattern by replacing each run of digits in the name with `(\d+)` and anchoring it (`^…$`, regex-escaped); show it and confirm. No → `rotation: null`.
3. **Roles.** Map the six roles to the board's columns. Names equal to the defaults map automatically. Otherwise list the columns and ask for each unmapped role. Every role maps to a distinct column; refuse otherwise.
4. **Repos root.** Default: the parent of the current repository's top level (`dirname "$(git rev-parse --show-toplevel)"`). Confirm or take the path the operator gives; it must exist.
5. **Write.** Build the cache object (`provider`, `workspace` from the current user's workspace, `board {ref,name}`, `columns`, `column_names`, `rotation`, `repos_root`) and `agent_loop.py write <key> --from-json -`. Print the mapping table, the rotation rule, the cache path, and point at the running guide in `agent-loop-tick/references/running.md`.

Re-running reconfigures from step 2 with the current values as defaults.

## `check` mode

With `check` in the arguments, nothing is asked: `agent_loop.py read <key>` (exit 4 → report "run agent-loop-setup"), then `get_board(board)` and confirm every cached column ref still exists under its cached name. Print `agent board OK — <name>` or the mismatches, and exit. For a runner's pre-flight.

## Rules

- The provider's partial-support signal on `ensure_board`/`ensure_columns` (a provider that cannot create boards) is shown to the operator with the exact board and column names to create by hand; then continue from the URL path.
- Never write a cache the script rejects; fix the mapping instead.
- Nothing here is unattended; the tick never calls this skill, it names it in its stop message.
