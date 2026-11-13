# cond

A dispatcher for the command-line tools in this directory.

```
cond <tool> [args...]
```

It adds no commands of its own — everything after the tool name belongs to the tool.
Its one job is to find the tool and run it with the right Python, so a tool with its
own `.venv` gets that interpreter no matter where you called `cond` from.

## Why

The skills in `plugins/` are prose a model reads and acts on one step at a time. That is
the right shape for work that needs judgment. Most of a workflow is not that: parsing a
URL, checking a field, cutting a branch, opening a draft PR, posting a fixed comment.
Handing those to a model costs a round-trip each, and it gets them wrong often enough
that the skills are full of shouty warnings trying to talk it out of skipping steps.

The tools here invert that. Control flow is code, so the deterministic parts are fast,
free, and identical on every run. A model is called only where one is genuinely needed.
Every ticket runs as a goal: a lead agent analyses it, plans it, and builds it through
its own coding agents, on one branch, into one PR. Tiny work skips the plan review.

## Install

```bash
bash ../setup-path.sh          # adds CONDUCTOR_HOME + PATH to ~/.zshrc (or ~/.bashrc)
bash ../setup-path.sh --check  # report what's set, change nothing
```

Then reload your shell. Nothing is copied or symlinked outside the clone, so if you
move or rename the clone, re-run it.

### Coming from `cortex`

The command was `cortex`; it is now `cond`. Goals' state stays where it was, in
`<repo>/.cortex/`, so running goals carry on. start-task, run-milestone and the daemon
are gone: every ticket runs as a goal.

1. Stop the old daemons (`cortex tui --stop` in each repo). Tasks still in their queue
   do not start; finish or close their open PRs by hand.
2. Run `bash ../setup-path.sh`, delete the old `CORTEX_HOME` lines it points out, and
   open a new terminal.
3. Open the TUI from the new terminal (`cond tui`).

Comments the old runs posted (`🤖 cortex ·`) and subtasks the old goals planned are still
recognised as the runs' own.

## Use

```bash
cond                    # list the tools
cond <tool> --help      # a tool's own arguments
```

| Tool | What it does |
|---|---|
| [`goal`](goal/README.md) | Implements an Asana ticket by itself — a lead agent with its own sub-agents — on one branch, into one PR |
| [`tui`](tui/README.md) | Browse boards, start goals on tickets and watch them work |
| [`queue`](queue/README.md) | Starts goals from the command line, as the TUI does — for scripts and other agents |

Run tools from inside the repo you want them to act on. `lib/` is not a tool: it holds
what the tools share (git, Asana, a goal's state, CI, the settings file).

## Adding a tool

Make a directory named after the tool, with an entrypoint of the same name and
underscores instead of dashes:

```
bin/my-tool/my_tool.py
```

The dispatcher picks it up automatically. Two conventions:

- **Summary line.** Put `# my-tool — one line about it` in the first few lines of the
  entrypoint. That's what `cond` prints in the tool list.
- **Dependencies.** If the tool needs packages, create `bin/my-tool/.venv`. The
  dispatcher uses it when it exists and falls back to `python3` when it doesn't.
