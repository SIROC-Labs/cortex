# queue

Start goals on Asana tickets from the command line, as the TUI does. Use it from a script,
or from any agent you work with. A TUI that is open shows the new goals at once.

```bash
cond queue add https://app.asana.com/0/0/1218985136116349   # a goal on the ticket
cond queue add 1218985136116349 1218985136116350 --into feature/m6
cond queue undo 1218985136116349                            # discard its goal, PR and branch
cond queue list                                             # the goals
```

Run it in the repo the work is for, or in one of its worktrees, or give `--repo`. A ticket
is its Asana URL or gid.

- **Into.** The PR goes into the TUI's **Queue into** branch, unless `--into` names another.
- **Milestones.** `add` on a milestone runs all of it as one goal.
- **Several tickets.** Each ticket starts its own goal, at once. A ticket that is already
  a goal starts nothing.
- **Undo.** `undo` discards a ticket's goal: its PR, branch, worktree, and the subtasks it
  made on the ticket.

## Tests

```bash
python3 -m unittest discover -s tests
```
