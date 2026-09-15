# fast-task — design

Run the `start-task` lifecycle as an explicit Python program, calling a model only
where one is genuinely required.

Status: implemented, not yet run against a live task.

## Why

`start-task` today is a 258-line `SKILL.md` plus ~600 lines of references, all of it
prose that a model reads and acts on one step at a time. The deterministic work is
already scripted (`tm.py`, `readiness.py`, `checkpoint.sh`), but the **control flow is
the model**: it reads the prose, decides which script to run, reads the JSON back,
formats it, and moves to the next step.

Auditing the 14 steps, only three need a language model — implementation (10), QA
judgment (11), and the work summary inside ship-it (12). Everything from "parse the
URL" through "post the start comment" is field comparisons and fixed templates. The
🏁 start comment is literally `🏁 Starting work — branch: X / PR: Y`.

Two consequences of prose-as-control-flow:

- **Cost.** Reaching step 9 — before a line of the feature is written — loads the skill
  and its references, the full task JSON, subtasks, comments and attachments, across
  roughly 15–25 model round-trips, each re-sending a growing context.
- **Reliability.** `SKILL.md` is littered with `❌ HARD GATE`, `do not substitute
  reasoning for invocation`, `auto mode does NOT override`. Those paragraphs exist
  because the model skips steps. They are an attempt to get deterministic behaviour out
  of English. A `for` loop gives that for free.

This replaces the brain, not the hands: the same Asana calls, sequenced by Python in a
fixed order. Zero model turns to reach step 9, then one call for the part that needs
thought.

## Non-goals

- Replacing the `start-task` skill. It stays untouched; this is a parallel path.
- Provider neutrality in the task manager. Asana only.
- Covering the pause/resume-on-blocker flow, the QA sub-flow's visual verification, or
  post-ship code review.

## Why the model call sits behind a seam

Every model call goes through `agent/`. The vendor SDK is imported in exactly one file;
everything else speaks `AgentRequest` / `AgentResult` / `AgentBackend`.

1. **The provider is a flag, not a rewrite.** `claude -p` is the default because it
   needs nothing installed. The Claude Agent SDK is one `--backend` away, and another
   runtime's headless CLI is a module plus a row in the registry — which is what keeps
   this usable outside Claude Code without the orchestrator knowing anything about it.
2. **The backends are genuinely interchangeable.** Same prologue, same prompt, same
   repo; only the transport differs.
3. **`echo` runs the whole flow for free.** No model, no cost. It is how the phases,
   the state machine and the prompt rendering get exercised without spending anything.

Two rules make the abstraction honest rather than decorative:

- **A backend never raises.** Failures come back as `ok=False` with an `error`. The
  orchestrator handles one failure shape regardless of provider.
- **A backend declares what it dropped.** Anything in the request it cannot express
  lands in `result.unsupported`, and the runner warns. The CLI backend has no budget
  ceiling, so `max_budget_usd` shows up there rather than being silently ignored — the
  caller is never told it got something it didn't.

`AgentRequest` is intent, not vendor configuration: a prompt, a working directory, an
autonomy level (`read-only` / `edit` / `full`), ceilings on turns and dollars, and
whether to load the project's own conventions. Tools are named neutrally (`read_file`,
`edit_file`, `run_command`); each backend maps them. `extra["argv"]` is the deliberate
exception — an escape hatch that hands the command line to the operator wholesale for a
run that stalls on a permission mode, and which backends without a command line report
as unsupported rather than appearing to honour.

Telemetry is optional and never invented. A backend that cannot report cost leaves it
`None`, and the ledger prints "cost not reported" rather than `$0.00`.

## Layout

```
bin/fast-task/
  DESIGN.md         # this file
  README.md         # usage
  fast_task.py      # the orchestrator — all control flow
  asana.py          # tm.py, copied, plus three new read verbs
  cache_util.py     # copied dependency of asana.py
  agent/
    base.py         # AgentRequest · AgentResult · AgentBackend · tool vocabulary
    __init__.py     # registry — the one place a provider is named
    claude_cli.py   # `claude -p` subprocess          (default)
    claude_sdk.py   # Claude Agent SDK                (needs requirements.txt)
    echo.py         # no model, no cost
  prompts/
    implement.md    # template for the implementation call
    qa_fix.md       # template for the failure-repair call
```

