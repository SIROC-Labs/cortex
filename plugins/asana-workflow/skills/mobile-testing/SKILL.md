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

2. **Stop and advise if any of these hold:**
   - No test target / test source set exists yet — testing isn't set up; agree on the harness first.
   - The test script or scheme is broken or fails on a clean checkout.
   - Two conventions coexist in the codebase (some files in `src/test/`, some in `src/androidTest/` for JVM-only code; mixed `*Test.kt` / `*Tests.kt` naming). Ask which one to follow rather than picking arbitrarily.
   - The test utilities look mismatched with the framework (e.g. Compose code with no `androidx.compose.ui:ui-test-junit4` and no JVM ViewModel tests either — a missing setup step).
   - The codebase is React Native, Flutter, or a hybrid wrapper (Capacitor, Ionic, Tauri). This skill doesn't cover those — surface it.

3. **Match what's there.** File naming, mocking style, test structure, where tests live. Don't introduce a second pattern.

## Reference files

- **`../generic-testing/process.md`** — universal fundamentals (determinism, AAA, behavior over implementation). Apply on every test.
- **`../generic-testing/references/infrastructure.md`** — CI, flake detection, benchmarks, reporting.
- **`process.md`** — unit + integration patterns (ViewModels, repositories, async/time, mocking, DI).
- **`references/infrastructure.md`** — mobile-specific CI, coverage, caching, and simulator pinning. Consult only when configuring CI or coverage; not needed for routine test-writing invocations.
