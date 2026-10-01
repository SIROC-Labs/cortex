# tui

Browse boards, queue tasks, and watch the runs that work them — in the terminal.

```bash
cortex tui                  # from inside the target repo
cortex tui --status         # the queue and the daemon, printed; no UI
cortex tui --stop           # stop this repo's daemon and the runs it launched
cortex tui --backend echo   # any other flag goes to every start-task run
```

The work is done by a background daemon, one per repo, through the same engine as
[`run-milestone`](../run-milestone/README.md): a queued task starts through
[`start-task`](../start-task/README.md) once every dependency is complete — queued or
not — and its PR is watched to merge. Closing the TUI leaves the daemon working;
opening it again, from any terminal, picks up where it is.

## Keys

The same everywhere a list is shown — arrows, vi and emacs keys all work:

| | |
|---|---|
| move | `↑` `↓` · `j` `k` · `Ctrl-N` `Ctrl-P` |
| page / half page | `PgDn` `PgUp` · `Ctrl-F` `Ctrl-B` / `Ctrl-D` `Ctrl-U` |
| top / end | `Home` `End` · `g` `G` |
| in | `⏎` · `→` · `l` — open a board, a run's log |
| out | `←` · `h` · `Esc` · `⌫` — clear the filter, then leave the board |
| tabs | `1`–`4` (or `Alt-1`–`4`) straight to one; the current tab's number again takes it back to its top. `Tab` / `Shift-Tab` cycle |
| filter | `/`, then type — `⏎` keeps it, `Esc` clears it |
| help | `?` |

## Tabs

| Tab | What it shows | Keys |
|---|---|---|
| **1 Runs** | every queued task: its state, PR and task links, the question or problem it is waiting on — then any live start-task run this repo's daemon does not own | `⏎` its log · `x` stop and unqueue · `r` retry a failed or stopped task · `o` open the PR (or task) |
| **2 Boards** | every board in the workspace; open one to see its sections and tasks | `space` queue or unqueue a task, or on a section queue all of it · `R` reload |
| **3 Sprint** | the boards again — pick the one queued tasks are added to | `⏎` use it |
| **4 Daemons** | every daemon on this machine, with its health and live runs | `s` start this repo's · `x` stop one · `d` clear a crashed one's entry |

Queueing the first task starts the daemon if it is not running. Nothing starts until
a sprint is picked; nothing about the sprint is guessed.

## No ghost runs

- Every daemon registers in `~/.cortex/cli/daemons/`, so the Daemons tab — from any
  terminal, in any repo — lists them all. A daemon that died uncleanly shows as
  `crashed`, with how many of its runs are still going.
- Stopping a daemon stops the runs it launched.
- Every live `start-task` process in the repo shows on the Runs tab whether or not
  the daemon owns it — a hand run, a `run-milestone` loop, an orphan of a crashed
  daemon — and `x` stops it. A restarted daemon adopts an orphan of its own instead
  of starting it again.

## Files

`<repo>/.cortex/queue/`:

- `control.json` — written by the TUI: the queue, the sprint, and stop/retry commands
- `state.json` — written by the daemon: what it last read of each task, and each run's
  record
- `daemon.json` — the daemon's pid and heartbeat; `daemon.log` — its output
- `logs/`, `results/`, `feedback/` — per run, as in `run-milestone`

## Tests

```bash
python3 tests/test_pure.py   # queue and commands, daemon health, unowned runs, tab rows
```
