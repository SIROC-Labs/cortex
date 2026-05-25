# Mobile Testing Infrastructure

Mobile-specific additions on top of `../../generic-testing/references/infrastructure.md`. Read that first — coverage principles, PR gates, flake protocol, and reporting live there. This doc only covers what's different about a mobile codebase. Scoped to **unit + integration** on native iOS, native Android, and KMP.

Before applying any snippet below, read the project's existing build files and CI workflows. Adapt — don't paste.

## Coverage

### Android / KMP (Kover)

`org.jetbrains.kotlinx:kover` is the default coverage tool for Kotlin code — JetBrains-maintained, KMP-aware, and natively understands Kotlin bytecode (inline functions, Compose compiler output, suspending lambdas, when-on-nullable-enum, JvmOverloads). No Kotlin-specific exclude rules needed.

```kotlin
plugins { id("org.jetbrains.kotlinx.kover") version "<latest>" }

kover {
    reports {
        total {
            xml { xmlFile = layout.buildDirectory.file("reports/kover/report.xml") }
            html { htmlDir = layout.buildDirectory.dir("reports/kover/html") }
        }
    }
}
```

In a multi-module build, apply Kover to the root project and to each module that should contribute to coverage; reports aggregate via the root `koverXmlReport` / `koverHtmlReport` tasks.

### iOS (Xcode)

Code coverage is built into Xcode — enable in scheme settings (`Edit Scheme → Test → Options → Code Coverage: Gather coverage for [target]`). Generate reports via `xcodebuild`:

```bash
xcodebuild test \
  -scheme MyApp \
  -destination 'platform=iOS Simulator,name=<iPhone model>' \
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

Job layout depends on the platform. The platform also dictates runner cost — macOS runners are ~10× Linux runners on GitHub-hosted, and only iOS *needs* macOS. Split jobs accordingly; don't pay macOS for Android or `commonTest` work.

**Pure Android** — one job on Linux: JDK → Gradle cache → lint (ktlint / detekt) → unit + integration tests with coverage → upload report.

**Pure iOS** — one job on macOS: Xcode (pinned) → SPM / CocoaPods cache → lint (SwiftLint) → unit + integration tests with coverage → upload report.

**KMP — split, do not unify:**

```
job: jvm-tests (linux)                  job: ios-tests (macos)
  - Set up JDK                            - Set up JDK (aarch64 on Apple Silicon)
  - Restore Gradle cache                  - Set up Xcode (pinned)
  - Lint (ktlint / detekt)                - Restore Gradle + ~/.konan cache
  - commonTest + androidUnitTest          - iosSimulatorArm64Test
  - Upload coverage report                - Upload coverage report
```

Running `commonTest` and `androidUnitTest` on macOS is a common, expensive mistake — they're JVM workloads that run anywhere. Reserve the macOS job for what genuinely needs it (`iosSimulatorArm64Test`, building the iOS framework, anything touching `xcodebuild`).

On Apple Silicon CI runners (`macos-latest`), run **only** the simulator-arm64 test target — `iosSimulatorArm64Test`. Running `iosX64Test` as well wastes compute; that target is for x86_64 hosts.

Two further wins specific to KMP CI:

- **Path-based job skipping.** Most PRs only touch one side. Use a path-based change-detection step to gate the iOS job on `shared/**` or `iosApp/**` changes, and the JVM job on `shared/**` or `androidApp/**`. Cuts CI minutes in half on typical PRs.
- **Concurrency cancellation.** `concurrency: { group: ${{ github.head_ref || github.ref_name }}, cancel-in-progress: true }` cancels older runs on the same branch when a new push lands — stops compute stacking up on rapid pushes.

Fail on any step. Block merge on lint, unit + integration, build.

## Parallelism

### Android (JVM unit tests)

- Gradle parallel execution: `--parallel` and `org.gradle.workers.max` in `gradle.properties`.
- Configure forked test JVMs (`tasks.withType<Test> { maxParallelForks = ... }`) for CPU-bound suites — usually CPU count − 1 on a CI runner.

### iOS (XCTest unit tests)

- `xcodebuild test -parallel-testing-enabled YES -parallel-testing-worker-count N` — parallel simulators per runner. Useful even at the unit-test scale because XCTest is slow to spin up.
- Boot simulators ahead of time (`xcrun simctl bootstatus`) and **keep them warm across tests in the same job** — do not boot a fresh one per test class. After the platform-split decision in CI pipeline, this is the biggest single lever on macOS cost.

### KMP

- `commonTest` runs on the JVM and parallelizes like any JVM test suite.
- Platform-specific test source sets (`androidUnitTest`, `iosSimulatorArm64Test`) parallelize per the platform rules above.

## Toolchain caching

Toolchain setup dominates wall-clock; cache aggressively, keyed by lockfile hash.

- **Android** — `~/.gradle/caches`, `~/.gradle/wrapper`, Gradle build cache.
- **KMP (iOS side)** — `~/.konan` (Kotlin/Native compiler + downloaded toolchains). Without it, cold KMP iOS builds take multiple extra minutes.
- **iOS** — `~/Library/Caches/CocoaPods`, `~/Library/Developer/Xcode/DerivedData/ModuleCache.noindex`, SPM checkouts. Pre-built simulator runtimes baked into the CI image also save ~1–3 min/job.

Key by `Podfile.lock`, `Package.resolved` (SPM), `gradle/wrapper/gradle-wrapper.properties`, `gradle.lockfile`, `libs.versions.toml`, or whatever the project uses for dependency pinning. For `~/.konan`, key by `*.gradle.kts` files plus `libs.versions.toml` — Kotlin/Native version is pinned there.

## iOS simulator pinning

iOS unit tests run on the simulator — pin the Xcode version and destination for reproducibility.

- Pin Xcode version (drives default simulator runtime).
- Pin destination with explicit model + OS — e.g. `'platform=iOS Simulator,name=<model>,OS=<runtime>'` — matching the Xcode runtime you've pinned. Don't leave it on a default that drifts when CI images update.
- Bump intentionally — when bumping target/Xcode versions, do it in a dedicated PR with a clear commit message; do not let CI silently drift.

Android JVM unit tests don't need an emulator — no pinning needed there until instrumentation tests come back in scope.

## Reporting (mobile-specific)

For trend tracking, PR-comment format, and flake telemetry, see generic-testing. The mobile delta:

- **Test report format** — JUnit XML is universal. Gradle reports XML by default. For Xcode use the current `xcrun xcresulttool get test-results …` subcommands (Xcode 16+); the older `xcresulttool get/export/graph` commands are deprecated and now require `--legacy`. Third-party converters (`trainer`, `xcparse`) still work and produce JUnit XML directly if your CI expects that.
- **Failure logs** — Xcode test failures sit in the `.xcresult` bundle; surface them in CI so debugging doesn't require pulling the artifact down locally.

