# Mobile Stack Detection

Before writing any test, learn the project's testing setup by inspecting it directly. Do not assume.

This skill is scoped to **native iOS**, **native Android**, and **Kotlin Multiplatform** (shared logic + native UI). Cross-platform UI frameworks (React Native, Flutter, hybrid wrappers) are out of scope — if you find one, stop and surface that the chosen skill doesn't fit.

## What to read

1. **Build / package files** — `Package.swift`, `Podfile`, `*.xcodeproj` settings, `build.gradle(.kts)` (module + project level), `settings.gradle(.kts)`, `libs.versions.toml`. These tell you the runner, the dependencies, the source-set layout, and (on KMP) which targets are configured.
2. **An existing test file** — pick a representative one and read it. It shows the import style, helpers, file naming, and how dependencies are wired in tests. Match what's there.
3. **CI workflow files** — `.github/workflows/`, `bitrise.yml`, `fastlane/Fastfile`, `.gitlab-ci.yml`, etc. See what already runs on PRs (lint, unit, instrumentation, UI, coverage) so you know what's enforced and what's missing.

## What to derive (don't pre-list)

- **Platform** — native iOS / native Android / KMP, and on KMP which platform targets are configured (`androidMain`, `iosMain`, `iosX64`/`iosArm64`/`iosSimulatorArm64`).
- **Runner** — XCTest (with or without Quick/Nimble); JUnit 4 vs JUnit 5 on Android; `kotlin.test` on KMP common code.
- **DI framework** — manual constructor injection (the default in our apps) / Hilt / Koin / Dagger / Swinject / Resolver / Factory. The choice drives test setup — see `process.md` → "DI for testability".
- **Async style** — Kotlin Coroutines + Flow, RxJava, `async/await`, Combine, callbacks. Drives time-control choice in `process.md`.
- **Persistence layer** — Room / SQLDelight / Core Data / SwiftData / GRDB. In-memory variants and recipes live in `process.md` → "Mocking boundaries".
- **Coverage tool** — Kover (Kotlin: Android and KMP), Xcode built-in (iOS).
- **Test file naming and location** — JVM tests in `src/test/`, instrumentation in `src/androidTest/`, iOS in `<Module>Tests/`, KMP shared tests in `commonTest`. Match the project's existing layout.

## When to stop and advise

If any of the following is true, raise it with the user **before** writing tests:

- No test target / test source set exists yet — testing isn't set up; agree on the harness first.
- The test script or scheme is broken or fails on a clean checkout.
- Two conventions coexist in the codebase (e.g. some files in `src/test/`, some in `src/androidTest/` for what looks like JVM-only code; mixed `*Test.kt` / `*Tests.kt` naming). Ask which one to follow rather than picking arbitrarily.
- The test utilities look mismatched with the framework (e.g. Compose code with no `androidx.compose.ui:ui-test-junit4` and no JVM ViewModel tests either — a missing setup step).
- The codebase is React Native, Flutter, or a hybrid wrapper (Capacitor, Ionic, Tauri). This skill doesn't cover those — surface it.

Surfacing these is more useful than silently picking a default.

## Detection output

After inspection, write down (in your head, or in the PR description if scaffolding a new test setup):

```
Platform:           <native iOS / native Android / KMP — which targets>
Runner + version:   <XCTest / JUnit 4 / JUnit 5 / kotlin.test on KMP>
DI:                 <Hilt / Koin / Swinject / manual / ...>
Async style:        <coroutines / async-await / Combine / RxJava / callbacks>
Persistence:        <Room / SQLDelight / Core Data / SwiftData / GRDB — in-memory variant>
Network mocking:    <MockWebServer / WireMock / URLProtocol fake / ...>
Coverage tool:      <Kover / Xcode coverage>
Package tooling:    <SPM / CocoaPods / Gradle>
CI provider:        <GH Actions / Bitrise / GitLab / CircleCI / ...>
```

Every choice that follows in `process.md` is keyed off these values.
