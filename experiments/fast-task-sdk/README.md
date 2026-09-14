# fast-task-sdk

The `start-task` lifecycle as an explicit Python program, with every model call behind
a provider-agnostic seam. Same phases as [`fast-task`](../fast-task/); the difference
is that the model is reached through a swappable backend — the Claude Agent SDK by
default — rather than a `claude -p` subprocess.

That buys real cost telemetry, a dollar ceiling, and visibility into denied tool
calls. See [DESIGN.md](DESIGN.md).

This is an experiment. It is not a skill, it is not agent-agnostic, and nothing in
`plugins/` depends on it.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export ASANA_PERSONAL_ACCESS_TOKEN=...      # in ~/.zshrc
```

The SDK authenticates the way Claude Code does — an existing subscription login
works, no API key needed. Also requires `git` and `gh` (authenticated).

Check what's usable:

```bash
.venv/bin/python fast_task_sdk.py backends
```

```
Backends
  [x] claude-sdk    (default)
  [x] claude-cli
  [x] echo
```

Optionally, in the target repo, a `.fast-task.json` describing the QA gate:

```json
{"lint": "npm run lint", "build": "npm run build", "test": "npm test"}
```

## Use

From inside the target repository:

```bash
fast_task_sdk.py run https://app.asana.com/0/123/456
```

Or a phase at a time — each is resumable:

```bash
fast_task_sdk.py prologue https://app.asana.com/0/123/456   # no model calls
fast_task_sdk.py implement MT251-47
fast_task_sdk.py qa        MT251-47
fast_task_sdk.py ship      MT251-47
fast_task_sdk.py status    MT251-47      # phases + per-call cost breakdown
```

### Flags

| Flag | Default | |
|---|---|---|
| `--backend` | `claude-sdk` | `claude-sdk`, `claude-cli`, `echo` |
| `--model` | backend default | |
| `--max-turns` | 60 | turn ceiling per call |
| `--budget` | none | hard USD ceiling per call, where supported |
| `--autonomy` | `full` | `read-only`, `edit`, `full` |
| `--no-project-context` | off | skip the repo's CLAUDE.md / AGENTS.md |
| `--repo` | cwd | target repository |

Comparing transports on the same task is the point — same prologue, same prompt,
different backend:

```bash
fast_task_sdk.py implement MT251-47 --backend claude-sdk
fast_task_sdk.py implement MT251-47 --backend claude-cli
fast_task_sdk.py status    MT251-47
```

`--backend echo` runs the whole flow with no model and no cost, for exercising the
phases themselves.

## Adding a provider

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

Two contracts: never raise (report `ok=False` with an `error`), and declare anything
in the request you could not honour via `result.unsupported`.

## Tests

```bash
.venv/bin/python tests/test_agent.py    # the seam, registry, backends
.venv/bin/python tests/test_pure.py     # slug, gate, link extraction
```

## Known gaps

- **Not yet run against a live task.** Tests and an `echo` end-to-end pass; no real
  model call has gone through it.
- **External links are text only** — the SDK backend could carry `mcp_servers`, but
  doesn't yet, so a Figma or Notion link is passed as a URL it cannot open.
- **`asana.py` is a copy** of the plugin's `tm.py` and will drift.
- **The orchestrator is duplicated** from `fast-task` rather than shared.
