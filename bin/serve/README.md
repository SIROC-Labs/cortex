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
working. `install` starts it through an interactive login zsh, so it has the tokens from
`~/.zshrc` and the login PATH (`/usr/local/bin`, where tools such as `docker` live). After a token changes, run `cond serve restart`. Its log is
`~/.cortex/cli/serve.log`.

**Repos.** A repo is registered when a goal starts in it, from anywhere (`cond queue`, the
TUI, the service), or with `--repo` or `POST /api/repos`. Its id is its folder's name. The
list is `~/.cortex/cli/repos.json` (`COND_HOME` moves the folder).

## The web page

`http://127.0.0.1:4747/`, served by the service: no build step, nothing to install.

- **Runs:** a prompt box on top (type, paste or drop images and files, pick the repo, and
  the branch it goes into if not the default; ⌘⏎ starts it), then the goals, those
  waiting on you first, each with its parts nested under it; its "› N parts" button folds
  them, and a goal
  finished with all its parts starts folded. Finished goals are hidden:
  *Show finished* shows them; one with a part still at work stays. The nav
  counts the goals waiting on you.
- **A goal:** under its title, its stages (Plan ▸ Build, or Revision N ▸ Static checks ▸
  Check N: gaps ▸ Fixing gaps ▸ Check again ▸ Push, or a part's Merge ▸ CI ▸ PR review),
  the current one marked, and who works now: tasks and their model, the lead deciding,
  the checker, the fixer, the runner, or you. Then what it waits on you for. Each
  question takes one of its options or your own words, and folds to one line with its
  answer when you pick an option, press *Done* or ⌘⏎ (clicking away leaves it open;
  *Change* opens it again until you send); *Discuss this question* opens a talk about it alone, in a session
  of its own with only the ask, the question and the journal's references and
  decisions, which reads but changes nothing (*Use as my answer* copies a reply into the
  answer; *Start over* clears the talk). A plan takes Approve or Ask for changes, and *Discuss the plan*
  talks it through the same way with the plan's steps, criteria and technical
  plan; while no plan waits on review, the Plan tab has the same link. A decision
  puts the plan's talks away, so a new plan starts with none. Once sent,
  the box shows what you sent (the answers, "Plan approved", or "Changes asked" with
  your words) until the goal picks it up. A red box warns when the lead changed a repo
  file itself, or a sub-agent it started did: it only reads and writes its journal. Its status
  line counts the steps and acceptance criteria done; hover over either for the list.
  What runs now, agent by agent, each in one plain line that Haiku writes (on OpenCode,
  the configured model with the lowest price, else none) about every 45 seconds while
  the page or the TUI shows the goal, and only for an agent that did something since.
  Tabs: its timeline (every step from the log, in phases that stay in view as you scroll:
  Plan, Build, Merge conflict, Static checks, Check N, Fixing gaps, Push, CI, PR review,
  Revision N and its own phases; each round says what it handed out, with the tasks, their
  model and how they ended; each check with its gaps; each step that asked you with
  every question and your answer, or your plan decision; the cost of each step; the
  running step lists its agents in plain words, and their commands under *Commands*),
  the plan (a split goal's parts, and the technical plan with its
  mermaid diagrams drawn), the ask and its files, the journal, the cost by agent, and
  the live log.
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
| `POST /api/repos/{repo}/goals {prompt, files?, base?}` | start a goal; each of `files` is a local path of a file or folder (the service is on this machine), or an upload `{name, data}` with the bytes in base64, whose `name` may be a path such as `proto/Main.dc.html` to send a folder file by file |
| `GET /api/repos/{repo}/goals/{goal}` | a goal in full: state, its `stages` and `who` works now, what it waits on and what was `sent` to it, journal, technical plan, tasks, calls and cost, parts, files, its timeline with each answer (`qa`), the running agents with their `summary`, and `lead_edits` |
| `GET /api/repos/{repo}/goals/{goal}/log?from=N` | its log from byte N (a negative N: the last bytes); `next` is where to read on |
| `GET /api/repos/{repo}/goals/{goal}/files/{path}` | a file it was given (`inputs/`), a ticket's attachment, its technical plan or usage report |
| `POST /api/repos/{repo}/goals/{goal}/answer {text, answers?, note?}` | answer what it waits on you for; `answers`, one per question, and `note` keep how the page wrote it. Every answer is kept in the goal's `answers.json` |
| `POST /api/repos/{repo}/goals/{goal}/tell {text, stop?}` | send it a note while it runs: the lead reads it after its next tool call, or with its next prompt; `stop` stops its running coding tasks first. Refused while it waits on your answer |
| `POST /api/repos/{repo}/goals/{goal}/{approve,stop,resume,done,clear,undo}` | approve its plan; stop it; carry it on; mark it done; take it off the list; undo all of it |
| `GET`, `POST`, `DELETE /api/repos/{repo}/goals/{goal}/discussions/{q1…,plan}` `{text}` | a talk about one question, or the plan, of what the goal waits on: the POST adds your message and starts the reply in the background; the GET gives the messages and whether a reply is coming; the DELETE starts the talk over |
| `GET`, `PUT /api/repos/{repo}/settings` | the branch goals go into (`base`, else main), `usage_threshold`, `goal_gate`, `runner` (`claude` or `opencode`), `models` (Claude's: `lead`, `subagent`, `check`, and `lead_effort`, `subagent_effort`, `check_effort`), `opencode_models` (`lead`, `subagent`, `check` as `provider/model`), and `providers`: providers for OpenCode: an OpenAI-compatible endpoint, or one of OpenCode's own without a `base_url` (`id`, `base_url`, `key_env`: the name of the key's variable, `models`, `input_price`, `output_price` per million tokens) |

## MCP

`http://127.0.0.1:4747/mcp`, over streamable HTTP (each reply one JSON body). Its tools
are the same actions: `list_repos`, `add_repo`, `list_goals`, `get_goal`, `goal_log`,
`start_goal` (files and folders as local paths), `answer_goal`, `tell_goal`, `approve_plan`, `stop_goal`,
`resume_goal`, `get_settings`, `set_settings`. In Claude Code:

```bash
claude mcp add --transport http conductor http://127.0.0.1:4747/mcp
```

## Tests

```bash
python3 -m unittest discover -s tests
```