Nothing here imports from `plugins/`. `asana.py` and `cache_util.py` are copies, taken
once; they are ours to edit and will drift from the originals. That is accepted while
this is experimental — the alternative couples it to a plugin that is still changing.

## Phases

Each phase is separately invocable and resumable.

```
fast_task.py run       <task-url>   # all four, in order
fast_task.py prologue  <task-url>   # zero model calls
fast_task.py implement <task-id>
fast_task.py qa        <task-id>
fast_task.py ship      <task-id>
fast_task.py backends               # which providers are usable here
```

State lives in `.fast-task/<task-id>/` at the **main repo root**, not in the worktree —
the worktree does not exist yet when the prologue starts writing, and it may be removed
after ship while the state is still wanted. It holds `context.json`, `result.json`,
`qa.json`, `state.json`, `cost.json`, `attachments/`. Re-running a phase overwrites its
own output. `run` skips phases already marked done in `state.json`.

`<task-id>` is the human key (`MT251-47`) read from the task's ID custom field, falling
back to the Asana gid when the project has no such field — the same field the readiness
gate treats as non-blocking, so it genuinely can be absent.

### prologue — pure Python, no model

1. Parse the task URL to a gid (`asana.py ref parse`).
2. Fetch the task (`task get`) — name, description, assignee, status, custom fields.
3. Assignee: if empty, self-assign and say so; if someone else, fail with a message.
4. Preconditions gate (below).
5. Fetch subtasks, dependencies, comments, attachments. Download non-image attachments
   inline; download images to `attachments/` and pass paths.
6. Extract external URLs (Figma / Notion / Drive / Loom) from description and comments
   by regex. Record them as bare URLs — see Known gaps.
7. Detect existing work: `git branch --list "*<task-id>*"`, `gh pr list --search`.
   If found, attach to it rather than creating.
8. Resolve base from `origin/main` via `git fetch origin` (never checks out a local
   base). Create worktree + branch: `git worktree add <path> -b <task-id>/<slug> <base>`,
   path anchored to the main repo root, never cwd-relative.
9. Empty commit, push, `gh pr create --draft`.
10. `set-status In Progress`; post the 🏁 comment, deduplicated by branch name.
11. Write `context.json`.

Slug is a deterministic slugify of the task name, truncated to 6 words.

### implement — one model call

The prompt is `prompts/implement.md` rendered with `context.json`, sent through the
seam. It ends by requiring a final fenced JSON block:

```json
{"summary": "...", "files_changed": ["..."], "notes": "..."}
```

Parsed into `result.json`. `summary` becomes the PR description in the ship phase, so
the PR body costs no extra call.

**Permission mode is unresolved.** In a headless run with no host answering prompts,
anything not pre-approved is auto-denied, so `acceptEdits` permits file edits but a
`Bash` call the settings do not already allow simply fails. That may be enough, or it
may stall every run that needs to install a dep or run a migration. First runs use
`--autonomy full`; if denials bite, the options are a narrower allowlist or
`--agent-cmd` to take the command over. Decide from evidence, not up front. The SDK
backend reports `permission_denials`, so a run that quietly did less says so; the CLI
backend cannot see them, and an empty list there is not proof none occurred.

### qa — Python first, model on failure

Reads `.fast-task.json` from the target repo:

```json
{"lint": "npm run lint", "build": "npm run build", "test": "npm test"}
```

Explicit config, not auto-detection. Each command runs in the worktree; a non-zero exit
is a failure. On failure, one model call per attempt with `prompts/qa_fix.md` and the
failing command's output, re-running the gate after each. Bounded to 2 attempts, then
stop and report — never ship a red gate.

Missing keys are skipped with a warning. A missing `.fast-task.json` skips the phase
entirely with a warning.

This covers the mechanical half of QA. Visual and behavioural verification — "does this
screen look right" — is out of scope; see Non-goals.

### ship — pure Python

1. `gh pr ready <url>`; set the PR body from `result.json.summary`.
2. `set-status In Review`.
3. Post the 🚀 completion comment with the summary and PR link.

