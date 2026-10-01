# start-task

The `start-task` lifecycle as an explicit Python program. Control flow is code; a model
is called exactly where one is required — to implement the task, and to repair a
failing QA gate. Every model call goes through a swappable backend. See
[DESIGN.md](DESIGN.md) for why.

The code is experimental. It is not a skill, and nothing in `plugins/` depends on it.

## Setup

```bash
export ASANA_PERSONAL_ACCESS_TOKEN=...   # in ~/.zshrc
```

Requires `git`, `gh` (authenticated), and `claude` on PATH. Nothing to install.

To call it from anywhere, put the `cortex` dispatcher on your PATH:

```bash
bash ../../setup-path.sh          # writes CORTEX_HOME + PATH to your shell profile
bash ../../setup-path.sh --check  # report what is set, change nothing
```

The `claude-sdk` backend is optional and the only thing that needs a venv:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The dispatcher resolves this directory's `.venv` when one exists, so the SDK
backend is visible however `cortex` was reached.

Check what's usable:

```bash
cortex start-task --backends
```

```
Backends
  [ ] claude-sdk    — claude-agent-sdk is not installed — pip install claude-agent-sdk
  [x] claude-cli    (default)
  [x] echo
```

Optionally, in the target repo, a `.start-task.json` describing the QA gates:

```json
{
  "gates": [
    {"name": "backend", "run": "make verify",
     "paths": ["apps/api/", "apps/core/", "pyproject.toml", "uv.lock", "Makefile"]},
    {"name": "frontend", "run": "npm run verify", "cwd": "apps/frontend",
     "paths": ["apps/frontend/"]}
  ]
}
```

A gate runs when a file the branch changed against its base — committed or not — is
one of its `paths` or sits under one; a gate with no `paths` always runs. `cwd` is
relative to the repo root. A docs-only change runs nothing. When the diff cannot be
worked out, every gate runs. The older flat form (`"lint"`, `"build"`, `"test"` as
commands) still works and always runs. Without the file, the QA phase is skipped with a
warning.

The CLI keeps its Asana cache in `~/.cortex/cli/` — never the skills'
`~/.cortex/cortex-workflow/`.

## Use

From inside the target repository:

```bash
cortex start-task https://app.asana.com/0/123/456
```

That runs every phase in order, skipping any already marked done in `state.json` —
so re-running the same command after an interruption picks up where it stopped rather
than repeating work. The prologue always runs: it is idempotent, and re-running it
refreshes the task context from Asana.

Phases can also be run one at a time, taking the task id the prologue resolved. A
`--phase` run is unconditional, which is how you redo a phase already marked done:

```bash
cortex start-task https://app.asana.com/0/123/456 --phase prologue   # no model calls
cortex start-task MT251-47 --phase implement
cortex start-task MT251-47 --phase qa
cortex start-task MT251-47 --phase ship
cortex start-task MT251-47 --status                                  # no work
```

### When the agent has a question

An agent that cannot proceed without a decision ends its turn with a `questions`
block instead of a summary. The run posts those to the task as a comment, waits for
a reply there, and calls the agent again with the answer plus a summary of what it
already changed:

```
Blocked — asking 1217932680420187
  Q: Which VPC — nonprod or shared?
  posted — waiting for a reply (Ctrl-C to stop; progress is saved)
  answer from Justin after 42m18s
```

Any comment on the task after the question counts as the answer — there is no
convention to remember, and a teammate can unblock a run that is not theirs — except
the run's own posts. It posts as you, so every comment it writes, on the task or the
PR, starts with `🤖 cortex ·`, and a comment carrying that mark is never an answer. The
wait is unbounded and costs one request every two minutes; Ctrl-C stops it and the
pending question stays in `awaiting.json`, which `--status` prints. A rerun looks for
the answer to that question before doing anything else, rather than asking again.
`--no-wait` posts and exits with code 3 instead of waiting.

### When anything else stops the run

