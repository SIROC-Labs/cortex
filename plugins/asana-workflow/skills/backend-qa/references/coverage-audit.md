# Coverage Audit

Scope the change, map its behaviours to tests, and judge whether the coverage is enough. This is the
heart of backend-qa — the run in [running-tests.md](running-tests.md) only confirms green; this step
decides whether green *means* anything.

## Step 1: Resolve the scope

Pin down exactly what is under QA before reading a single test:

- **Branch / PR** — `git diff --stat <base>...HEAD` (default base is the repo's main branch). The
  changed production files are your subject; the changed test files are your evidence.
- **Module** — the named package/directory and its public surface.
- **Ask if ambiguous.** "QA this" with no scope and a dirty tree → confirm whether the subject is the
  working-tree diff, the branch vs main, or a specific module.

Separate production changes from test changes. A diff that is *all* test files is a test-quality
review (still in scope); a diff with production changes and no test changes is an immediate red flag.

## Step 2: Enumerate the changed behaviours

For each changed production file, list the **behaviours** that changed — not lines, behaviours:

- a new or modified branch/condition (each side is a behaviour),
- a query or datasource (does it parse, filter, dedup, page, and map rows correctly?),
- an external client call (success, each error-status mapping, retry/timeout),
- an error boundary (fail-open vs fail-closed — which, and is it honoured?),
- a guard / validation rule.

This list is the denominator. Coverage is measured against behaviours, never against line counts.

## Step 3: Map behaviours → tests

For each behaviour, find the test(s) that exercise it and classify each:

- **Integration** — runs against a real dependency (container DB, real HTTP fake). Required for
  anything touching I/O: datasources, queries, clients, repositories.
- **Unit** — isolated pure logic, no I/O (a validator, a clause builder, a guard).
- **Contract** — an external third-party service driven through a spec-driven fake with a drift guard.

Judge each against the bar in [backend-testing/process.md](../../backend-testing/process.md). A test
that *names* a behaviour but only asserts on a mock's recorded call, a generated SQL string, or a
stubbed return value does **not** cover it.

## Step 4: Classify the gaps

Produce an explicit gap list. Each gap is one of:

| Gap type | What it looks like | Severity |
|---|---|---|
| **Uncovered behaviour** | a changed branch/query/mapping with no test hitting it | high |
| **Mock-masking** | I/O behaviour "covered" only by a mock or SQL-string assertion | high — green but blind |
| **Gate violation (mockable-as-integration)** | a *unit* test mocks a boundary (DB, HTTP, queue, cache) to cover behaviour that could and should be an integration test — green, but it can't catch a parse error, a bad serialization, or a wrong round-trip | high — green but blind |
| **Untested new boundary** | the change *adds* a boundary (cache read/write + TTL, serialization round-trip, new query/client) with no integration test, even though the datasource it wraps is tested elsewhere | high |
| **Skipped integration** | the real-dependency test exists but is excluded/skipped in the run | high |
| **Zero-value test** | re-asserts a stub, a library feature, or a trivial invariant | noise — don't count it |
| **Weak assertion** | runs the real path but asserts too little to catch a regression | medium |
| **Missing error path** | success covered, error/edge/empty-input branch not | medium |

**Applying the hard gate.** For every changed behaviour that touches or orchestrates a boundary, the question is not "is there a test?" but "is there an *integration* test?" A green unit test built on mocks does **not** discharge the requirement — it is a *gate violation* (high), and the verdict is **Fail** until a real-dependency test exists. The fix is replace-then-remove: write the integration test to parity, then delete the mocked unit test (hand off to [backend-testing](../../backend-testing/SKILL.md)). Do not let the mock and the integration test coexist.

For a de-mocking / integration-migration change specifically, the headline question is: **did a
mock-based test get replaced by one that exercises the real dependency, or just deleted?** A dropped
behaviour with no integration replacement is an uncovered-behaviour gap, not a cleanup.

## Output of this step

A behaviour→test table and a gap list, feeding directly into [reporting.md](reporting.md). High-severity
gaps mean the QA verdict cannot be a clean pass regardless of the suite's exit code.
