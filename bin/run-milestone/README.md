# run-milestone

Works a whole Asana milestone through [`start-task`](../start-task/README.md), in
parallel, until every task is merged. The loop is plain code: no model is called here,
only inside the `start-task` runs it launches.

## Use

From inside the target repository, with the URL of the milestone's own task:

```bash
cortex run-milestone https://app.asana.com/1/<ws>/project/<board>/task/<milestone>
cortex run-milestone <milestone-url> --status        # where every task stands; no work
cortex run-milestone <milestone-url> --backend echo  # any other flag goes to start-task
```

It is meant to sit in a spare terminal or tmux pane. Ctrl-C stops it and the runs it
launched; run the same command to carry on.

## What it does

Each pass:

1. **Reads the milestone** — its tasks, their status and their dependencies — every five
   minutes, and straight after a merge.
2. **Starts every ready task at once.** Ready means not completed, every dependency
   completed (inside the milestone or not), a not-yet-started status, unassigned or
   assigned to you, and not already run. It adds the task to the active sprint, assigns
   it to you, and launches `start-task` on it. The sprint is resolved in code: the
   team's sprint boards are found by the board's `<Team> | ` prefix and the current one
   is picked. `start-task` takes the git setup — fetch, worktree, draft PR — one run at a
   time under a lock in `.cortex/`. Everything after that runs concurrently.
3. **Watches each shipped PR**, backing off from one check a minute to one every ten
   while nothing changes:
   - a review, inline comment or PR comment that is not the run's own (marked
     `🤖 cortex ·`) and not from a bot account is handed to `start-task --phase revise`,
     which applies it in the task's session, runs the gates the change touches, pushes
     and replies on the PR;
   - a merge completes the task in Asana, moves it to Done and removes its worktree;
     whatever that readies starts on the next pass;
   - a conflict with the base is posted to the PR and the task, and waits for you: your
     reply on the PR goes through `revise`, which merges the base in — never a rebase or
     force-push;
   - a PR closed without merging is posted to the task and left: reopen it to carry on,
     or complete or cancel the task.

A run that needs you — the agent's questions, QA still red, a refused push — waits on
the task itself (see `start-task`); only its dependents wait with it. A run that fails
outright is recorded and blocks only its dependents. A task you complete or cancel in
Asana while it runs is stopped and its worktree left alone.

The loop ends when nothing is running, waiting or open and nothing is ready, and prints
where every task stands — exit 0 when the whole milestone is complete, 1 when something
is left (and why).

## State

`<repo>/.cortex/milestones/<milestone-gid>/`:

- `state.json` — the milestone's tasks as last read, and a record per task: phase, PR,
  feedback already handled
- `logs/<task-id>.log` — each `start-task` run's output
- `results/<gid>.json` — each run's outcome, as `start-task --result-file` wrote it
- `feedback/` — the review feedback each `revise` was given

A restart does not trust the record: each task is reconciled against `start-task`'s own
state. A run still going is adopted rather than started twice, one that finished while
the loop was down is taken at its word, and one that died with the loop is relaunched —
`start-task` resumes it.

## Tests

```bash
python3 tests/test_pure.py   # readiness, feedback selection, outcomes, reconciliation
```
