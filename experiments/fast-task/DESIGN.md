# fast-task — design

An experiment: run the `start-task` lifecycle as an explicit Python program, calling an
LLM only where one is genuinely required.

Status: design, not yet implemented.

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

This experiment replaces the brain, not the hands: the same Asana calls, sequenced by
Python in a fixed order. Zero model turns to reach step 9, then one `claude -p` for the
part that needs thought.

## Non-goals

- Replacing the `start-task` skill. It stays untouched; this is a parallel path.
- Working under OpenCode or Codex. This is deliberately Claude-Code-specific, which is
  precisely why it does not live in `plugins/`.
- Provider neutrality. Asana only.
- Covering the pause/resume-on-blocker flow, the QA sub-flow's visual verification, or
  post-ship code review.

## Layout

```
experiments/fast-task/
  DESIGN.md         # this file
  README.md         # usage
  fast_task.py      # the orchestrator — all control flow
  asana.py          # tm.py, copied, plus three new read verbs
  cache_util.py     # copied dependency of asana.py
  prompts/
    implement.md    # template for the implementation call
    qa_fix.md       # template for the failure-repair call
```

Nothing here imports from `plugins/`. `asana.py` and `cache_util.py` are copies, taken
once; they are ours to edit and will drift from the originals. That is accepted — the
alternative couples an experiment to a plugin that is still changing.

## Phases

Each phase is separately invocable and resumable.

```
fast_task.py run       <task-url>   # all four, in order
fast_task.py prologue  <task-url>   # zero model turns
fast_task.py implement <task-id>
fast_task.py qa        <task-id>
fast_task.py ship      <task-id>
```

State lives in `.fast-task/<task-id>/` at the **main repo root**, not in the worktree —
the worktree does not exist yet when the prologue starts writing, and it may be removed
after ship while the state is still wanted. It holds `context.json`, `result.json`,
`state.json`, `attachments/`. Re-running a phase overwrites its own output. `run` skips
phases already marked done in `state.json`.

`<task-id>` is the human key (`MT251-47`) read from the task's ID custom field, falling
back to the Asana gid when the project has no such field — the same field the readiness
gate treats as non-blocking, so it genuinely can be absent.

### prologue — pure Python, no LLM

1. Parse the task URL to a gid (`asana.py ref parse`).
2. Fetch the task (`task get`) — name, description, assignee, status, custom fields.
3. Assignee: if empty, self-assign and say so; if someone else, fail with a message.
4. Preconditions gate (below).
5. Fetch subtasks, dependencies, comments, attachments. Download non-image attachments
   inline; download images to `attachments/` and pass paths (the implement call can
   read image files).
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

### implement — one LLM call

```
claude -p --disable-slash-commands --strict-mcp-config --no-session-persistence \
       --add-dir <repo-root> --permission-mode acceptEdits --output-format json
```

`--disable-slash-commands` turns off all skills; `--strict-mcp-config` with no
`--mcp-config` loads no MCP servers. `--bare` would go further (no hooks, no plugin
sync, no auto-memory) but authenticates only via `ANTHROPIC_API_KEY` or `apiKeyHelper`,
never OAuth or keychain — so it would move billing off the subscription. Not used.
The full command is overridable with `--agent-cmd`.

**Permission mode is unresolved.** In `-p` with no host answering prompts, anything not
pre-approved is auto-denied, so `acceptEdits` permits file edits but a `Bash` call the
settings do not already allow simply fails. That may be enough, or it may stall every
run that needs to install a dep or run a migration. First runs use `acceptEdits`; if
denials bite, the options are an explicit `--allowedTools` list or
`--dangerously-skip-permissions`. Decide from evidence, not up front.

The prompt is `prompts/implement.md` rendered with `context.json`. It ends by requiring
a final fenced JSON block:

```json
{"summary": "...", "files_changed": ["..."], "notes": "..."}
```

Parsed into `result.json`. `summary` becomes the PR description in the ship phase, so
the PR body costs no extra call.

### qa — Python first, LLM on failure

Reads `.fast-task.json` from the target repo:

```json
{"lint": "npm run lint", "build": "npm run build", "test": "npm test"}
```

Explicit config, not auto-detection. Each command runs in the worktree; a non-zero exit
is a failure. On failure, one `claude -p` call per attempt with `prompts/qa_fix.md` and
the failing command's output, re-running the gate after each. Bounded to 2 attempts,
then stop and report — never ship a red gate.

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
notably `decide_set_status` (`tm.py:1468`), which handles Asana's two-axis status model:
try the "Product Status" custom field, fall back to a board section move.

## Known gaps

- **External links.** Python extracts Figma/Notion/Drive URLs but cannot read them, and
  the implement call runs without MCP servers. The URLs are passed through as text; if
  a task's real content lives in Figma, this run will not see it. Accepted for now.
- **Copy drift.** `asana.py` diverges from `tm.py` the moment either changes.
- **No pause flow.** A blocked run stops and reports; it does not commit WIP or post a
  blocking question.
- **Claude Code only.** By design.

## Testing

`prologue` is the testable half. Its pure functions — slugify, gate evaluation,
URL extraction, bundle assembly — get unit tests against fixture JSON, following
`readiness.py`'s split of pure policy from live fetch. Phases that shell out to
`claude`, `gh`, or Asana are validated by running them.
