# Backend Testing Patterns

How to test a backend. Universal fundamentals live in `../generic-testing/process.md` — determinism, AAA, behavior-over-implementation, test naming, edge cases. Apply those on every test. This file covers what is specific to backends.

## The Spine

- **Integration is the default and the biggest slice.** Exercise real dependencies through containers — Testcontainers (JVM/Go/Node), `testcontainers-python`, or the ecosystem equivalent. Real DB, real cache, real queue. **Never mock infrastructure.**
- **API / endpoint tests are integration tests** — boot the app with its containerized dependencies, send real HTTP, assert on status, body, headers, and the error contract. They are not a separate tier.
- **External services are replaced by spec-driven fakes** — see `references/contract-testing.md`. The fake runs in a container, seeded from the external contract; responses are schema-validated so the fake can't drift.
- **Unit tests cover only isolated internal business logic** — pure functions and domain logic with no I/O. Anything touching I/O or a boundary is an integration test.

## The Decision Rule

For every behavior you are about to test, ask one question:

> Does it touch I/O or a boundary (DB, HTTP, queue, cache, filesystem, clock, external API)?

- **Yes → integration test** against a real container (or a spec-driven fake for external boundaries).
- **No, it's pure logic → unit test.**

If you find yourself mocking a repository, a DB driver, or an HTTP client to unit-test a handler, stop — that is an integration test wearing a disguise. Boot the real thing in a container instead.

## Database Integration

Real DB in a container, never an in-memory substitute that behaves differently from production.

**Isolation between tests** — pick one strategy and apply it consistently:

| Strategy | How | Use when |
|---|---|---|
| **Transaction rollback** | Open a transaction in setup, roll back in teardown | Default. Fastest. Each test sees a clean DB. |
| **Truncate** | Truncate affected tables between tests | Code under test manages its own transactions/commits. |
| **Fresh schema** | New schema/database per test or per file | Tests assert on transaction/commit behavior itself. |

Run migrations against the container once at suite start — the schema under test must be the real migrated schema, not a hand-built one. Tests must pass in any order and in parallel; if they don't, they share state.

## Test Data

Build data with factories/builders, not hand-rolled literals copied between tests.

- A factory produces a valid default; each test overrides only the fields it cares about.
- Seed through the application's real write path or a factory that mirrors it — not raw SQL that can drift from constraints.
- Setup/teardown is per-test (`beforeEach`/fixtures), never accumulated across tests.

## Async, Jobs, and Messaging

Background jobs, queues, and event flows get real brokers in containers (Kafka, RabbitMQ, Redis).

- **Await completion deterministically** — poll for the observable outcome (row written, message acked, downstream state changed) with a bounded timeout. **Never `sleep` for a fixed duration.**
- Assert on the effect, not on internal scheduling details.
- Drain/reset the broker between tests so messages don't leak across cases.

### Task orchestration frameworks (Celery, Sidekiq, BullMQ, …)

Frameworks that dispatch work to background workers — **Celery** (Python), Sidekiq (Ruby), BullMQ (Node), Dramatiq/RQ/ARQ (Python), Temporal, Spring `@Async`/Quartz (JVM) — get tested at three levels. Apply the decision rule per piece:

1. **The task's business logic in isolation → unit test.** Call the plain function the task wraps (not via `.delay()`/`.apply_async()`/`enqueue`) and assert on its return/effect. Pure logic, no broker.
2. **The dispatch → execution → effect path → integration test.** Run a **real broker and a real worker** in containers, enqueue the task the way production does, and poll for the observable effect. This is the test that proves serialization, routing, retries, and the worker wiring actually work.
3. **Scheduling/retry/routing config → integration test** where it matters (e.g. a task is retried on a specific exception, or a beat/cron schedule fires).

**The eager-mode trap.** Celery's `task_always_eager` (and equivalents that run jobs inline/synchronously) execute the task in-process, bypassing the broker, the serializer, routing, and retry handling. That is a **partial mock**: it can prove the logic runs but hides the exact failures backend integration tests exist to catch (non-serializable args, wrong queue, retry misconfiguration). Treat eager mode as a convenience for exercising logic only — **never** as a substitute for at least one real broker+worker integration test on the enqueue→execute→effect path.

