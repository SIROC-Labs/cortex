# Test ladder (unattended runs)

A change is proved by **every rung it can reach**, not by the cheapest rung that comes back green. Run bottom to top, record a result per rung; a rung with no recorded result was skipped.

| # | Rung | Proves | Out of reach only when |
|---|---|---|---|
| 1 | **Static** — the repo's declared lint, typecheck and any whole-file quality gate, over every file the branch touched | it compiles and every touched file conforms in full | never |
| 2 | **Unit** — pure logic: mappers, parsers, formatters, reducers, query builders, gating and scoring rules | the logic is right in isolation | the change contains no pure logic |
| 3 | **Integration against real dependencies in containers** — the repo's own database, cache, queue, seeded through its own fixtures | the real driver, real constraints, real SQL | the change touches no dependency the repo ships a container for |
| 4 | **In-process API** — the app's test client over the real router | status codes, payload shape, error branches, ordering | no HTTP surface changed |
| 5 | **Element-scoped browser harness** — a standalone page mounting only what changed, with fixture data, driven through the browser MCP | rendered DOM, styles, breakpoints, interaction, console clean | no UI changed |
| 6 | **Whole-app local run** — app plus its own containers | the real flow end to end | some dependency the flow needs cannot run locally |
| 7 | **Live run** | — | **always; never yours** |

Three rules:

- **A mock is for a dependency that cannot run here.** The repo ships a container, so it can. A mock in its place is a hole you chose.
- **"Out of reach" is a fact about the change, never about effort.** "No HTTP surface changed" is a fact; "the fixtures were fiddly" is rung 3's work.
- **A red rung is a defect until proven otherwise.** Never re-scope a test to pass it, never lower a rung because the one above went green.

## Rung 1 — declared entrypoints, whole touched set

Read the commands out of the repo (`Makefile`, `package.json` scripts, `pre-commit` config, `CLAUDE.md`); never call the underlying runner by hand — the wrapper supplies the working directory and config. In a monorepo the entrypoint often lives in the sub-package you changed.

Build the touched-file list from the branch, so a file touched in an earlier commit of this run is still in it:

```bash
grep -q '^/\.qa/$' .git/info/exclude || printf '/.qa/\n' >> .git/info/exclude
mkdir -p .qa
{ git diff --name-only --diff-filter=ACMR "origin/<base>...HEAD"
  git diff --name-only --diff-filter=ACMR
  git ls-files --others --exclude-standard
} | sort -u > .qa/touched.txt
```

An empty list on a shipping run means the implementation step did nothing: a `failed` stop, not a green rung. When the repo declares a whole-file quality gate, run it over that list: a violation on a line you did not write is still this run's work — touching the file made its body yours, and the repo's commit hook applies the same bar. Never narrow the gate (`noqa`, `eslint-disable`, ignore files, `--no-verify`).

Report with the file count and both halves: `quality gate: 7 touched files → clean; lint + typecheck green`.

## Rung 3 — containers, isolated

Use the repo's own declared target first (a `make test-integration`, a compose profile). Isolate by compose project so nothing touches the operator's running stack:

```bash
export COMPOSE_PROJECT_NAME="agent-<task-ref>"
docker compose -f <the repo's compose file> up -d --wait
# … the repo's integration target …
docker compose -p "agent-<task-ref>" down -v
```

Tear down on every exit path, including a `failed` stop. Never `docker stop`/`rm`/`prune` unscoped. Port collisions are the expected failure: publish on ephemeral ports or reach services over the compose network; a collision is not a reason to mock. Seed through the repo's fixtures or migrations, never hand-written inserts.

## Rung 4 — in-process API

The app's own test client over the real router, with the real database from rung 3. Assert on what a caller sees: status code, exact payload shape and keys, the error branch, pagination or ordering. A test asserting only `200` proves the route exists and nothing else.

## Fixtures are recorded, never invented

An invented fixture agrees with your reading of the payload, which is the reading the code encodes; every rung above it goes green on the same mistake. A fixture's shape and units come from outside your head, in this order: a payload recorded from the real API (a checked-in sample, a cassette, a response pasted on the card); the API's own schema or example; the repo's existing fixtures for that endpoint. None → the units are an open contract question → `clarification` stop. State the provenance in the verification report.

## Rung 5 — element-scoped browser harness

Mount only what changed, with recorded fixture data, in a standalone page, and drive it through the browser MCP. Two variants; say which you used:

- **Component harness** — a temporary entry (`.qa/element.html` + `.qa/element.tsx` or the stack's equivalent) importing the real component from the worktree, rendered under every state the change can produce, served by the repo's own dev server. Proves behaviour: branches, formatting, gating, empty, loading and error states. Wrap in the real provider with a fixture value; never edit the component to make it mountable.
- **Static markup harness** — a plain HTML file with the project stylesheet and the markup copied out. Proves CSS only: layout, overflow, wrapping, breakpoints, truncation.

Render every state side by side, resize through the real breakpoints, screenshot, read the DOM, and read the console: an error there is a defect. Harness files live in `.qa/` (excluded above, never committed) and are pasted into the verification report with the command that serves them.

## Rung 6 — whole-app local run

Permitted only when every dependency the flow touches runs locally. Drive the real user flow through the browser MCP and assert on what the page shows. The moment the flow needs a staging API or a real third-party account, this rung is out of reach; pointing the local app at a deployed backend is rung 7 in disguise.

## Rung 7 — live checks, handed over

Never run. State each as one line with the exact command or URL, under **Left for you (live)** in the verification report. A live check left over is the operator's half of the verification, not a gap in the change.
