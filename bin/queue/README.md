# queue

Queue Asana tasks, milestones and goals from the command line, as the TUI does. Use it
from a script, or from any agent you work with: it changes the same control file as the
TUI, and this repo's daemon picks the change up the same way. A TUI that is open shows it
at once.

```bash
cortex queue add https://app.asana.com/0/0/1218985136116349   # a task, or a milestone's open subtasks
cortex queue add 1218985136116349 1218985136116350 --into feature/m6 --checkpoint
cortex queue remove 1218985136116349
cortex queue undo 1218985136116349                            # discard its run, PR and branch first
cortex queue goal https://app.asana.com/0/0/1218985136116349  # run the ticket as a goal
cortex queue list                                             # the goals, the queue, the daemon
```

Run it in the repo the work is for, or in one of its worktrees, or give `--repo`. A task
is its Asana URL or gid.

- **Into.** Work goes into the TUI's **Queue into** branch, unless `--into` names another.
- **Milestones.** `add` on a milestone queues its open subtasks. `goal` on a milestone runs
  all of it as one goal.
- **Earlier work.** `add` refuses a task that an earlier run left work for: a PR, a branch,
  or saved state. A run queued on top of that would carry the old work on, PR and all.
  `undo` discards it first, as the TUI's Undo does: it closes the PR, deletes the branch and
  the worktree, and in Asana takes the task off the sprint and unassigns it. A merged task
  gets a revert PR instead. Only the daemon can undo, and only a task it has run.
- **The daemon.** Queueing does not start the daemon. If it is not running, or no sprint is
  picked, the output says so; start it from the TUI.

## Tests

```bash
python3 -m unittest discover -s tests
```
