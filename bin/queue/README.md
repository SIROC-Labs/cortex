# queue

Start goals from the command line, as the TUI does. Use it from a script, or from any
agent you work with. A TUI that is open shows the new goals at once.

```bash
cond queue add "Fix the inbox badge: it counts read items"     # a goal on the prompt
cond queue add https://app.asana.com/0/0/1218985136116349 -f mock.png --into feature/m6
cond queue add < prompt.md                                     # the prompt from stdin
cond queue undo goal-fix-the-inbox-badge                       # discard it, its PR and branch
cond queue list                                                # the goals
```

Run it in the repo the work is for, or in one of its worktrees, or give `--repo`.

- **The prompt** is what to build, in words and links. A link to an Asana ticket is read
  when the goal starts, with its subtasks; nothing is written back. `-f` gives a file with
  it, such as a screenshot; repeat it for more.
- **Into.** The PR goes into the TUI's **Queue into** branch, else `main`, unless `--into`
  names another.
- **Undo.** `undo` discards a goal: its PR, branch and worktree. It takes the goal's id,
  as `list` shows it.

## Tests

```bash
python3 -m unittest discover -s tests
```
