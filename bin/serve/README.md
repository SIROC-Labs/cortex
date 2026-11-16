# serve

The conductor service: goals over REST and MCP, for the web page, the TUI, scripts and
agents. It listens on `127.0.0.1` only, and refuses requests whose `Host` or browser
`Origin` is not its own, so other sites cannot reach it.

```bash
cond serve                     # run it in the foreground, on port 4747 (--port, COND_PORT)
cond serve --repo ~/code/web   # also register a repo
cond serve install             # run it at login, through launchd
cond serve status | restart | uninstall
```

Goals run in processes of their own: stopping or restarting the service leaves them
working. `install` starts it through an interactive zsh, so it has the tokens from
`~/.zshrc`. After a token changes, run `cond serve restart`. Its log is
`~/.cortex/cli/serve.log`.

**Repos.** A repo is registered when a goal starts in it, from anywhere (`cond queue`, the
TUI, the service), or with `--repo` or `POST /api/repos`. Its id is its folder's name. The
list is `~/.cortex/cli/repos.json` (`COND_HOME` moves the folder).

## REST

Every body is JSON. An error is `{"error": "..."}` with a 4xx status.

| | |
|---|---|
| `GET /api/repos` · `POST /api/repos {path}` | the repos; register one |
| `GET /api/goals` | every repo's goals, each with its `repo` |
| `GET /api/repos/{repo}/goals` | a repo's goals, newest first, each goal's parts after it |
| `POST /api/repos/{repo}/goals {prompt, files?, base?}` | start a goal; `files` are `{name, data}`, with the bytes in base64 |
| `GET /api/repos/{repo}/goals/{goal}` | a goal in full: state, what it waits on, journal, technical plan, tasks, calls and cost, parts, files |
| `GET /api/repos/{repo}/goals/{goal}/log?from=N` | its log from byte N (a negative N: the last bytes); `next` is where to read on |
| `GET /api/repos/{repo}/goals/{goal}/files/{path}` | a file it was given (`inputs/`), a ticket's attachment, its technical plan or usage report |
| `POST /api/repos/{repo}/goals/{goal}/answer {text}` | answer what it waits on you for |
| `POST /api/repos/{repo}/goals/{goal}/{approve,stop,resume,done,clear,undo}` | approve its plan; stop it; carry it on; mark it done; take it off the list; undo all of it |
| `GET`, `PUT /api/repos/{repo}/settings` | the branch goals go into (`base`, else main), `usage_threshold`, `goal_gate`, `models` |

## MCP

`http://127.0.0.1:4747/mcp`, over streamable HTTP (each reply one JSON body). Its tools
are the same actions: `list_repos`, `add_repo`, `list_goals`, `get_goal`, `goal_log`,
`start_goal` (files as local paths), `answer_goal`, `approve_plan`, `stop_goal`,
`resume_goal`, `get_settings`, `set_settings`. In Claude Code:

```bash
claude mcp add --transport http conductor http://127.0.0.1:4747/mcp
```

## Tests

```bash
python3 -m unittest discover -s tests
```
