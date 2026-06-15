# Testing Fundamentals

Universal testing principles for writing tests that prove code works. Platform and framework extensions provide the concrete tooling, configuration, and runner bindings.

## Core Belief

> "The more your tests resemble the way your software is used, the more confidence they can give you." — Kent C. Dodds

Tests exist to prove behavior, not to prove coverage. A test that doesn't resemble real usage is a test that lies about confidence.

## The Non-Negotiables

### 1. Determinism Is Law

A flaky test is worse than no test. It trains developers to ignore failures, erodes trust in the entire suite, and wastes everyone's time.

**A test that sometimes fails is a bug. Treat it as one.**

| Source of flakiness | Fix |
|---|---|
| Time/dates | Inject a clock. Never use `Date.now()` or system time directly. |
| Randomness | Seed the RNG or inject deterministic values. |
| Network calls | Stub at the boundary. No real HTTP in unit/integration tests. |
| Shared state | Isolate. Each test sets up and tears down its own world. |
| Execution order | Tests must pass in any order. If they don't, they share state. |
| Race conditions | Await properly. No arbitrary `sleep`/`setTimeout` in tests. |
| File system | Use temp directories or in-memory alternatives. Clean up after. |
| Environment variables | Set and restore per test. Never depend on the machine's env. |

**When a flaky test is found:**
1. **Quarantine immediately** — mark it, skip it, file a bug. Do not leave it in the suite failing intermittently.
2. **Fix within the sprint** — quarantined is not resolved. It's a debt with interest.
3. **Never "retry until green"** — that's hiding the bug, not fixing it.

### 2. Test Behavior, Not Implementation

Tests assert on **what the code does**, not **how it does it internally**.

A refactor that doesn't change behavior should break zero tests. If your tests break on a refactor, they're testing implementation details.

**Signals you're testing implementation:**
- Asserting on internal method calls
- Checking the order of operations that don't affect output
- Testing private methods directly
- Your test mirrors the production code's structure line by line

### 3. One Concept Per Test

A test proves one thing. Multiple `expect` lines are fine if they assert on one logical outcome. Multiple *behaviors* in one test means split it.

**The name test:** if you need "and" in the test name, it's two tests.

### 4. AAA Structure

Every test follows Arrange-Act-Assert. One act per test.

```
Arrange — set up the preconditions
Act     — execute the behavior under test
Assert  — verify the outcome
```

No assertions in Arrange. No side effects in Assert. One Act.

### 5. Real Code Over Test Doubles

Prefer real implementations. Only introduce doubles when real code is slow, non-deterministic, or has side effects you can't control.

**Confidence hierarchy (most to least):**

| Level | Use when |
|---|---|
| **Real code** | Always the default. No reason needed. |
| **Fake** | Real impl is slow or has side effects (e.g., in-memory DB instead of real DB). |
| **Stub** | You need to control what a dependency returns. |
| **Spy** | You need to verify a call happened (e.g., analytics event fired). |
| **Mock** | Last resort. You need to verify call arguments AND control returns. |

**If mock setup is longer than the test logic, you're over-mocking.** Consider an integration test with real dependencies instead.

### 6. Independence

No test depends on another test's state, output, or execution order.

- No shared mutable state between tests
- Each test creates what it needs and cleans up after itself
- Parallel execution must be safe
- `beforeEach` resets, not `beforeAll` accumulates

### 7. Test at the Right Level

Not everything needs a unit test. Not everything needs an E2E test.

| Level | Tests | Speed | Confidence | Use for |
|---|---|---|---|---|
| **Static analysis** | Types, lint rules | Instant | Low | Catching typos, type errors, style |
| **Unit** | Pure functions, utilities | Fast | Medium | Logic with no dependencies |
| **Integration** | Modules working together | Medium | High | Business logic, data flows, API handlers |
| **E2E** | Full user flows | Slow | Highest | Critical paths, smoke tests |

**Default to integration.** Unit test pure logic. E2E test critical paths. This is the testing trophy — integration is the biggest slice.

### 8. Edge Cases Are First-Class

Empty inputs, nulls, boundaries, error paths, and failure modes are not afterthoughts. They're where bugs live.

For every behavior, ask:
- What if the input is empty?
- What if it's null/undefined?
- What happens at the boundary? (0, -1, MAX_INT, empty string)
- What does the error path look like?
- What if the dependency fails?

### 9. Test Names Are Documentation

A reader should understand **what broke and why** from the test name alone, without reading the test body.

**Good:** `rejects expired tokens with a 401 and clear error message`
**Bad:** `test token validation`

**Good:** `returns empty array when user has no permissions`
**Bad:** `test getPermissions`

Convention: describe the **behavior** and the **condition**, not the method name.

### 10. Coverage Is Diagnostic, Not a Goal

