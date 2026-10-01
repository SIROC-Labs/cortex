# run-milestone

Works the milestones of an Asana board through [`start-task`](../start-task/README.md),
in parallel, until every task is merged. The loop is plain code: no model is called here,
only inside the `start-task` runs it launches.

## Use

From inside the target repository, naming the board, the milestones on it to work and
the sprint board the tasks go into:

```bash
cortex run-milestone <board-url> M1 --sprint <sprint-url>
cortex run-milestone <board-url> M1 M2 --sprint <sprint-url>       # several at once
cortex run-milestone <board-url> --status                          # where every task stands
cortex run-milestone <board-url> M1 --sprint <url> --backend echo  # other flags → start-task
```

A milestone is named by its full name, the short name before ` :: ` (`M1`), or its
task's URL or gid. Nothing is guessed: no milestone or sprint is picked for you, so a
board that names things differently works the same.

It is meant to sit in a spare terminal or tmux pane. Ctrl-C stops it and the runs it
launched; run the same command to carry on.

## What it does

Each pass:

1. **Reads the milestone** — its tasks, their status and their dependencies — every five
   minutes, and straight after a merge.
2. **Starts every ready task at once.** Ready means not completed, every dependency
   completed (inside the milestones or not), a not-yet-started status, unassigned or
   assigned to you, and not already run. It adds the task to the `--sprint` board,
   assigns it to you, and launches `start-task` on it. `start-task` takes the git setup
   — fetch, worktree, draft PR — one run at a time under a lock in `.cortex/`.
   Everything after that runs concurrently.
3. **Watches each shipped PR**, backing off from one check a minute to one every ten
   while nothing changes:
   - a review, inline comment or PR comment that is not the run's own (marked
     `🤖 cortex ·`) and not from a bot account is handed to `start-task --phase revise`,
     which applies it in the task's session, runs the gates the change touches, pushes
     and replies on the PR;
   - a merge completes the task in Asana, moves it to Done and removes its worktree;
     whatever that readies starts on the next pass;
   - a conflict with the base parks the task: it is posted once to the PR and the task,
     and nothing more happens to it until a PR comment says `please resolve`. That goes
     through `revise`, which fetches, merges the base in and resolves the conflicts —
     never a rebase or force-push. A conflict you resolve yourself un-parks it too;
   - a PR closed without merging stops the task. Nothing is posted and nothing waits on
     it; its dependents stay blocked.

A run that needs you — the agent's questions, QA still red, a refused push — waits on
the task itself (see `start-task`); only its dependents wait with it. A run that fails
outright is recorded and blocks only its dependents. A task you complete or cancel in
Asana while it runs is stopped and its worktree left alone.

The loop ends when nothing is running, waiting, open or parked and nothing is ready, and prints
where every task stands — exit 0 when the whole milestone is complete, 1 when something
is left (and why).

## State

`<repo>/.cortex/milestones/<board-gid>/`:

- `state.json` — the tasks in scope as last read, and a record per task: phase, PR,
  feedback already handled. Records are per task, so running a different set of
  milestones on the same board keeps what earlier runs did.
- `logs/<task-id>.log` — each `start-task` run's output
- `results/<gid>.json` — each run's outcome, as `start-task --result-file` wrote it
- `feedback/` — the review feedback each `revise` was given

A restart does not trust the record: each task is reconciled against `start-task`'s own
state. A run still going is adopted rather than started twice, one that finished while
the loop was down is taken at its word, and one that died with the loop is relaunched —
`start-task` resumes it.

## Tests

```bash
python3 tests/test_pure.py   # readiness, milestone matching, feedback, outcomes, reconciliation
```
