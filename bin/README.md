# cortex

A dispatcher for the command-line tools in this directory.

```
cortex <tool> [args...]
```

It adds no commands of its own — everything after the tool name belongs to the tool.
Its one job is to find the tool and run it with the right Python, so a tool with its
own `.venv` gets that interpreter no matter where you called `cortex` from.

## Install

```bash
bash ../setup-path.sh          # adds CORTEX_HOME + PATH to ~/.zshrc (or ~/.bashrc)
bash ../setup-path.sh --check  # report what's set, change nothing
```

Then reload your shell. Nothing is copied or symlinked outside the clone, so if you
move or rename the clone, re-run it.

## Use

```bash
cortex                  # list the tools
cortex <tool> --help    # a tool's own arguments
```

| Tool | What it does |
|---|---|
| [`start-task`](start-task/README.md) | Runs the start-task lifecycle — ticket to draft PR — as a program rather than a skill |

Run tools from inside the repo you want them to act on.

## Adding a tool

Make a directory named after the tool, with an entrypoint of the same name and
underscores instead of dashes:

```
bin/my-tool/my_tool.py
```

The dispatcher picks it up automatically. Two conventions:

- **Summary line.** Put `# my-tool — one line about it` in the first few lines of the
  entrypoint. That's what `cortex` prints in the tool list.
- **Dependencies.** If the tool needs packages, create `bin/my-tool/.venv`. The
  dispatcher uses it when it exists and falls back to `python3` when it doesn't.