- Reset broker/result-backend state between tests (the broker is a container; the result backend too if used).
- Await the worker by polling the task's effect or result, with a bounded timeout — never a fixed `sleep`.
- `references/stack-detection.md` includes detecting the orchestration framework and its broker so the right containers are spun up.

## Auth in Tests

Real services usually require authentication that, in production, is performed manually. Automated tests cannot have a human in the loop. Decide per service:

- **Can the credential be reproduced in-test?** → mint it. Sign a test JWT with a test key the app trusts, seed a session directly, or run a fake OIDC provider container (it becomes one of the spec-driven fakes). This is the **default** — it runs anywhere, including CI, with no manual step.
- **Genuinely cannot be reproduced?** → a human obtains a token once and stores it as a **gitignored local secret**; only the local-only heavy suite injects it. Never commit it; never rely on it in CI.

Never make an automated test depend on an interactive login.

## Dependencies With No Testcontainers Module

"No dedicated module" almost never means "cannot containerize." Work down this tree:

1. **A dedicated module exists** → use it.
2. **No module, but an official Docker image exists** (e.g. ClickHouse, and most services) → use a **generic container**: point it at the image, set the env, and give it an explicit wait strategy (port open, HTTP health endpoint, or a log-line regex). Wire ports manually. **This is the primary answer.**
3. **Cloud-only service** (DynamoDB, BigQuery, S3, …) → use the vendor's local emulator (LocalStack, fake-gcs-server, …) in a container.
4. **Truly impossible to containerize** → treat it as an external boundary: a spec-driven fake (`references/contract-testing.md`) plus a thin contract check against a shared real instance, run local-only.

The rule: drop to a generic container before you reach for a mock. Keep the dependency real.

## Container Cost & Flakiness

Containers are the #1 source of slow and flaky backend suites. Manage them:

- **Reuse, don't re-create.** Share a container across a test file/module (session/module-scoped fixtures); recreate only the *data* per test, not the container.
- **Parallel isolation.** Let the runtime assign random host ports; never hardcode a port. Give each parallel worker its own schema/namespace.
- **Explicit wait strategies.** A container that "started" is not a container that's "ready." Wait on a health signal, never a sleep.
- **Image pinning.** Pin image tags (`postgres:16`, not `postgres:latest`) so the suite is reproducible and the evidence block can name exact versions.
- **Heavy suites run local, not in CI** — see `references/infrastructure.md`.

## Expected Output

A finished backend-testing deliverable is:

- **Integration tests** covering the endpoints/flows changed, running against real containerized dependencies, with spec-driven fakes standing in for external services.
- **Unit tests** only where there is isolated pure logic worth proving in isolation.
- **Stale tests removed.** When a behaviour becomes covered by an integration test, delete the superseded test that mocked it (assertions on call args, operator dicts, or generated query strings) — don't leave both. Keep only genuinely-valuable pure-logic units, and preserve any unique behaviour the deleted test covered as an integration test.
- **Deterministic** — no `sleep`, no shared state, passes in any order and in parallel.
- **A green run captured as PR evidence** — the brief evidence block from `references/infrastructure.md`, not a wall of logs.

## Anti-Patterns

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| Mocking the DB / repository | Proves the mock, not the query | Real DB in a container |
| Asserting on the generated SQL / query string (substring match) | A query that is never executed can't be proven correct — won't catch a parse error, a wrong join, a shadowed alias, or wrong rows | Execute it against a real engine in a container; assert on the rows returned |
| Asserting on the operator dict / call args passed to a mock DB | Proves the code built a dict, not that the store accepts or correctly applies it | Real DB in a container; assert on what was actually persisted/returned |
| In-memory DB standing in for the real one | Different SQL dialect/behavior | Same engine, containerized |
| `sleep(2)` waiting for a job | Non-deterministic, slow | Poll for the outcome with a timeout |
| Eager mode as the only async test | Bypasses broker/serialization/retries | At least one real broker+worker integration test |
| Hardcoded container ports | Breaks parallelism, flaky | Random host ports |
| New container per test | Suite crawls | Reuse container, reset data |
| Unit-testing a handler with everything mocked | Tests wiring, not behavior | Integration test through real HTTP |
| Fake that returns hand-typed JSON | Drifts from the real contract | Spec-driven fake, schema-validated |
| Committing a real auth token | Leaks secrets, breaks in CI | Mint in-test, or gitignored local secret |