A full run (no `--phase`) treats every stop short of a ready PR the same way: QA still
red after its repair attempts, a push or `gh pr ready` that fails, a call that stalls at
the turn limit, a precondition that is not met, a step that errors. Each is posted to
the task with what went wrong, and the run waits for your reply — then goes on with it:
the reply is handed to the QA repair or the stalled session as guidance, or, for a
failed step, the run starts again from the top (finished phases are skipped). A
question is never treated as done, and nothing ships past one. A single `--phase` run
stops with the error as before, since you are at the terminal.

### When the PR gets a review

```bash
cortex start-task MT251-47 --phase revise --feedback-file review.md
```

Applies review feedback in the task's worktree, resuming the agent's recorded session
when the same backend still has it (a fresh, fully briefed call otherwise), runs the QA
gates the change touches, commits, pushes and replies on the PR with what it did. It
never rebases or force-pushes; a conflict with the base is resolved by merging the base
in, and only when the feedback asks for it. `run-milestone` calls this for you.

### Outcomes

Every run ends with an exit code and an `outcome.json` in the task's state — also at
`--result-file <path>` when given — so whatever launched it never reads the console:

| Exit | `status` | |
|---|---|---|
| 0 | `shipped`, `revised`, `done` | a full run shipped / a revise was pushed / a single phase finished |
| 1 | `failed` | `reason` says why |
| 3 | `awaiting` | `--no-wait` posted a question; rerun to pick the reply up |
| 130 | — | interrupted |

The outcome carries `task`, `gid`, `pr_url`, `branch`, `worktree` and the agent's
`session`.

The agent's session does not survive the wait, so the resumed call is a fresh one:
it is given the original task, the answer, and `git diff --stat` of its own earlier
work, and told to continue rather than start over.

### When the agent hits the turn limit

`--max-turns` bounds a single call, not the work. A call stopped by the ceiling comes
back with the session it was using, and the run resumes that same session — the agent
keeps its memory and picks up mid-thought:

```
  implement: calling claude-cli
  implement: claude-cli · claude-opus-5 · 300 turns · 861.2s
  implement: hit the turn limit, resuming the session
  implement: calling claude-cli (continuation 2)
```

The guard is progress. Before each continuation the run fingerprints the worktree
(`git status --porcelain` plus `git diff --stat`); if a call burns a whole ceiling and
the fingerprint is unchanged, it is going in circles, so the run stops and says so
rather than paying for another lap:

```
  ! implement stopped at the turn limit — it reached the limit again without changing anything
```

Because sessions are resumed, they are left on disk rather than discarded after each
call.

### Taking over the session

When a run ends it prints the way back into the agent's last session, so you can carry
on in an interactive shell instead of re-explaining the task:

```
Done
  task MT251-47 shipped

  continue this session yourself (implement):
    cd /…/.cortex/worktrees/MT251-47+csv-export && claude --resume 6f3a…
```

It is the newest session — the implement call, or the last QA repair if one ran — and
`--status` prints it again later. The command is shown as recorded; whether the provider
still has that session is between you and it.

### Flags

| Flag | Default | |
|---|---|---|
| `--phase` | all | run one of `prologue`, `implement`, `qa`, `ship` alone, even if already done, or `revise` |
| `--status` | off | report phase progress and do no work |
| `--backends` | off | list providers and whether they are usable |
| `--repo` | cwd | target repository |
| `--backend` | `claude-cli` | `claude-cli`, `claude-sdk`, `echo` |
| `--model` | backend default | |
| `--max-turns` | 300 | turn ceiling per call — a checkpoint, not a cap on the task |
| `--autonomy` | `full` | `read-only`, `edit`, `full` |
| `--agent-cmd` | — | override the backend's command wholesale |
| `--no-project-context` | off | skip the repo's CLAUDE.md / AGENTS.md |
| `--no-worktree` | off | branch in the current directory instead of `.cortex/worktrees/` |
| `--base` | `origin/main` | base branch |
| `--strict` | off | Estimate and sprint membership become blocking |
| `--ignore-deps` | off | incomplete dependencies warn instead of blocking |
| `--no-wait` | off | post a question or problem and exit 3 instead of waiting |
| `--feedback`, `--feedback-file` | — | the review feedback for `revise` |
| `--result-file` | — | also write the outcome JSON here |

