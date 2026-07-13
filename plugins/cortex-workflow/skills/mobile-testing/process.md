# Mobile Testing

Mobile bindings for `../generic-testing/process.md` (non-negotiables apply here too). Scoped to native iOS, native Android, and KMP.

## The golden rule

> Test the layer below the view, not the view.

ViewModels, Presenters, Stores, use cases, repositories, mappers, and pure functions are the right unit-test targets. Do not unit-test that a SwiftUI / Compose view renders pixels — that is UI-test territory, and most of it is testing the framework (Apple and Google have already tested it for you).

## What to test at the unit level

Order roughly by priority — most coverage value, lowest cost.

### 1. ViewModels / Presenters / Stores

The single highest-value target on mobile. State machines that map input + state → new state + side effects.

```
Arrange — construct the ViewModel with fake/stub dependencies and known initial state
Act     — invoke a single method or emit a single event
Assert  — verify the resulting state and any side effects (navigation events, analytics calls)
```

**Test state transitions, not internal field assignments.** If the ViewModel exposes `state: LoginState`, assert on `state == LoginState.Loading` after submit, not on a private `isLoading` boolean.

Stack bindings:

- **Android / KMP (Kotlin)** — `runTest { ... }` with an injected `TestDispatcher`. Collect `StateFlow` / `SharedFlow` using the project's flow-assertion helper, or `flow.toList()` in a `runTest` block for one-shot terminating flows. Never use `runBlocking` in tests.
- **iOS (Swift)** — `async/await` test methods (XCTest and Swift Testing both support them natively). For time control, inject a Swift `Clock`. Use callback-based expectation APIs (`XCTestExpectation` in XCTest, `confirmation` in Swift Testing) only for genuinely callback-based legacy code.

### 2. Use cases / interactors / domain services

Pure orchestration logic between repositories. High coverage value because they encode business rules. Same AAA shape as ViewModels — construct with fake repositories returning known data, call the use case, assert on the returned domain result and any cross-repository coordination.

On KMP, use cases typically live in `commonMain` and are tested from `commonTest` — runs on the JVM, fastest tests in the build.

### 3. Repositories

The boundary between domain code and platform APIs. Test the *coordination* — what happens on success, error, empty, partial — using a fake network layer (success / 4xx / 5xx / timeout) and an in-memory database. Assert on return value, cache writes, and error mapping.

### 4. Pure functions — mappers, validators, formatters

DTO ↔ domain mappers, form validators, currency / date formatters, parsers. The cheapest tests in the codebase, and the easiest to write last (or skip). Include them — pure functions accumulate edge-case bugs (locale, null, empty, boundary).

## Async and time control

The single largest source of flake on mobile. Treat the rules below as non-negotiable.

| Stack | Time control | Async control |
|---|---|---|
| **Kotlin (Android / KMP)** | `TestDispatcher` — default to `StandardTestDispatcher` (queues continuations); switch to `UnconfinedTestDispatcher` only when you need eager dispatch (e.g. some `flatMapLatest` synchronization). `advanceTimeBy(...)` for explicit virtual-time control. | `runTest { }`, flow-assertion helper for `StateFlow` / `SharedFlow` |
| **Swift (iOS)** | inject a Swift `Clock` | native `async/await` test methods |

**Forbidden:**

- `Thread.sleep`, `usleep`, `await Task.sleep(seconds:)` with real time
- `Date()` / `Date.now` / `System.currentTimeMillis()` / `Clock.System.now()` directly in production code paths under test — inject a clock instead
- "Retry until green" — fix the determinism root cause

## Mocking boundaries

**Prefer hand-rolled fakes over a mocking library** for the dependencies you own. A `FakeUserRepository` that implements the production interface is plain code — zero supply-chain risk, reads like the real thing, reusable across tests. Reach for a mocking library only when verification, exception-path scripting, or argument capture would be visibly clunky as a fake — and even then, only if a library is already in the project.

Mock at the platform / network boundary. Do not mock your own value types or pure functions.

| Layer | Mock? | Why |
|---|---|---|
| **HTTP / GraphQL** | Yes — fake server preferred | Honest integration shape; status codes, headers, retries all real |
| **Platform APIs** (location, camera, biometrics, push, keychain/keystore, permissions) | Yes — protocol/interface + fake | Not available reliably in unit-test environment |
| **Persistent storage** | Prefer in-memory variant over mocks | Recipes below |
| **Analytics / crash reporting SDKs** | Yes — stub or no-op | Avoid side effects; sometimes assert events fired |
| **Date / random** | Inject — never mock the system clock or `Math.random()` | Determinism is law (see generic-testing) |
| **Value types** (data classes, structs, enums) | No | They have no behavior to mock |
| **Pure functions** | No | Call them directly |
| **Your own ViewModels / use cases under test** | No | That's the thing you're testing |

### Network — fake at the wire, not the call site

Prefer a fake server over response mocks. A fake server forces your code through real serialization, headers, and error paths — the places where bugs actually live. Response-mocking libraries that bypass the network layer hide real failures.

