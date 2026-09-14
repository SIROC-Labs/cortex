# fast-task

The `start-task` lifecycle as an explicit Python program. Control flow is code; an LLM
is called exactly where one is required — to implement the task, and to repair a
failing QA gate. See [DESIGN.md](DESIGN.md) for why.

This is an experiment. It is not a skill, it is not agent-agnostic, and nothing in
`plugins/` depends on it.

## Setup

```bash
export ASANA_PERSONAL_ACCESS_TOKEN=...   # in ~/.zshrc
```

Requires `git`, `gh` (authenticated), and `claude` on PATH.

Optionally, in the target repo, a `.fast-task.json` describing the QA gate:

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
python3 /path/to/fast-task/fast_task.py run https://app.asana.com/0/123/456
```

Or a phase at a time — each is resumable and re-runnable:

```bash
fast_task.py prologue https://app.asana.com/0/123/456   # no LLM, no tokens
fast_task.py implement MT251-47
fast_task.py qa        MT251-47
fast_task.py ship      MT251-47
fast_task.py status    MT251-47
```

Useful flags: `--repo <path>` (target repo, default cwd), `--no-worktree`,
`--base <branch>`, `--strict` (Estimate and sprint membership become blocking),
`--agent-cmd` (override the LLM invocation wholesale).

## Phases

| Phase | LLM calls | What it does |
|---|---|---|
| `prologue` | 0 | Parse URL, fetch task + subtasks + deps + comments + attachments, gate, claim if unassigned, create worktree + branch off `origin/main`, empty commit, push, draft PR, status → In Progress, 🏁 comment |
| `implement` | 1 | Feeds the context bundle to `claude -p`, expects a `{summary, files_changed, notes}` block back |
| `qa` | 0–2 | Runs lint/build/test; on failure hands the output to one repair call, retries the gate, max 2 attempts |
| `ship` | 0 | Commits, pushes, sets the PR body from `summary`, marks it ready, status → In Review, 🚀 comment |

State lives in `<main-repo-root>/.fast-task/<task-id>/` — `context.json`, `result.json`,
`qa.json`, `state.json`, `attachments/`.

## Preconditions

`prologue` refuses to start a task that is already in progress, is blocked by an
incomplete dependency, or belongs to someone else. An unassigned task is claimed rather
than rejected. A missing Estimate and a task off the sprint board are warnings unless
you pass `--strict`.

## Tests

```bash
python3 tests/test_pure.py
```

Covers the pure functions — slug, gate, link extraction, agent-output parsing. The
phases that shell out to `claude`, `gh`, `git` or Asana are validated by running them.

## Known gaps

- **External links are text only.** The implement call runs with no MCP servers, so a
  Figma or Notion link in the ticket is passed through as a URL the agent cannot open.
- **Permission mode is unsettled.** `-p` auto-denies anything not pre-approved, so a
  run needing an un-allowed `Bash` command may stall. Escalate with `--agent-cmd` if it
  bites.
- **`asana.py` is a copy** of the plugin's `tm.py` (plus three read verbs it lacks). It
  will drift.
- **No pause flow.** A blocked run stops and reports; it does not commit WIP or post a
  blocking question.
