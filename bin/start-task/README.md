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

Optionally, in the target repo, a `.start-task.json` describing the QA gate:

```json
{
  "lint":  "npm run lint",
  "build": "npm run build",
  "test":  "npm test"
}
```

Any key may be omitted. Without the file, the QA phase is skipped with a warning.

## Use

From inside the target repository:

```bash
cortex start-task https://app.asana.com/0/123/456
```

That runs every phase in order. Or one at a time — each is resumable and
re-runnable, taking the task id the prologue resolved:

```bash
cortex start-task https://app.asana.com/0/123/456 --phase prologue   # no model calls
cortex start-task MT251-47 --phase implement
cortex start-task MT251-47 --phase qa
cortex start-task MT251-47 --phase ship
cortex start-task MT251-47 --status                                  # no work
```

### Flags

| Flag | Default | |
|---|---|---|
| `--phase` | all | run one of `prologue`, `implement`, `qa`, `ship` alone |
| `--status` | off | report phase progress and do no work |
| `--backends` | off | list providers and whether they are usable |
| `--repo` | cwd | target repository |
| `--backend` | `claude-cli` | `claude-cli`, `claude-sdk`, `echo` |
| `--model` | backend default | |
| `--max-turns` | 60 | turn ceiling per call |
| `--autonomy` | `full` | `read-only`, `edit`, `full` |
| `--agent-cmd` | — | override the backend's command wholesale |
| `--no-project-context` | off | skip the repo's CLAUDE.md / AGENTS.md |
| `--no-worktree` | off | branch in the current directory |
| `--base` | `origin/main` | base branch |
| `--strict` | off | Estimate and sprint membership become blocking |
| `--ignore-deps` | off | incomplete dependencies warn instead of blocking |

`--backend echo` runs the whole flow with no model at all, for exercising the phases
themselves. `--agent-cmd` is the escape hatch when a run stalls on a permission
mode; a backend with no command line to override reports it as unsupported rather than
appearing to have honoured it.

## Phases

| Phase | Model calls | What it does |
|---|---|---|
| `prologue` | 0 | Parse URL, fetch task + subtasks + deps + comments + attachments, gate, claim if unassigned, create worktree + branch off `origin/main`, empty commit, push, draft PR, status → In Progress, 🏁 comment |
| `implement` | 1 | Feeds the context bundle through the seam, expects a `{summary, files_changed, notes}` block back |
| `qa` | 0–2 | Runs lint/build/test; on failure hands the output to one repair call, retries the gate, max 2 attempts |
| `ship` | 0 | Commits, pushes, sets the PR body from `summary`, marks it ready, status → In Review, 🚀 comment |

State lives in `<main-repo-root>/.start-task/<task-id>/` — `context.json`,
`result.json`, `qa.json`, `state.json`, `attachments/`, and `<phase>.failure.log`
when a model call exits non-zero — that file is the only copy of what the provider
printed, so it is written before the run dies.

## Preconditions

`prologue` refuses to start a task that is already in progress, is blocked by an
incomplete dependency, or belongs to someone else. An unassigned task is claimed rather
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

Two contracts: never raise (report `ok=False` with an `error`), and declare anything in
the request you could not honour via `result.unsupported`.

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
- **`asana.py` is a copy** of the plugin's `tm.py` (plus three read verbs it lacks). It
  will drift.
- **No pause flow.** A blocked run stops and reports; it does not commit WIP or post a
  blocking question.
