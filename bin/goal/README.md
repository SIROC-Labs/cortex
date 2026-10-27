# goal

An ask, implemented by itself, on one branch, into one PR.

```bash
cortex goal new --ask "Add CSV export to the reports page" --base feature/reports --start
cortex goal new --ask-file ask.md            # build on the default branch; start it later
cortex goal run goal-1027-1432-add-csv-export   # run or resume one in the foreground
```

The usual way in is the TUI: *New goal* in its palette (`:`). The goal then shows on the
Runs tab, where you answer it, stop it and carry it on.

## How it works

A **lead agent** gets the ask and nothing more. It plans the work, keeps a journal, and
starts its own sub-agents, reviewers and checkers as it sees fit. It commits on the goal's
branch as it goes. Nobody breaks the work down for it, and nothing goes to Asana.

This program is the harness around the lead:

- **Rounds.** The lead is called on one session, in rounds of up to 200 turns. After each
  round the branch is pushed, and the next round continues the same conversation. If the
  session is lost, a new one starts from the journal and the branch.
- **Questions.** The lead asks only what it cannot decide: a decision that is yours, or
  something only you have. The question waits on the TUI's Runs tab; your answer goes back
  to the lead, and it continues.
- **Done means checked.** When the lead says it is done, a separate checker agent compares
  the branch with the ask and runs the tests. Gaps go back to the lead. Only a clean check
  finishes the goal: the PR gets the lead's summary and a comment with its walkthrough, and
  is marked ready for review.
- **Usage.** Your Claude subscription's limits (`/usage`) are read before each round and
  every 5 minutes during one. At 75% or more of any limit (`--threshold`), the goal stops
  its call and pauses until that limit resets, then continues the same session.
- **Stops.** Three rounds in a row that change nothing, four checks in a row that find
  gaps, a refused push, or an agent call that keeps failing: each is a question to you,
  not an end.

The goal never merges, rebases or force-pushes, and never touches another branch.

## Files

A goal keeps its state in `.cortex/state/<id>/`:

| File | What |
|---|---|
| `goal.json` | the ask, the branch, the PR, the status, the round, the last usage read |
| `journal.md` | the lead's plan, progress and decisions |
| `goal.log` | everything the harness did |
| `awaiting.json` | the question waiting on you, while there is one |
| `usage.json` | the tokens of every call |

Its worktree is `.cortex/worktrees/<id>`, on the branch `goal/<id without "goal-">`.

## Tests

```bash
python3 -m unittest discover -s tests
```
