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
| commands | `:` — the command palette (below) |
| help | `?` |

## The command palette

`:` opens it. It holds only the commands that are not already in plain sight — none
whose key is shown in the line at the bottom of the screen — and only those that can
run right now. On the Runs tab, with a task whose PR is not on the target branch, that
is *Change HCI-8's PR base branch to feature/x*; from any tab but Daemons, starting or
stopping this repo's daemon. Type to narrow it (it also matches the words you would use
— *retarget*, *move*, *update*, *base*), `↑↓` or `^P ^N` to choose, `⏎` to run, `Esc`
to close.

## Typing

Every text input — the palette, the `/` filter, an answer, a new branch name — takes
the usual line-editing keys, and none of them sets off a hotkey while you type:

| | |
|---|---|
| start / end of the line | `^A` `^E` · Home End |
| a character back / forward | `^B` `^F` · `←` `→` |
| a word back / forward | `Alt-B` `Alt-F` |
| delete to the end / to the start | `^K` `^U` |
| delete the word before the cursor | `^W` |
| delete forward / back | `^D` Delete / Backspace |

## Tabs

| Tab | What it shows | Keys |
|---|---|---|
| **1 Runs** | every queued task — those waiting on you first, flagged ⚑ — with its state and PR and task links; then any live start-task run this repo's daemon does not own | `⏎` what it is waiting on (or its log) · `a` answer · `A` answer in `$EDITOR` · `m` merge · `x` stop and unqueue · `r` retry a failed or stopped task · `o` open the PR (or task) |
| **2 Boards** | every board in the workspace; open one to see its sections and tasks | `space` queue or unqueue a task, or on a section queue all of it · `R` reload |
| **3 Setup** | the sprint queued tasks are added to, the branch new work targets, and whether PRs are merged | `⏎` change one |
| **4 Daemons** | every daemon on this machine, with its health and live runs | `s` start this repo's · `x` stop one · `d` clear a crashed one's entry |

Queueing the first task starts the daemon if it is not running. Nothing starts until
a sprint is picked; nothing about the sprint is guessed.

## Setup

Settings are per repo: they live in the repo's `.cortex/queue/`, beside its queue and
its daemon.

- **Sprint** — the board queued tasks are added to.
- **Target branch** — the branch new runs branch off and open their PR against; the
  repo's default branch unless you pick another. The list is origin's branches (`/`
  searches it). Its first row, **+ New branch…** (or `n`), asks for a name — any
  characters, `/` included — and creates it on origin from `origin/<default>` once you
  confirm — fetched first, so it starts at what is on GitHub, never at a local copy
  that may be behind or carry unpushed commits; it is a push. PRs already open keep the base they have — *Change …'s PR base branch to …* in
  the command palette moves one onto the current target, after counting any commits the move would drag in (ones its
  old base has that the target does not) and asking. From then on it merges by the
  rules for its new base. The UI's git calls
  never prompt: if SSH needs a passphrase or a new host key, the call fails and says
  so instead of taking over the terminal.
- **Merging** — when a shipped PR is merged without you asking; `⏎` cycles:
  - *automatically, unless it targets the default branch* (the default, and the
    recommendation): a PR into `milestone/m1` lands by itself, one into `main` waits
    for `m`;
  - *always automatically*, the default branch included;
  - *only when asked* — only `m` merges.

  `m` works in every mode. An automatic merge is exactly what `m` does, conflicts and
  failing checks included; `m` on one calls it off, and it stays off for that task.

## What each row says

The status next to a task says what is happening to that task now, not just its phase:

- a command of yours the daemon has not acted on yet — *base branch change to
  feature/m1 asked — waiting for the daemon*;
- something the daemon is in the middle of for it — *changing HCI-8's PR base branch to
  feature/m1…*, *finishing HCI-8 in Asana…*, *removing HCI-8's worktree…*;
- for a running task, its current step from its log, what it is waiting on and for how
  long — *running — Implementing · agent at work · 12m*, *running — QA · make verify · 3m*;
- for an open PR, what it waits for — *PR open — waiting for review; m merges*;
- and when it waits on you, what that asks of you (below).

## Waiting on you

