---
name: mobile-testing
version: 0.1.0
description: >
  Use when writing, reviewing, or improving tests in a mobile project — triggers include "write tests",
  "add tests", "test this ViewModel", "test this Presenter", "test this use case", "/mobile-testing",
  or any request to create or fix mobile tests. Also triggered when TDD is active in a mobile codebase
  to provide the testing context and patterns. Scoped to native iOS, native Android, and Kotlin
  Multiplatform. Currently covers unit + integration only.
---

# Mobile Testing

Scoped to **native iOS**, **native Android**, and **Kotlin Multiplatform** (shared logic + native UI). Cross-platform UI frameworks (React Native, Flutter, hybrid wrappers) are out of scope — if you find one, stop and surface that this skill doesn't fit.

## Before writing any test

1. **Inspect the project.** Read the build files (`build.gradle(.kts)`, `settings.gradle(.kts)`, `libs.versions.toml`, `Package.swift`, `Podfile`, `*.xcodeproj` settings), one representative existing test file, and the CI workflow. These tell you the runner, the DI approach, the async style, and the conventions to match. Don't assume.

2. **Handle ambiguous or unsupported situations.** Never block — take the default action below and include the surfaced message in the output. The operator (or the calling skill) can read it and redirect if the default is wrong.

   - **No test target / source set exists** → skip writing tests. Do not auto-scaffold project structure. Surface: *"No test infrastructure found. No tests were added. Set up the test harness before invoking this skill again."*
   - **Test runner or scheme broken on clean checkout** → skip writing tests. Don't pile new tests onto a broken runner. Surface: *"Test runner failed on clean checkout: \<error\>. No tests were added until the harness is fixed."*
   - **Mixed conventions in the codebase** (test location, file naming, etc.) → use the majority convention in the closest sibling directory. Surface: *"Found mixed conventions (\<X\> used N times, \<Y\> used M times). Chose \<X\>. Regenerate with the alternative if this is wrong."*
   - **Test utilities missing for one layer** (e.g. Compose UI Test not configured for Composable code) → write tests for the layers that have utilities, skip the rest. Surface: *"Wrote tests for \<X\>. Skipped \<Y\> tests because \<utility\> is not configured."*
   - **Project is React Native, Flutter, or hybrid wrapper** → do not write tests. Hard scope mismatch. Surface: *"Project uses \<framework\>. This skill doesn't cover \<framework\>. Consider an alternative."*

   When invoked by another skill, propagate the surfaced text so the caller has the record.

3. **Match what's there.** File naming, mocking style, test structure, where tests live. Don't introduce a second pattern.

## Reference files

- **`../generic-testing/process.md`** — universal fundamentals (determinism, AAA, behavior over implementation). Apply on every test.
- **`../generic-testing/references/infrastructure.md`** — CI, flake detection, benchmarks, reporting.
- **`process.md`** — unit + integration patterns (ViewModels, repositories, async/time, mocking, DI).
- **`references/infrastructure.md`** — mobile-specific CI, coverage, caching, and simulator pinning. Consult only when configuring CI or coverage; not needed for routine test-writing invocations.
