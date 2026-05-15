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
- **DI framework** — Hilt / Koin / Dagger / Swinject / Resolver / Factory / manual constructor injection. The choice drives test setup (see "Implications" below).
- **Async style** — Kotlin Coroutines + Flow, RxJava, `async/await`, Combine, callbacks. Drives time-control choice in `process.md`.
- **Persistence layer** — Room / SQLDelight / Core Data / SwiftData / GRDB, and its in-memory variant (see "Implications").
- **Coverage tool** — JaCoCo (Android), Xcode built-in (iOS), Kover (KMP / Kotlin-first multi-target).
- **Test file naming and location** — JVM tests in `src/test/`, instrumentation in `src/androidTest/`, iOS in `<Module>Tests/`, KMP shared tests in `commonTest`. Match the project's existing layout.

## When to stop and advise

If any of the following is true, raise it with the user **before** writing tests:

- No test target / test source set exists yet — testing isn't set up; agree on the harness first.
- The test script or scheme is broken or fails on a clean checkout.
- Two conventions coexist in the codebase (e.g. some files in `src/test/`, some in `src/androidTest/` for what looks like JVM-only code; mixed `*Test.kt` / `*Tests.kt` naming). Ask which one to follow rather than picking arbitrarily.
- The test utilities look mismatched with the framework (e.g. Compose code with no `androidx.compose.ui:ui-test-junit4` and no JVM ViewModel tests either — a missing setup step).
- The codebase is React Native, Flutter, or a hybrid wrapper (Capacitor, Ionic, Tauri). This skill doesn't cover those — surface it.

Surfacing these is more useful than silently picking a default.

## Implications worth knowing

The points below are platform-specific gotchas worth applying once you know the stack. They are principles, not a lookup table — they exist because the obvious default is wrong.

### KMP

- Tests for shared code live in **`commonTest`** (the test counterpart to `commonMain`), not in `commonMain`. They run on the JVM by default and can use `kotlin.test` for assertions, with `kotlinx-coroutines-test` for `runTest { }`.
- Platform-specific tests go in `androidUnitTest` / `androidInstrumentedTest` / `iosTest` (or `iosX64Test`, etc.) depending on what the target needs.
- Treat the platform-specific source sets the same as their native counterparts for testing purposes.

### Android DI

- **Hilt** — plan for `@TestInstallIn(replaces = ProductionModule::class)` modules and `HiltAndroidRule` in instrumentation. JVM tests usually do not need Hilt — inject fakes directly.
- **Koin** — `loadKoinModules(testModule)` in test setup; stop the container in `@After`.
- **Manual constructor injection** — simplest path; pass fakes directly to the type under test. Prefer this everywhere it's viable.

### iOS DI

- Most modern Swift codebases use manual constructor injection or property-based injection — pass fakes in directly. If the project uses Swinject / Resolver / Factory, follow the framework's per-test container or property-based approach.
- If a type cannot be constructed in a test without booting the full DI graph, it has too many dependencies — refactor toward constructor injection.

### Persistence — in-memory variants

- **Room** — `Room.inMemoryDatabaseBuilder(...)`.
- **SQLDelight** — `:memory:` driver (`JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY)` on JVM).
- **Core Data** — `NSInMemoryStoreType` is the canonical in-memory variant. `description.url = URL(fileURLWithPath: "/dev/null")` on a SQLite store is a different technique used when SQLite parser semantics are needed; don't conflate them.
- **SwiftData** — `ModelConfiguration(isStoredInMemoryOnly: true)`.
- **GRDB** — `DatabaseQueue()` with no path is in-memory by default.

### Async / time control

- **Kotlin Coroutines** — `runTest { }` skips `delay(...)` calls automatically via virtual time. A `delay(1.minutes)` returns immediately. Only call `advanceTimeBy(...)` when asserting on intermediate state between dispatches.
- **Swift `async/await`** — iOS 16+: inject a Swift `Clock` (`ContinuousClock`, custom test clock) for time control. iOS 15 and earlier: wrap `Date()` / sleep calls in a `TimeProvider` protocol and inject a fake.
- **Legacy Combine / callbacks** — use `XCTestExpectation` only when the code under test is genuinely callback-based; prefer migrating to `async/await` for new tests.

### Coverage classpaths (Android / JaCoCo)

- Cover both `tmp/kotlin-classes/<variant>` **and** `intermediates/javac/<variant>/classes` — Kotlin and Java live in different trees. Missing one silently underreports.
- Use `layout.buildDirectory` rather than the deprecated `buildDir` property — `buildDir` lint-warns on Gradle 8.x.

## Detection output

After inspection, write down (in your head, or in the PR description if scaffolding a new test setup):

```
Platform:           <native iOS / native Android / KMP — which targets>
Runner + version:   <XCTest / JUnit 4 / JUnit 5 / kotlin.test on KMP>
DI:                 <Hilt / Koin / Swinject / manual / ...>
Async style:        <coroutines / async-await / Combine / RxJava / callbacks>
Persistence:        <Room / SQLDelight / Core Data / SwiftData / GRDB — in-memory variant>
Network mocking:    <MockWebServer / WireMock / URLProtocol fake / ...>
Coverage tool:      <JaCoCo / Xcode coverage / Kover>
Package tooling:    <SPM / CocoaPods / Gradle>
CI provider:        <GH Actions / Bitrise / GitLab / CircleCI / ...>
```

Every choice that follows in `process.md` is keyed off these values.