## Context bundle

`context.json`, the sole input to the implement call:

```json
{
  "task": {
    "id": "MT251-47", "gid": "1209...", "url": "https://app.asana.com/...",
    "name": "Add CSV export", "description": "...",
    "category": "Feature Request", "status": "In Progress",
    "estimate": "3h", "assignee": "Justin"
  },
  "subtasks":     [{"name": "...", "completed": false}],
  "dependencies": [{"name": "...", "completed": true}],
  "comments":     [{"author": "...", "created_at": "...", "text": "..."}],
  "attachments":  [{"name": "spec.md", "path": "attachments/spec.md", "inline": "..."}],
  "external_links": ["https://figma.com/file/..."],
  "git": {
    "branch": "MT251-47/add-csv-export", "base": "origin/main",
    "worktree": "/Users/.../repo-MT251-47", "pr_url": "https://github.com/..."
  },
  "repo": {"root": "/Users/.../repo-MT251-47"}
}
```

`category` is context for the implement call, not a routing key — the bug/feature fork
that `start-task` uses to pick a sub-skill has no equivalent here, since there is one
implementation path.

## Preconditions gate

Blocking:

- Task is in a not-yet-started status.
- **No incomplete dependencies.** New — the current flow cannot see dependencies at
  all; the contract has `add_dependency` (write) with no read counterpart.
- Assignee is the current user (self-assign when empty; fail when someone else's).

Warning only: active-sprint membership, Estimate. Both are process hygiene the
implementation never reads. `--strict` restores them as blocking.

The premise: a task that passes this gate carries everything needed to implement it, so
the implement call does not need to go hunting.

## Additions to the copied `asana.py`

`tm.py` scripts its Asana *writes* but not these *reads* — the provider's mapping table
points them at raw `curl` recipes in `references/rest.md` for a model to hand-assemble.
They become real verbs here:

| Verb | Endpoint |
|---|---|
| `task subtasks <gid>` | `GET /tasks/<gid>/subtasks?opt_fields=name,completed,gid` |
| `task attachments <gid>` | `GET /tasks/<gid>/attachments?opt_fields=name,download_url,resource_subtype` |
| `task dependencies <gid>` | `GET /tasks/<gid>/dependencies?opt_fields=name,completed` |

Each is ~10 lines against the existing `api_get` helper. Everything else is used as-is —
notably `decide_set_status`, which handles Asana's two-axis status model: try the
"Product Status" custom field, fall back to a board section move.

## A trap worth recording

The published Python docs describe `ResultMessage.usage` as a `MessageUsage` dataclass.
In the installed SDK (0.2.152) it is a plain `dict`. Reading it with `getattr` returns
`None` for every field, silently. `_usage()` reads both shapes, and a regression test
covers it. The lesson generalizes: the seam's telemetry fields are all `Optional`, so a
shape change degrades to "not reported" rather than to a wrong number.

## Known gaps

- **Not yet run against a live task.** The seam, registry, backends, phases and state
  machine are exercised by tests and an end-to-end run on the `echo` backend; no real
  model call has been made through it.
- **External links are text only.** Python extracts Figma/Notion/Drive URLs but cannot
  read them, and the implement call runs without MCP servers. `mcp_servers` is on the
  SDK's options, so the SDK backend *could* read one. It does not yet.
- **Copy drift.** `asana.py` diverges from the plugin's `tm.py` the moment either
  changes.
- **No pause flow.** A blocked run stops and reports; it does not commit WIP or post a
  blocking question.

## Testing

`prologue` is the testable half. Its pure functions — slugify, gate evaluation, URL
extraction, bundle assembly — get unit tests against fixture JSON, following
`readiness.py`'s split of pure policy from live fetch. The seam gets its own suite: the
registry, the tool vocabulary, each backend's mapping tables and failure reporting, and
the CLI backend's envelope parsing. Phases that shell out to a model, `gh`, or Asana are
validated by running them.

```bash
python3 tests/test_pure.py     # slug, gate, link extraction, task key
python3 tests/test_agent.py    # the seam, registry, backends, envelope
```
