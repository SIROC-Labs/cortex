---
name: backend-testing
version: 0.1.0
description: >
  Use when writing, reviewing, or improving tests in a backend / API / service project —
  triggers include "write tests", "add tests", "test this endpoint", "test this service",
  "improve test coverage", "/backend-testing", or any request to create or fix backend tests.
  Also triggered when TDD is active in a backend codebase to provide the testing context and
  patterns. Covers HTTP APIs, services, workers, and data layers across languages
  (Python, Node, JVM, Go, Ruby).
---

# Backend Testing

## Before writing any test

1. **Inspect the stack** — follow `references/stack-detection.md`. Read the dependency manifest, the test runner config, and an existing test file. Don't assume the language, runner, container library, or file conventions. If something looks inconsistent, stop and advise before writing.
2. **Match existing conventions** — file naming, location, import style, test structure. Don't introduce a second pattern.
3. **Pick the level deliberately** — apply the decision rule in `process.md`: touches I/O or a boundary → integration (real container); pure logic, no I/O → unit; external dependency → spec-driven fake. Integration is the default and the biggest slice.

## Reference files

- **`../generic-testing/process.md`** — universal fundamentals (determinism, AAA, behavior over implementation). Apply on every test.
- **`../generic-testing/references/infrastructure.md`** — CI, flake detection, benchmarks, reporting.
- **`process.md`** — backend patterns: integration-first with testcontainers, the test-level decision tree, DB isolation, test-data factories, async/messaging, auth in tests, the container decision tree, and the expected deliverable.
- **`references/stack-detection.md`** — how to inspect the project's language, runner, and container library.
- **`references/contract-testing.md`** — spec-driven fakes for external services and the drift guard.
- **`references/infrastructure.md`** — backend CI: the heavy-local / light-CI split, test tagging, and the PR evidence contract.
