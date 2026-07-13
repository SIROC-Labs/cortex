# Running the Suites

Backend-qa must confirm the tests actually pass — both the fast suite and the heavy integration
suite. Discover the runner from the project; do not assume.

## Step 1: Discover the runner and the suite split

Read the project before running anything (see
[backend-testing/references/stack-detection.md](../../backend-testing/references/stack-detection.md)
for how to inspect language, runner, and container library):

- **Runner & config** — `Makefile` targets (`make tests`, `make integration-tests`), `pytest.ini` /
  `pyproject.toml`, `package.json` scripts, `build.gradle`, `go test`, etc. Note that an active
  `pytest.ini` overrides `pyproject.toml [tool.pytest.ini_options]`.
- **The split** — integration tests are usually **excluded from the default run** (e.g. pytest
  `addopts = -m 'not integration'`) so CI and pre-commit stay Docker-free. Find the marker/tag and the
  separate target that includes them. The fast suite passing tells you nothing about the integration
  suite.
- **Container dependency** — the integration suite needs a Docker daemon and pulls pinned images
  (testcontainers). Confirm Docker is available *before* running; if it isn't, that's a blocker to
  surface, not a reason to skip.

## Step 2: Run the fast suite

Run the default suite scoped to the change where possible (changed module's `test/` dir), then the
whole fast suite. All green is the floor, not the goal.

## Step 3: Run the integration suite — for real

Run the heavy target (`make integration-tests` or the marker-selected run). This is the step that
actually exercises datasources, queries, and clients against real containers — the coverage that
matters most for a backend change.

- **A skip is not a pass.** If integration tests are collected-but-skipped (missing Docker, missing
  env, an `@skip`), the behaviours they own are **unverified**. Report them as such.
- **Scope when the full suite is slow.** Run the changed module's integration tests first for a fast
  signal, then widen. Note anything you did not run — never imply full coverage you didn't execute.

## Step 4: Interpret results

- **Failure** — capture the failing test id and the assertion/error. A failure in a test covering a
  changed behaviour blocks the QA. Investigate before reporting; don't hand back a raw traceback.
- **Flake** — re-run a suspected flaky test in isolation a few times. A test that passes only
  sometimes is a reliability gap, report it (see
  [generic-testing/references/infrastructure.md](../../generic-testing/references/infrastructure.md)
  on flake detection).
- **Error vs failure** — a collection/import error (stale venv, missing dep) means the suite never
  ran; resolve or surface it. Don't read "0 failed" off a run that collected nothing.

## What to carry into the report

Exact commands run, counts (passed / failed / skipped) for **each** suite separately, the
environment (runner version, Docker yes/no, image tags if relevant), and any subset you scoped to.
Feed this into [reporting.md](reporting.md) as the run-evidence block.
