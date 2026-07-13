# Backend Stack Detection

Before writing any test, learn the project's setup by inspecting it directly. Do not assume the language, runner, or container library.

## What to read

1. **Dependency manifest** — `pyproject.toml`/`requirements.txt` (Python), `package.json` (Node), `pom.xml`/`build.gradle*` (JVM), `go.mod` (Go), `Gemfile` (Ruby). It names the framework, the test runner, and whether a testcontainers binding is already present.
2. **Test runner config** — `pytest.ini`/`pyproject.toml [tool.pytest]`, `jest.config.*`/`vitest.config.*`, JUnit/Surefire config, `go test` conventions. This is your source of truth for how tests are invoked.
3. **An existing test file** — pick a representative one. It shows import style, fixture/factory helpers, file naming, location (co-located vs `tests/`), and how containers are spun up if at all. Match what's there.
4. **Container / compose files** — `docker-compose*.yml`, `Dockerfile`, existing testcontainers usage. They reveal which dependencies the app needs and at what versions.
5. **CI workflow files** — see what already runs on PRs (lint, type-check, unit, integration, coverage) and which tests are excluded.

## What to derive (don't pre-list)

- Language, framework, and the exact test command (read it from scripts/config — don't guess the package manager or invocation).
- Test runner and its config.
- Whether a testcontainers binding exists; if not, note that adding one is part of the work.
- The app's runtime dependencies (DB, cache, queue, external APIs) and their pinned versions.
- Any **task-orchestration framework** (Celery, Sidekiq, BullMQ, Dramatiq/RQ/ARQ, Temporal, Quartz) and the broker/result-backend it uses — so the right broker + a worker get spun up for integration tests (see `../process.md` → Task orchestration frameworks).
- Test file naming and location conventions.

## Testcontainers binding by ecosystem

If the project hasn't set one up, these are the standard bindings to introduce (confirm the version against the project):

| Language | Binding |
|---|---|
| Python | `testcontainers` (testcontainers-python) + `pytest` fixtures |
| Node/TS | `testcontainers` (Testcontainers for Node) |
| JVM | `org.testcontainers` JUnit integration |
| Go | `github.com/testcontainers/testcontainers-go` |
| Ruby | `testcontainers-ruby` |

For a dependency with no dedicated module, use the binding's generic-container API (see `../process.md` → Dependencies With No Testcontainers Module).

## When to stop and advise

Raise it with the user **before** writing tests if:

- No test runner is configured — testing isn't set up; agree on the stack first.
- The test command is broken or fails on a clean checkout.
- Docker is unavailable in the environment where integration tests must run — testcontainers needs a working Docker daemon; confirm how/where heavy tests run.
- Two conventions coexist (file naming, location, container setup) — ask which to follow.
- There are no existing tests in the area you're touching — propose the convention you'll establish and confirm before generating files.