`--backend echo` runs the whole flow with no model at all, for exercising the phases
themselves. `--agent-cmd` is the escape hatch when a run stalls on a permission
mode; a backend with no command line to override reports it as unsupported rather than
appearing to have honoured it.

## Phases

| Phase | Model calls | What it does |
|---|---|---|
| `prologue` | 0 | Parse URL, fetch task + subtasks + deps + comments + attachments, gate, claim if unassigned, create worktree in `.cortex/worktrees/<task-id>+<slug>` + branch off `origin/main`, empty commit, push, draft PR, status → In Progress, 🏁 comment |
| `implement` | 1 | Feeds the context bundle through the seam, expects a `{summary, files_changed, notes}` block back |
| `qa` | 0–2 | Runs the gates the change touches; on failure hands the output to a repair call, retries the gate, max 2 attempts before asking |
| `ship` | 0 | Commits, pushes (checked), sets the PR body from `summary`, marks it ready, status → In Review, 🚀 comment |
| `revise` | 1+ | Not part of a full run — applies PR feedback, QA, push, replies on the PR |

State lives in `<main-repo-root>/.cortex/state/<task-id>/` — `context.json`,
`result.json`, `qa.json`, `state.json`, `outcome.json`, `revise.json`, `attachments/`, `run.json` (the live run's
pid, so an abandoned terminal is findable), `session.json` (the agent's last session,
for picking the conversation up by hand), `awaiting.json` while a question is
outstanding, and `<phase>.failure.log`
when a model call exits non-zero — that file is the only copy of what the provider
printed, so it is written before the run dies.

`.cortex/` ignores itself, so nothing the tool writes turns up in the diff of the branch
it is working on. State from before the move, in a top-level `.start-task/`, is
relocated the first time a run touches that task.

## Preconditions

`prologue` refuses to start a task that is already in progress, is blocked by an
incomplete dependency, or belongs to someone else. A task this run already started
passes on a rerun: its status moved because of the run itself. An unassigned task is claimed rather
than rejected. A missing Estimate and a task off the sprint board are warnings unless
you pass `--strict`.

## Adding a backend

One module and one row:

```python
# agent/my_provider.py
from .base import AgentBackend, AgentResult, extract_last_json_block

class MyBackend(AgentBackend):
    name = "my-provider"

    def available(self):
        return True, ""

    def run(self, request):
        text = ...                       # call your provider
        return AgentResult(backend=self.name, text=text,
                           structured=extract_last_json_block(text))
```

```python
# agent/__init__.py
_REGISTRY = {..., "my-provider": (".my_provider", "MyBackend")}
```

Three contracts: never raise (report `ok=False` with an `error`); declare anything in
the request you could not honour via `result.unsupported`; and separate *why the model
stopped* from *whether it failed* — a run that hit the turn ceiling is `ok=True` with
`stop_reason="max_turns"` and, if your provider can continue one, a `resume_token`. A
backend that cannot resume leaves the token `None` and the runner stops there instead of
looping. `resume_command()` is optional on top of that: return the shell command that
drops a person into that session, or leave it returning `None`.

## Tests

```bash
python3 tests/test_pure.py     # slug, gate, link extraction, task key
python3 tests/test_agent.py    # the seam, registry, backends, envelope parsing
```

The phases that shell out to a model, `gh`, `git` or Asana are validated by running
them.

## Known gaps

- **Not yet run against a live task.** Tests and an `echo` end-to-end pass; no real
  model call has gone through it.
- **Permission mode is unsettled.** A headless run auto-denies anything not
  pre-approved, so a run needing an un-allowed `Bash` command may stall. Escalate with
  `--agent-cmd` if it bites.
- **External links are text only.** The implement call runs with no MCP servers, so a
  Figma or Notion link in the ticket is passed through as a URL the agent cannot open.
- **`asana.py` is a copy** of the plugin's `tm.py` (plus the read verbs, `task complete`
  and `project get` it lacks). It will drift. It shares no runtime files with the skill.
- **Parallel QA can collide.** Runs share the machine: gates that bind fixed ports or a
  shared database will fight when several tasks hit QA at once.