Coverage tells you what code ran during tests. It does not tell you if the assertions were meaningful.

- 100% coverage with weak assertions is worse than 70% with strong ones
- 0% to 70% is transformative. 70% to 90% is incremental. 90% to 100% is often testing trivial code.
- Use coverage to **find gaps in critical paths**, not to chase a number

**What to cover first:** Business logic, error handling, data transformations, security boundaries.
**What to skip:** Boilerplate, generated code, simple pass-through wrappers, framework glue.

### 11. Every Test Must Be Able to Fail for a Real Reason

A test earns its place only if you can name **(a)** the specific behavior it pins and **(b)** a plausible code change it would catch *that no other test already catches*. If you can't name both, don't write it — and delete it if it exists. Tests are a liability as well as an asset: a zero-value test is permanent maintenance cost, noise when it breaks, and false confidence — with no upside. Adding a test "for coverage" is a reason to *not* add it.

**Never write or keep:**
- **Tautological** — asserts a stub/mock returns exactly what it was configured to return.
- **Framework re-tests** — re-asserts the language/library/framework's own behavior (that the ORM persists a field, that the validator validates, that an enum's `.value` is the literal you wrote, that the router routes).
- **Trivial invariants** — asserts a function with no meaningful return is `None`; exercises a no-logic constructor / getter / property.
- **Duplicates** — the same behavior+condition is already pinned by another test.
- **Coverage-only smoke** — calls the code and asserts nothing meaningful, or only that it "didn't raise" when not-raising isn't the contract.

**The carve-out:** a fail-open / fail-closed **spy** ("X was / wasn't called") is real when the call *is* the observable contract — a best-effort side-effect fired, or a non-essential one was suppressed on failure. That's behavior, not an implementation mirror.

**The cheap test:** before adding a test, write its one-line reason — "fails if `<specific change>`." If the test would still pass after you delete its assertions, or after you replace the implementation under test with `return <the stubbed value>`, it proves nothing. Delete it. This is the operational form of #10: a green line with a meaningless assertion is worse than an uncovered one, because it lies.

## Testing Infrastructure

Tests without infrastructure are unenforceable. The system must prove the tests are trustworthy, not just the developer.

### CI Pipeline

- Tests run on **every push**. No exceptions.
- No merge without green. The pipeline is the gatekeeper, not discipline.
- Test failures block the build. Not warnings — failures.
- CI should reproduce locally. If it passes locally and fails in CI (or vice versa), the environment is the bug.

### Coverage Reports

- Generated on every CI run
- Track **trends**, not absolutes — coverage going down on a PR is a signal worth investigating
- Visible to the team — not buried in logs
- Enforce **minimum thresholds on critical paths** (auth, payments, data integrity), not globally

### Flake Detection

- Track test pass rates over time
- Any test below 100% pass rate gets flagged
- Quarantine mechanism: flaky tests are skipped and tracked, not silently retried
- Flake budget: if quarantined tests exceed a threshold, the team stops feature work and fixes them

### Performance Benchmarks

- Benchmark critical operations and track regressions
- Performance tests run in CI on a consistent environment
- Regressions are caught before merge, not after deploy
- Historical data is kept — trends matter more than snapshots

### Test Reporting

- Clear, readable output: what passed, what failed, why
- Failure messages must be actionable — no "expected true to be false"
- Test duration tracked — slow tests are a smell
- Results visible in PR/CI, not just in logs

## Anti-Patterns

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| Testing mock behavior | You're proving the mock works, not the code | Test real components or don't assert on mocks |
| Shared mutable state | Tests pollute each other | Isolate per test |
| Testing private methods | Couples tests to implementation | Test through the public interface |
| Snapshot overuse | Brittle, no one reads the diff | Use targeted assertions on specific values |
| Multiple acts per test | Ambiguous failures | One act, one concept |
| Test-only code in production | Dangerous if called accidentally | Keep test utilities in test files |
| Retrying until green | Hides flakiness | Fix the flake or quarantine |
| Sleep-based synchronization | Non-deterministic, slow | Await events, use polling with timeout |
| Asserting on error messages | Breaks on copy changes | Assert on error types/codes |
| Zero-value / tautological test | Maintenance cost and false confidence, catches no real bug | Delete it; keep only tests that fail on a specific behavior change |

## Red Flags

You are off-track if:
- Test setup is longer than the test itself
- You can't explain what behavior a test proves
- A test would still pass if you deleted its assertions or replaced the code under test with `return <stubbed value>`
- You're adding a test "to bump coverage" rather than to pin a behavior
- A test name uses "and" or is a method name
- Tests break when you refactor without changing behavior
- You're adding `retry` or `flaky` annotations instead of fixing
- Coverage is going up but confidence isn't
- Tests pass locally but fail in CI (or vice versa)
- You're testing framework behavior, not your code
