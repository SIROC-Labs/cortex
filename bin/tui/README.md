# tui

Browse boards, start goals on tickets, and watch them work — in the terminal.

```bash
cond tui                  # from inside the target repo
cond tui --status         # the goals, printed; no UI (`cond queue list` prints the same)
```

A goal is a ticket that runs by itself, with no breakdown and no queue: it works on its
own branch, into one PR, and asks you only what it cannot decide. Each goal runs in a
process of its own, so closing the TUI leaves it working; opening it again, from any
terminal, shows where it is. See [the goal tool](../goal/README.md) for how a goal works.

## Tabs

| Tab | What it shows | Keys |
|---|---|---|
| **1 Runs** | every goal and its parts — those waiting on you first, flagged ⚑ — with what each is doing, its round, its usage and cost, and how far its plan and criteria are | `⏎` what it is waiting on, or its live view · `a` answer · `A` answer in `$EDITOR` · `c` approve its plan · `x` stop — or, on a finished goal, remove it from the list · `r` carry it on · `o` open its PR · `u` what each agent cost · `d` mark it done |
| **2 Boards** | every board in the workspace that is neither archived nor marked complete; open one to see its sections and tasks — each with its ID, faint, when it has one — and how many subtasks each has (▸ 3 subtasks); a milestone shows ◈ | `:` *Run … as a goal* on a task or a milestone · `→` `l` `⏎` on a task with subtasks shows them, `←` `h` hides them · `o` open the task (or board) in Asana · `R` reload |
| **3 Setup** | the branch goals go into, whether done tasks show, the usage limit, the goals' models, and who approves their plans | `⏎` change one: pick it from a list, or type the usage limit · `n` new branch, in the branch list |

Anything that waits on you opens in the same box as the command palette, in the middle
of the screen: a yes/no question (`y` yes, any other key no), a line to type (an answer, a
new branch, the usage limit), or a list to pick from (a Setup choice). The bottom line only
says what happened.

## Keys

The same everywhere a list is shown — arrows, vi and emacs keys all work:

| | |
|---|---|
| move | `↑` `↓` · `j` `k` · `Ctrl-N` `Ctrl-P` (`Ctrl-K` too) |
| page / half page | `PgDn` `PgUp` · `Alt-N` `Alt-B` / `Ctrl-D` `Ctrl-U` |
| top / end | `Home` `End` · `g` `G` |
| in | `⏎` · `→` · `l` (`Ctrl-L` too) — open a board, a goal's question or live view, a setting |
| out | `←` · `h` · `Esc` · `⌫` — clear the filter, then leave the board |
| tabs | `1`–`3` (or `Alt-1`–`3`) straight to one; the current tab's number again takes it back to its top. `Tab` / `Shift-Tab` cycle |
| filter | `/`, then type — `⏎` keeps it, `Esc` clears it |
| commands | `:` — the command palette (below) |
| help | `?` |

## The command palette

`:` opens it. It holds only the commands that are not already in plain sight — none
whose key is shown in the line at the bottom of the screen — and only those that can
run right now:

- on a board's task or milestone, *Run … as a goal on …* — the branch is **Queue into**;
- on a goal, *Discuss the goal …* and *Undo the goal …*;
- on the Runs tab, once some are done, *Clear N done goals from the list*;
- everywhere, *Hide done tasks* / *Show done tasks*.

Type to narrow it (it also matches the words you would use), `↑↓` or `^P ^N` to choose,
`⏎` to run, `Esc` to close.

## Goals

On a board, select a task or a milestone and pick *Run … as a goal* in the palette. It
starts at once, on its own branch made from **Queue into**, and ends as one PR into that
branch. A ticket that is already a goal says so instead. The goal reads the ticket, its
open subtasks, its comments and its attachments once, when it starts. It puts its
questions and its plan on the ticket as subtasks, in three sections, *Questions*,
*Review* and *Execution*, and does not merge anything.

A goal is a row on the Runs tab: what it is doing, its round, and the highest usage of
your Claude limits. It pauses by itself while any limit is at the **Usage limit** or more,
and carries on when the limit resets. When it asks you something, the row is flagged ⚑,
and the header counts it:

- `⏎` shows the whole of it: every question with its reasoning, or the problem with the
  output that caused it.
