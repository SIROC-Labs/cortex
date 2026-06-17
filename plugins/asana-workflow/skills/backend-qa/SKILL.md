---
name: backend-qa
version: 0.2.0
description: >
  Use when the operator wants to confirm a backend change is adequately tested before it ships —
  triggers include "QA this branch", "QA this PR", "is this tested enough", "do we have enough
  tests", "verify test coverage", "confirm the tests pass", "/backend-qa", or any request to
  audit/gate the unit + integration coverage of a backend change. Verifies an existing test
  suite; to author missing tests, use [backend-testing](../backend-testing/SKILL.md).
argument-hint: <branch | PR | module | what-to-verify>
---

# Backend QA

Confirm that a backend change — a branch, a PR, a module — carries **enough unit and integration
tests**, that those tests **pass**, and **report what is covered and why it matters**. This is a
verification gate, not an authoring task: backend-qa reads the change and its tests, runs them, and
produces a coverage verdict. It does not write code or drive a running service.

## The bar you verify against

"Enough" is not a coverage percentage. It is the testing standard defined in
[backend-testing/process.md](../backend-testing/process.md) and
[generic-testing/process.md](../generic-testing/process.md). Hold the suite to it:

- **Integration is a hard gate, not a preference.** If a changed behaviour *can* be proven with an
  integration test, it *must* be — datasources, queries, HTTP clients, caches, and queues are
  exercised against real dependencies in containers. A test that asserts on a generated SQL string,
  on the operator dict passed to a mocked DB, or on a mocked cache/boundary proves nothing — it
  cannot catch a query that fails to parse, a serialization that drops a field, a missing TTL, or a
  wrong miss→hit interaction. **A unit test that mocks a boundary to cover behaviour that belongs in
  an integration test is itself a high-severity gap — fail the QA even when it is green.**
- **A boundary the change *adds* needs its own integration test.** A new cache layer, serialization
  round-trip, or wrapper is untested even if the datasource it wraps is integration-tested elsewhere.
  "Covered downstream" never covers the new boundary's round-trip and wiring.
- **Unit tests only for isolated pure logic** (no I/O).
- **External third-party services** are faked with a spec-driven fake (e.g. WireMock) plus a
  schema-drift guard — not hand-mocked.
- **No zero-value tests.** A test that re-asserts a stub, a library feature, or a trivial invariant
  is not coverage. Don't count it; call it out.

## The flow

1. **Scope the change** — follow [references/coverage-audit.md](references/coverage-audit.md). Resolve
   exactly what is under QA (branch diff vs base, PR files, named module) and enumerate the
   behaviours that changed.
2. **Inventory the tests** — map each changed behaviour to the test(s) that exercise it. Classify
   each as unit / integration / contract, and judge whether it meets the bar above.
3. **Find the gaps** — behaviours with no test, behaviours covered only by a mock/string-assertion
   where an integration test is required, and any zero-value tests inflating the count.
4. **Run the suites** — follow [references/running-tests.md](references/running-tests.md). Run the
   fast suite **and** the heavy integration suite (real containers). Confirm green; investigate every
   failure or skip — a skipped integration test is not a pass.
5. **Report** — follow [references/reporting.md](references/reporting.md). Lead with the verdict,
   then per-area "what's tested / why it matters / gaps", then the run evidence.

## Rules

- **Read-only on code and deployment.** Backend-qa runs the test suite; it does not modify
  production code or tests, and it never drives or mutates a running service. If tests are missing,
  report the gap and hand off to [backend-testing](../backend-testing/SKILL.md) — do not write them here.
- **Green is necessary, not sufficient.** A passing suite that mocks the database, skips the
  integration tests, or pins library behaviour is a failing QA. Coverage adequacy and test honesty
  are part of the verdict, not just the exit code.
- **Run the integration tests for real.** They are often excluded from the default/CI run by design
  ([references/running-tests.md](references/running-tests.md)). If Docker is unavailable, that is a
  blocker to surface — not a reason to pass on the fast suite alone.
- **"Why it matters" is mandatory in the report.** For each covered area, state the failure it
  guards against. Coverage with no articulated risk is noise.

## Reference files

- [references/coverage-audit.md](references/coverage-audit.md) — scope the change, map behaviours to
  tests, the gap taxonomy.
- [references/running-tests.md](references/running-tests.md) — discover and run the unit vs
  integration suites, interpret pass/fail/skip, handle flakes.
- [references/reporting.md](references/reporting.md) — the QA report contract.
- [backend-testing/SKILL.md](../backend-testing/SKILL.md) — the authoring skill; the standard
  backend-qa verifies against, and where gaps are remediated.
- [generic-testing/process.md](../generic-testing/process.md) — universal testing fundamentals.
