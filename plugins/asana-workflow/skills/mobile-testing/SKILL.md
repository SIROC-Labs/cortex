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

## Before writing any test

1. **Inspect the stack** — follow `references/stack-detection.md`. Read the build files, an existing test file, and CI. Don't assume the runner, DI framework, async style, or file conventions. If something looks weird or inconsistent, stop and advise before writing.
2. **Match existing conventions** — file naming, mocking style, test structure. Don't introduce a second pattern.

## Reference files

- **`../generic-testing/process.md`** — universal fundamentals (determinism, AAA, behavior over implementation). Apply on every test.
- **`../generic-testing/references/infrastructure.md`** — CI, flake detection, benchmarks, reporting.
- **`process.md`** — unit + integration patterns (ViewModels, repositories, async/time, mocking, DI).
- **`references/stack-detection.md`** — how to inspect the project's testing setup.
- **`references/infrastructure.md`** — mobile-specific additions on top of the generic infrastructure doc.
