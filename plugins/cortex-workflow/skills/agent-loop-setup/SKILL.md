---
name: agent-loop-setup
version: 0.1.0
description: >
  Use when setting up the agent loop from scratch or repairing it — "set up the agent loop",
  "/agent-loop-setup", "configure the agent board", "map the agent board columns", "get the agent
  loop running", or when an unattended run reports that its cache is missing or invalid. Walks the
  operator through four stages: finds or creates the board through the task-manager interface, maps
  its columns to the six roles, records the repos root and the board's rotation rule and writes the
  machine-local cache; runs a pre-flight; authors the first cards; and presents every way to run the
  build and review loops for the operator to start. Attended: it asks. Also "agent-loop-setup check"
  to validate the cache against the live board without asking.
---

# Agent loop setup

Take the operator from nothing to a running loop in four stages: **board → pre-flight → first cards → loops**. The board is the **agent board** (`plugins/cortex-workflow/references/workflow/boards.md` → "The agent board"); the cache is `~/.cortex/agent-loop/<provider>.json`, written through `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/skills/agent-loop-setup/scripts/agent_loop.py`. One agent board per provider per machine. Every task-manager call goes through the `task-manager` interface.

Announce each stage by name as it starts. The operator may skip any stage after the first.

## Entry

Resolve the provider through the seam (`resolve_provider.py`; ask when it exits 4) and `get_current_user()`. The cache key is `agent_loop.py key <provider>`. `agent_loop.py read <key>`: exit 4 → stage 1. A cache that reads → run the stage 2 board check; OK → print the board and ask whether to reconfigure it (stage 1 with the cached values as defaults) or continue from stage 3.

## Stage 1 — Board

1. **Board.** Ask for a board URL or "create one".
   - URL → `find_task`-style parsing is not for boards; take the board ref from the URL as the provider documents it, then `get_board(board)`.
   - Create → ask for the name; `ensure_board(name, ["Queue", "In Progress", "Blocked", "In Review", "Ready", "Done"])`, then `get_board`.
   - Ask whether the board is a series (a sprint number in its name). Yes → propose a rotation pattern by replacing each run of digits in the name with `(\d+)` and anchoring it (`^…$`, regex-escaped); show it and confirm. No → `rotation: null`.
2. **Roles.** Map the six roles to the board's columns. Names equal to the defaults map automatically. Otherwise list the columns and ask for each unmapped role. Every role maps to a distinct column; refuse otherwise.
3. **Repos root.** Default: the parent of the current repository's top level (`dirname "$(git rev-parse --show-toplevel)"`). Confirm or take the path the operator gives; it must exist.
4. **Write.** Build the cache object (`provider`, `workspace` from the current user's workspace, `board {ref,name}`, `columns`, `column_names`, `rotation`, `repos_root`) and `agent_loop.py write <key> --from-json -`. Print the mapping table, the rotation rule and the cache path.

## Stage 2 — Pre-flight

Nothing is asked; each line prints `ok` or the failure with its fix.

- **Board**: the `check` mode below. A mismatch returns to stage 1; the later stages need a valid board.
- **Fields**: `list_fields(board)` has `Priority` and `Type / Category` (a provider that realizes the category as a native issue type has it). Missing → name the field and say the operator adds it on the board: the queue orders by `Priority`, and the category routes bug-fix versus feature work.
- **GitHub**: `gh auth status` exits 0. Otherwise → the operator runs `gh auth login`.

A failed field or GitHub line does not stop the flow; the operator fixes it before the loops start, and stage 4 repeats any line still failing.

## Stage 3 — First cards

Ask whether to author cards now. Yes → ask for the input (a URL, a file path, pasted text or a one-line idea) and invoke `agent-loop-author` with it; it asks its own questions and returns here when the cards are on the queue. No → print `/agent-loop-author <input>` for later, and continue.

## Stage 4 — Loops

Present the ways to run the loop from `skills/agent-loop-tick/references/running.md` that are possible here: the current runtime's column of its ways table, and the agterm session only on macOS with `agtermctl` on `PATH`. For each, its step-by-step instructions and templates in full, with this machine's values filled in (`<repos_root>`, `<key>`, the runtime binary's directory, `<home>`) and the current runtime's variant of every command. Open with "By hand" as the first run to watch, and close with that file's "What every way must keep".

Say plainly that the operator sets up and starts the loops themselves, each in a session of its own and never in this one. This skill runs no tick, starts no loop, writes no file from a template and installs no scheduler entry. End with the cache path and one line naming what remains undone: stages skipped and pre-flight lines still failing.

## `check` mode

With `check` in the arguments, nothing is asked: `agent_loop.py read <key>` (exit 4 → report "run agent-loop-setup"), then `get_board(board)` and confirm every cached column ref still exists under its cached name. Print `agent board OK — <name>` or the mismatches, and exit. For a runner's pre-flight.

## Rules

- The provider's partial-support signal on `ensure_board`/`ensure_columns` (a provider that cannot create boards) is shown to the operator with the exact board and column names to create by hand; then continue from the URL path.
- Never write a cache the script rejects; fix the mapping instead.
- Nothing here is unattended; the ticks never call this skill, they name it in their stop message.