- `a` answers in one line; `A` opens `$VISUAL` / `$EDITOR` with the questions as `#`
  comments, like `git commit`. The answer is handed straight to the goal, which looks for
  one every second. You can also answer in Asana, on each question's subtask.
- When its plan is ready, the row says so and nothing is built until you approve it: `c`
  approves it, `a` says what to change, or complete *Review the plan* in Asana. A goal
  split into parts asks for *Review the split* first, the same way.

`x` stops a running goal and `r` carries it on from where it stopped; on a finished goal,
`x` takes it off the list. `d` marks a goal done by hand: it and its parts stop, and it no
longer watches its PR. Its branch, PR and ticket stay as they are.

*Undo the goal* in the palette takes all of it back out — its PR, its branches, its
worktrees and state, and every subtask it made on the ticket — after saying what it will
do and asking. *Discuss the goal* opens a Claude session in its worktree that has read its
journal, its open questions and its log, and says so in a few lines when it opens, to talk
it through: it may write and run scratch files (scripts, drafts, diagrams) in a temp
folder, and a hook refuses any other change: no repository files, no git writes, no Asana
writes. Edits are accepted without asking; shell commands still ask you. In Ghostty on
macOS it opens in a new tab; in another terminal it takes the TUI's screen, and the TUI
comes back when you leave it.

A goal split into parts has them on the rows below it, indented (`└ API`), each with its
own state; the goal's row says how many parts are done and which are being built, and its
cost includes theirs. A part's question waits on its own row. `⏎`, `x` and `r` work on a
part as on a goal; stopping the goal stops its parts.

`⏎` on a goal opens its live view, re-read every two seconds from Claude Code's own
transcripts: the stage it is at (analysis ▸ review ▸ building ▸ syncing ▸ CI ▸ checking ▸
done), how many of the lead's acceptance criteria are met and which are not yet, how far
the lead's checklist under `## Plan` in its journal is, with the next step, what the lead
(or the reviewer, the checker, or a CI fix) is doing now and last said, each sub-agent with
its task, model and time, the running ones with what they are doing, and the end of the
goal's journal. `l` opens its log and `u` what each agent cost.

A finished goal whose PR is merged or closed on GitHub learns so in the background and
leaves the list as a watched one does.

## Setup

Settings are per repo: they live in the repo's `.cortex/queue/control.json`. Keys other
tools left there are kept as they are.

- **Queue into** — the branch goals go into: a new goal branches off it and opens its PR
  against it. The repo's default branch unless you pick another. A goal already started
  keeps its own. The list is origin's branches (`/` searches it). Its first row, **+ New
  branch…** (or `n`), asks for a name — any characters, `/` included — and creates it on
  origin from `origin/<default>` once you confirm — fetched first, so it starts at what is
  on GitHub, never at a local copy that may be behind or carry unpushed commits; it is a
  push. The UI's git calls never prompt: if SSH needs a passphrase or a new host key, the
  call fails and says so instead of taking over the terminal.
- **Done tasks** — shown or hidden; `⏎` toggles, as do *Hide done tasks* / *Show done
  tasks* in the palette. Hidden, boards leave out completed tasks (and sections with
  nothing else), and Runs leaves out goals that are done — except one still waiting on you.
- **Usage limit** — the share of any Claude usage limit at which goals wind down and
  pause, until it resets: 75% by default; `⏎` and type a percentage, 1 to 100. Running
  goals read it at their next usage check, so raising it lets one finish its work.
- **Models** — `⏎` on each lists its choices, with what each is for (haiku, sonnet, opus,
  fable; effort low to max), and `⏎` picks one: *Goal lead*, *Goal sub-agents*, *Goal
  checker*, *Checker effort* — opus, sonnet, opus and high by default. The checker also
  reviews each plan before it is built. A goal keeps the models it started with; the checker
  effort applies from each goal's next check. Planning and fixing stay with the lead and its
  sub-agents.
- **Plan approval** — who approves a goal's plan before it is built: you, for the goal
  and each of its parts (the default); you for the goal and the reviewer agent for its
  parts; or the reviewer agent only. For goals started from then on.

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

`R` re-reads whatever is shown, now. The cache is only ever a copy; deleting it costs one
slower first look.

## Tests

```bash
python3 -m unittest discover -s tests -q   # rows, goals, waits, keys, setup, cache
```