- **Android / KMP** — match whatever the project already uses (an HTTP-client interceptor, an HTTP engine swap, or a JVM fake server). Only introduce something new if there's nothing.
- **iOS** — a `URLProtocol` subclass intercepting at the `URLSession` layer. Native to Foundation; no third-party dependency required.

**iOS `URLProtocol` gotcha:** the protocol class must be registered before the `URLSession` is created. Either build a custom session (`URLSessionConfiguration.ephemeral` with `protocolClasses = [MockURLProtocol.self]`) and inject it, or call `URLProtocol.registerClass(MockURLProtocol.self)` in test setup before any code touches `URLSession.shared`. Without this, requests fall through to the real network silently.

### Persistence — in-memory variants

Prefer the real persistence layer in an in-memory configuration over mocks. You get real schema validation, real query behavior, and real serialization — without disk I/O.

- **Room** — `Room.inMemoryDatabaseBuilder(...)`.
- **SQLDelight** — `:memory:` driver (`JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY)` on JVM).
- **Core Data** — `NSInMemoryStoreType` is the canonical in-memory variant. `description.url = URL(fileURLWithPath: "/dev/null")` on a SQLite store is a different technique used when SQLite parser semantics are needed; don't conflate them.
- **SwiftData** — `ModelConfiguration(isStoredInMemoryOnly: true)`.
- **GRDB** — `DatabaseQueue()` with no path is in-memory by default.

## DI for testability

**Default: manual constructor injection.** Pass fakes directly to the type under test. No framework, no container, no test-runtime wiring. This is what our apps use; prefer it everywhere it's viable.

**Rule of thumb:** if a class cannot be constructed in a test without booting an entire DI graph, the class has too many dependencies. Refactor toward constructor injection rather than introducing a test container.

If you encounter an existing DI framework in the codebase, follow its test conventions rather than fighting them — but the bar for *introducing* a framework should be high:

| Stack you find | Test override |
|---|---|
| **Hilt (Android)** | `@TestInstallIn(replaces = ProductionModule::class)`; `HiltAndroidRule` in instrumentation tests |
| **Koin (Android / KMP)** | `loadKoinModules(testModule)` in test setup; stop the container in `@After` |
| **Dagger (Android)** | swap `@Component` builders or `@BindsInstance` for fakes |
| **Swinject / Resolver / Factory (iOS)** | per-test container or property-based injection |

## Integration tests (middle tier)

Integration tests exercise multiple real layers without the UI. They are the highest-confidence-per-second tests on mobile and are routinely undervalued.

**When to write one:**

- ViewModel + Repository + in-memory database — verifies the DI graph and data flow end-to-end below the view.
- Use case + fake-server network + in-memory cache — verifies error mapping, retry, offline fallback.
- Navigation graph wiring — verifies that triggering a navigation event leads to the expected destination key (without rendering).

**What to use:** real `ViewModel`, real `Repository`, in-memory persistence, fake network. On Android this stays on the JVM unit-test runner (milliseconds). On iOS, an iOS test target (Swift Testing or XCTest) with in-memory Core Data / SwiftData / GRDB and the `URLProtocol` fake. On KMP, shared-code integration goes in `commonTest`; platform-specific integration (anything touching `androidMain` or `iosMain`) goes in the matching platform test source set.

**Never:** real network, real device sensors, real push delivery, real biometric prompts, real backend (even staging). Those belong in UI tests at most.

## What NOT to unit-test

- Framework-provided behavior — that `@Observable` publishes, that `StateFlow` emits, that `@Published` triggers re-render. Apple and JetBrains tested it.
- Trivial getters / setters with no logic.
- Layout, colors, fonts — visual concerns belong to snapshot tests (out of scope for this skill).
- The contents of an SDK you depend on. Test how *your* code reacts to its outputs.

## Conventions

### Naming

Each test name describes one behavior, in domain language.

```
test_loginSucceeds_whenCredentialsAreValid()
test_loginShowsError_whenServerReturns401()
test_repositoryFallsBackToCache_whenNetworkUnavailable()
```

Avoid `testLoginViewModel_1()`, `test_handleSubmit_works()`, or names that mirror the production method name. Names should read as a specification.

### File layout

Match the existing project. If none exists, default to:

- **Android (Gradle)** — `src/test/kotlin/<package>/<TypeName>Test.kt` for JVM tests; `src/androidTest/kotlin/...` reserved for instrumentation only.
- **iOS (Xcode)** — `<Module>Tests/<TypeName>Tests.swift` in a dedicated unit-test target.
- **KMP** — shared tests in `commonTest/kotlin/<package>/<TypeName>Test.kt`; platform-specific tests in `androidUnitTest/` (JVM), `androidInstrumentedTest/` (device/emulator), and `iosTest/` (iOS).

**KMP iOS folders, in one breath:** you have *one* `iosTest/` folder. Names like `iosX64Test` / `iosArm64Test` / `iosSimulatorArm64Test` are Gradle *task names*, not folders — Kotlin's hierarchical structure compiles `iosTest/` against each declared iOS target and exposes a test task per target. Per-target source-set leaves stay empty in practice. CI runs the task that matches the runner architecture (`iosSimulatorArm64Test` on Apple Silicon).