A run that needs you — the agent's questions, QA still red after its repairs, a refused
push, a stalled call, a failed step — and a PR parked on a conflict all show on the Runs
tab first, flagged ⚑, and the header counts them. `⏎` shows the whole of it: every
question with its reasoning, or the problem with the output that caused it.

- `a` answers in one line at the bottom of the screen; `A` opens `$VISUAL` / `$EDITOR`
  with the questions as `#` comments, like `git commit`.
- The answer is handed straight to the waiting run, which looks for one every second,
  and is posted to the task in Asana as your comment, so the conversation stays where
  it was asked. A run that is not alive when you answer finds it when it starts again.
- On a parked conflict, `a` asks for a resolve: it posts `please resolve` on the PR,
  which the loop picks up within a minute.

Answering on the task in Asana still works exactly as before.

## Merge

`m` on a task means "get this onto its target branch". It can be pressed at any point — on an open
PR, a parked conflict, or a run still going (it merges once the PR is up) — and from
then on the PR is driven until it lands, checked every 15 seconds:

| GitHub says | The run |
|---|---|
| ready to merge | merges, with a method the repo and its rules allow (squash first) |
| conflicts with the base | revises: merges the base in and resolves them — never a rebase or force-push |
| behind the base | updates the branch |
| checks running | waits — every check, not only the ones the branch's rules require |
| a check failed | revises to fix it, or re-runs it when it is plainly a flake |
| a draft | marks it ready |

Review comments that arrive after you press `m` are not acted on — you said go. When
siblings are merged together, each one that lands may leave the next conflicting; that
one resolves and goes on. It stops and waits on you (⚑, with the reason) after three
rounds of conflicts or two failed fixes of a check, or when something other than a check
blocks it (a required review, say); `m` tries again from wherever the PR stands. `m` on
a merge in progress calls it off.

## Asana data and its cache

Nothing waits on the network to draw. Boards and their sections are cached in
`$XDG_CACHE_HOME/cortex/asana/` (`~/.cache/cortex/asana/` by default) and shown at
once, with their age at the right of the breadcrumb (`updated 4m ago`). When the copy
is older than the view tolerates, Asana is re-read in the background — a spinner says
so, you can keep moving or leave the view, and the screen updates when it lands:

| View | Re-read when the copy is older than |
|---|---|
| a board, when you open it | 30 seconds |
| a board, while it is on screen | 1 minute |
| the list of boards | 5 minutes |

`R` re-reads whatever is shown, now. What the daemon knows — a task it merged, a
run in flight — is laid over the cached board, so the parts that change most are
never stale. The cache is only ever a copy; deleting it costs one slower first look.

## No ghost runs

- Every daemon registers in `~/.cortex/cli/daemons/`, so the Daemons tab — from any
  terminal, in any repo — lists them all. A daemon that died uncleanly shows as
  `crashed`, with how many of its runs are still going.
- Stopping a daemon stops the runs it launched.
- Every live `start-task` process in the repo shows on the Runs tab whether or not
  the daemon owns it — a hand run, a `run-milestone` loop, an orphan of a crashed
  daemon — and `x` stops it. A restarted daemon adopts an orphan of its own instead
  of starting it again.
- Every run is started in its own process group, and stopping it stops the group —
  its agent and QA commands too, not just the run. An agent still working in one of
  the repo's worktrees with no run over it (one left by a run killed some other way)
  is listed on the Runs tab as well, and `x` stops it.

## Updates

The daemon restarts itself onto new code — after a `git pull`, say — at the first
moment no run is in flight, so nothing is interrupted; until then the header says it
will update once its runs finish. Every command the TUI sends (merge, stop, retry) is
followed until the daemon acts on it, and the TUI says if it was not understood or not
picked up.

## Files

`<repo>/.cortex/queue/`:

- `control.json` — written by the TUI: the queue, the sprint, and stop/retry commands
- `state.json` — written by the daemon: what it last read of each task, and each run's
  record
- `daemon.json` — the daemon's pid and heartbeat; `daemon.log` — its output
- `logs/`, `results/`, `feedback/` — per run, as in `run-milestone`

## Tests

```bash
python3 tests/test_pure.py   # queue, daemon health, unowned runs, rows, keys, cache
```
