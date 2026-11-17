# tui

The goals in the terminal: a client of [the service](../serve/README.md), like the web
page, for reading goals and the few things you do to them.

```bash
cond tui            # the goals, waiting ones first; ⏎ opens one
cond tui --status   # the goals, printed (`cond queue list` prints the same, without the service)
```

It needs `cond serve` running (`cond serve install` starts it at login). `COND_URL` or
`COND_PORT` points it at another one.

**The list** shows every repo's goals, each with its parts nested under it: what each is
doing, its plan, round and cost.
Those waiting on you come first, then the running ones; `f` shows the finished ones too.

**A goal** shows what it waits on you for (its questions with their options, or its plan),
the agents running now, and its timeline in phases: each step from its log, with a
round and the tasks it handed out as one step, and each step's cost and time. `⏎` opens a
step: what the lead said, and how each task ended. `L` tails its log.

| Key | |
|---|---|
| `↑` `↓` `j` `k` `g` `G` | move |
| `⏎` `→` `l` | open the goal; on a step, its details |
| `←` `h` `Esc` | back |
| `a` · `A` | answer what it waits on, in a line · in `$VISUAL` / `$EDITOR` |
| `c` | approve the plan it waits on |
| `x` · `r` · `d` | stop it (asks first) · carry it on · mark it done (asks first) |
| `L` | its log, which follows the end until you scroll up |
| `o` · `w` | its PR · the goal on the web page |
| `f` | show or hide finished goals |
| `q` | quit |

Starting goals, settings and undo are on the web page (`w`), or `cond queue`.

## Tests

```bash
python3 -m unittest discover -s tests
```
