# Testing Infrastructure

What the project needs beyond the tests themselves. A test suite without infrastructure is unenforceable.

## Coverage

### Principles

- **Exclude** generated code, type definitions, barrel exports, config files, and framework glue
- **Threshold:** on a greenfield project, ~70% global is a reasonable starting point. On an existing codebase, set the threshold at current coverage and ratchet up — never set a threshold that fails the build on day one.
- **Critical paths** (auth, payments, data integrity) should have higher thresholds via per-directory overrides
- **CI enforces the threshold** — coverage drop fails the build
- Track **trends**, not absolutes — coverage going down on a PR is a signal worth investigating
- Visible to the team — not buried in logs

## CI Pipeline

### Minimum viable test job

The test job must:
1. Install dependencies (cached)
2. Run static analysis (type checking, linting)
3. Run tests with coverage
4. Upload coverage report as artifact
5. Fail on any step failure — no `continue-on-error` for tests

### Slow/heavy tests (separate job)

Tests that are slow, need special infrastructure, or have external dependencies should run in a separate job:
- Run in parallel with the fast test job
- Have their own timeout (longer)
- Be required for merge or advisory, depending on project maturity

Examples: E2E browser tests, database integration tests, API contract tests, load tests.

### PR gates

| Gate | Required | Advisory |
|---|---|---|
| Static analysis (types + lint) | Yes | — |
| Unit/integration tests | Yes | — |
| Coverage threshold | Yes | — |
| Coverage delta (diff) | — | Yes (flag if coverage decreases) |
| Slow/heavy tests | Depends on project | — |
| Build succeeds | Yes | — |

## Flake Detection

### What to track

- Test pass rate per test file over the last N runs
- Tests that fail then pass on retry (the retry IS the signal)
- Tests that fail only in CI (environment-dependent flake)

### Response protocol

1. **First flake occurrence:** investigate immediately. Most flakes are real bugs (race condition, shared state, timing).
2. **Cannot fix immediately:** quarantine with `skip` + comment linking to the tracking issue.
3. **Quarantine budget:** agree a cap with the team (a small fraction of the suite). When the project exceeds it, stop feature work and fix flakes.
4. **Never add retry logic to mask flakes.** Retries hide problems.

## Performance Benchmarks

### When to benchmark

- Operations that process user-visible data
- Handlers that could regress under load
- Operations with known performance constraints (must complete in < Xms)

### How to benchmark

- Use the test runner's built-in timing or a dedicated benchmark tool
- Run on consistent hardware (CI, not local machines with variable load)
- Track trends over time — a single number means nothing
- Set a regression threshold appropriate to the operation's variance, and fail the build when the latest run breaches it

### What NOT to benchmark

- Every function (noise drowns signal)
- Code that's I/O bound (benchmark the I/O mock, not the code)
- Startup/initialization (unless it's user-facing)

## Test Reporting

### In CI output

- **What passed** — collapsed/summarized, not line by line
- **What failed** — expanded with full error, expected vs actual, file:line
- **Duration** — total and per-suite, flag slow suites
- **Coverage summary** — lines/branches/functions with delta from base branch

### In PR

- Coverage report as PR comment or status check
- Failed test names visible without clicking into logs
- Clear pass/fail status — no ambiguity
