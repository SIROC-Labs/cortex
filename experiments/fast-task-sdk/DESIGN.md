# fast-task-sdk — design

The same lifecycle as the sibling [`fast-task`](../fast-task/DESIGN.md) experiment,
with every model call behind a provider-agnostic seam and driven through the Claude
Agent SDK rather than a `claude -p` subprocess.

Status: implemented, not yet run against a live task.

## Why a second experiment

`fast-task` proved the control-flow point: steps 0–9 need no model. It left two
things unresolved, and both are properties of the transport, not the design.

**Cost is unmeasurable.** The whole premise is "faster and cheaper", but shelling out
to `claude -p` gives back a text envelope. You can time it; you cannot reliably say
what it cost. The SDK returns a `ResultMessage` carrying `total_cost_usd`, `usage`,
and `num_turns` — so the experiment can actually be evaluated instead of believed.

**Denied tools are invisible.** `-p` auto-denies anything not pre-approved, silently.
A run can finish "successfully" having skipped half the work because a `Bash` call was
refused. The SDK reports `permission_denials`, so the runner can say so.

The SDK also authenticates exactly as Claude Code does, which is what makes this
viable: a subscription login works with no API key. That was the blocker that ruled
out `--bare` in the first experiment.

## Why a seam rather than just importing the SDK

`claude_agent_sdk` is imported in exactly one file. Everything else speaks
`AgentRequest` / `AgentResult` / `AgentBackend`. Three reasons:

1. **The experiment is about the shape of the flow, not the vendor.** Coupling the
   orchestrator to one SDK would make "is this better?" and "is this SDK good?"
   the same question.
2. **The backends are genuinely comparable.** `claude-sdk` and `claude-cli` run the
   same prologue, the same prompt, the same repo — differing only in transport. That
   is a measurement, not a guess.
3. **Swapping providers is a file.** Adding one is a module implementing
   `AgentBackend` plus a row in `agent/__init__.py`.

## The seam

```
agent/
  base.py         AgentRequest · AgentResult · AgentBackend · tool vocabulary
  __init__.py     registry — the one place a provider is named
  claude_sdk.py   Claude Agent SDK              (default)
  claude_cli.py   `claude -p` subprocess        (parity with fast-task)
  echo.py         no model, no cost             (exercises the flow for free)
```

`AgentRequest` is intent, not vendor configuration: a prompt, a working directory, an
autonomy level (`read-only` / `edit` / `full`), ceilings on turns and dollars, and
whether to load the project's own conventions. Tools are named neutrally
(`read_file`, `edit_file`, `run_command`); each backend maps them.

Two rules make the abstraction honest rather than decorative:

- **A backend never raises.** Failures come back as `ok=False` with an `error`. The
  orchestrator handles one failure shape regardless of provider.
- **A backend declares what it dropped.** Anything in the request it cannot express
  lands in `result.unsupported`, and the runner warns. The CLI backend has no budget
  ceiling, so `max_budget_usd` shows up there rather than being silently ignored —
  the caller is never told it got something it didn't.

Telemetry is optional and never invented. A backend that cannot report cost leaves it
`None`, and the ledger prints "cost not reported" rather than `$0.00`.

## Phases

Identical to `fast-task` — `prologue` (zero model calls), `implement`, `qa`, `ship` —
plus a `backends` subcommand listing which providers are usable here and why not.

State gains `cost.json`: one entry per model call with backend, model, cost, tokens,
turns and duration. `status` prints the per-call breakdown and the run total, which is
the number this experiment exists to produce.

## What the SDK buys, concretely

| | `claude-cli` | `claude-sdk` |
|---|---|---|
| Cost per call | envelope, best-effort | `total_cost_usd` |
| Token counts | envelope, best-effort | `usage` |
| Turn ceiling | `--max-turns` | `max_turns` |
| Dollar ceiling | — | `max_budget_usd`, enforced server-side |
| Denied tools | invisible | `permission_denials` |
| Project context | all-or-nothing | `setting_sources` |

## A trap worth recording

The published Python docs describe `ResultMessage.usage` as a `MessageUsage`
dataclass. In the installed SDK (0.2.152) it is a plain `dict`. Reading it with
`getattr` returns `None` for every field, silently — the run succeeds, the ledger
fills with nulls, and the one number the experiment exists to measure is quietly
absent. `_usage()` reads both shapes, and a regression test covers it.

The lesson generalizes: the seam's telemetry fields are all `Optional`, so a shape
change degrades to "not reported" rather than to a wrong number.

## Known gaps

- **Not yet run against a live task.** The seam, registry, backends, phases and cost
  ledger are exercised by tests and an end-to-end run on the `echo` backend; no real
  model call has been made through it.
- **`asana.py` is a third copy** — one in the plugin, one per experiment. All three
  will drift.
- **External links are still text only.** `mcp_servers` is on `ClaudeAgentOptions`,
  so the SDK backend *could* read a Figma or Notion link. It does not yet.
- **The orchestrator is duplicated** from `fast-task` rather than shared. Deliberate
  while the two diverge; if they converge, one should absorb the other.
