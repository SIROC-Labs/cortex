# Mobile Testing Infrastructure

Mobile-specific additions on top of `../../generic-testing/references/infrastructure.md`. Read that first — coverage principles, PR gates, flake protocol, and reporting live there. This doc only covers what's different about a mobile codebase. Scoped to **unit + integration** on native iOS, native Android, and KMP.

UI / E2E, snapshot, performance, persistence-migration, and device-farm infrastructure are deferred — see the scope callout in `SKILL.md`.

Before applying any snippet below, read the project's existing build files and CI workflows. Adapt — don't paste.

## Coverage

### Android (JaCoCo)

JaCoCo is the standard for Kotlin/Java coverage on JVM unit tests. Wire it from the module's `build.gradle.kts`:

```kotlin
plugins {
    jacoco
}

jacoco {
    toolVersion = "0.8.11"
}

tasks.register<JacocoReport>("jacocoTestReport") {
    dependsOn("testDebugUnitTest")
    reports {
        xml.required = true
        html.required = true
    }
    val excludes = listOf(
        "**/R.class", "**/R\$*.class",
        "**/BuildConfig.*",
        "**/Manifest*.*",
        "**/*_Hilt*.*", "**/Hilt_*.*",
        "**/*_Factory.*", "**/*_MembersInjector.*",
        "**/databinding/**", "**/generated/**",
    )
    val kotlinTree = fileTree(layout.buildDirectory.dir("tmp/kotlin-classes/debug")) { exclude(excludes) }
    val javaTree   = fileTree(layout.buildDirectory.dir("intermediates/javac/debug/classes")) { exclude(excludes) }
    classDirectories.setFrom(kotlinTree, javaTree)
    sourceDirectories.setFrom(files("src/main/kotlin", "src/main/java"))
    executionData.setFrom(fileTree(layout.buildDirectory).include("/jacoco/*.exec"))
}
```

Two non-obvious points:

- Cover both `tmp/kotlin-classes/<variant>` **and** `intermediates/javac/<variant>/classes` — Kotlin and Java live in separate trees. Missing one silently underreports.
- Use `layout.buildDirectory` rather than the deprecated `buildDir` property — `buildDir` lint-warns on Gradle 8.x.

For KMP modules, **Kover** (Kotlin coverage tool) handles multi-target reporting better than JaCoCo's Android-centric setup — use it if the module is Kotlin-first with multiple targets.

### iOS (Xcode)

Code coverage is built into Xcode — enable in scheme settings (`Edit Scheme → Test → Options → Code Coverage: Gather coverage for [target]`). Generate reports via `xcodebuild`:

```bash
xcodebuild test \
  -scheme MyApp \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  -derivedDataPath build/ \
  -enableCodeCoverage YES

xcrun xccov view --report --json build/Logs/Test/*.xcresult > coverage.json
```

For threshold gating, use `xcov` or process the JSON in CI.

### What to exclude

- **Generated code** — DI graphs (Hilt, Dagger), Room generated classes, KSP/KAPT output. Including them inflates coverage without adding signal.
- **UI-only code from unit-coverage targets** — Composables and SwiftUI views are not unit-tested by design; including them depresses the metric.

(See generic-testing for thresholds and ratchet strategy — don't restate them here.)

## CI pipeline

A single test job is enough while scope is unit + integration:

```
job: lint-and-test
  - Set up JDK / Xcode (cached by toolchain version)
  - Restore dependency cache (Gradle / SPM / CocoaPods)
  - Lint (ktlint / detekt / SwiftLint)
  - Unit + integration tests with coverage
  - Upload coverage report
```

Fail on any step. Block merge on lint, unit + integration, build.

## Parallelism

### Android (JVM unit tests)

- Gradle parallel execution: `--parallel` and `org.gradle.workers.max` in `gradle.properties`.
- Configure forked test JVMs (`tasks.withType<Test> { maxParallelForks = ... }`) for CPU-bound suites — usually CPU count − 1 on a CI runner.

### iOS (XCTest unit tests)

- `xcodebuild test -parallel-testing-enabled YES -parallel-testing-worker-count N` — parallel simulators per runner. Useful even at the unit-test scale because XCTest is slow to spin up.
- Boot simulators ahead of time (`xcrun simctl bootstatus`) — saves ~30s per test run.

### KMP

- `commonTest` runs on the JVM and parallelizes like any JVM test suite.
- Platform-specific test source sets (`androidUnitTest`, `iosTest`) parallelize per the platform rules above.

## Toolchain caching

Mobile CI is dominated by toolchain setup, not by tests. Cache aggressively, keyed by lockfile hash.

| Cache target | Hit rate impact |
|---|---|
| **Android** — `~/.gradle/caches`, `~/.gradle/wrapper`, build cache | 5–15× speedup |
| **iOS** — `~/Library/Caches/CocoaPods`, `~/Library/Developer/Xcode/DerivedData/ModuleCache.noindex`, SPM checkouts | 3–10× speedup |
| **iOS** — pre-built simulator runtime in CI image | Saves 1–3 min/job |

Key by `Podfile.lock`, `gradle/wrapper/gradle-wrapper.properties`, `gradle.lockfile`, `libs.versions.toml`, or whatever the project uses for dependency pinning.

## iOS simulator pinning

iOS unit tests run on the simulator — pin the Xcode version and destination for reproducibility.

- Pin Xcode version (drives default simulator runtime).
- Pin destination: `'platform=iOS Simulator,name=iPhone 15,OS=17.4'`.
- Bump intentionally — when bumping target/Xcode versions, do it in a dedicated PR with a clear commit message; do not let CI silently drift.

Android JVM unit tests don't need an emulator — no pinning needed there until instrumentation tests come back in scope.

## Reporting (mobile-specific)

For trend tracking, PR-comment format, and flake telemetry, see generic-testing. The mobile delta:

- **Test report format** — JUnit XML is universal. Gradle reports XML by default; for Xcode, extract via `xcresulttool` (or `trainer` / `xcparse`).
- **Failure logs** — Xcode test failures sit in the `.xcresult` bundle; surface them in CI so debugging doesn't require pulling the artifact down locally.

## Cost awareness

Mobile CI is expensive on macOS. Two levers move the bill the most:

1. **CI runner type** — macOS runners cost ~10× Linux runners (GitHub-hosted) and are required for iOS. Don't run Android-only or KMP-`commonTest`-only jobs on macOS by accident.
2. **Simulator boot time** — keep simulators warm across tests in the same iOS job; do not boot a fresh one per test.

For KMP repos, run the `commonTest` job and the Android job on Linux (cheap) and the iOS job on macOS (expensive). Don't unify everything on macOS just for convenience.
