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

## The web page

`http://127.0.0.1:4747/`, served by the service: no build step, nothing to install.

- **Runs:** a prompt box on top (type, paste or drop images and files, pick the repo, and
  the branch it goes into if not the default; ⌘⏎ starts it), then the goals, those
  waiting on you first. Finished goals are hidden: *Show finished* shows them. The nav
  counts the goals waiting on you.
- **A goal:** what it waits on you for, at the top: its questions with their options (a
  click adds one to the answer), or its plan with Approve and Ask for changes; a plan
  waiting opens on the Plan tab. What runs now, agent by agent. Tabs: its timeline
  (every step from the log, in phases, each round with the tasks it handed out and how
  they ended, each check with its gaps, the cost of each step), the plan (its parts,
  steps and acceptance criteria, ticked, and the technical plan, its mermaid diagrams
  drawn), the ask and its files,
  the journal, the cost by agent, and the live log.
- **Settings:** *Runs on*: Claude Code (`claude -p`) or OpenCode. Under it, only the chosen
  one's model for each role (and, for Claude, each role's effort and the usage limit;
  for OpenCode, its providers). Then the goals' branch and plan approval, and the repos.

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
| `GET`, `PUT /api/repos/{repo}/settings` | the branch goals go into (`base`, else main), `usage_threshold`, `goal_gate`, `runner` (`claude` or `opencode`), `models` (Claude's: `lead`, `subagent`, `check`, and `lead_effort`, `subagent_effort`, `check_effort`), `opencode_models` (`lead`, `subagent`, `check` as `provider/model`), and `providers`: providers for OpenCode: an OpenAI-compatible endpoint, or one of OpenCode's own without a `base_url` (`id`, `base_url`, `key_env`: the name of the key's variable, `models`, `input_price`, `output_price` per million tokens) |

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
