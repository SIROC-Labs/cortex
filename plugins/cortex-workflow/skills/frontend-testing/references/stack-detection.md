# Frontend Stack Detection

Before writing any test, learn the project's testing setup by inspecting it directly. Do not assume.

## What to read

1. **`package.json`** — `dependencies` and `devDependencies` tell you the framework, the runner, and the testing utilities. `scripts.test` (and any sibling scripts like `test:unit`, `test:e2e`, `test:watch`) tell you the exact command to run.
2. **Runner config in the project root** — `vitest.config.*`, `vite.config.*`, `jest.config.*`, `playwright.config.*`, `cypress.config.*`, or runner settings inside `package.json`. The presence and shape of this file is your source of truth. If multiple runners are configured, the `scripts.test` entry tells you which is canonical.
3. **An existing test file** — pick a representative one and read it. It shows the import style, helpers, file naming (`.test.*` / `.spec.*` / something else), and where tests live relative to source (co-located, sibling folder, top-level directory). Match what's there.
4. **CI workflow files** — see what already runs on PRs (lint, type-check, unit, E2E, coverage) so you know what's enforced and what's missing.

## What to derive (don't pre-list)

- Runner and its config
- Framework
- Component-testing utilities and any network/mocking layer in use
- Coverage tool and thresholds, if any
- The exact command and package manager (read it from `scripts` and the lockfile — don't guess)
- Test file naming and location conventions

## When to stop and advise

If any of the following is true, raise it with the user **before** writing tests:

- No runner config and no test script — testing isn't set up yet; agree on the stack first.
- `scripts.test` is broken, points at nothing, or fails on a clean checkout.
- Two conventions coexist in the codebase (e.g. some files co-located, some in `__tests__/`; some `.test.`, some `.spec.`). Ask which one to follow rather than picking arbitrarily.
- The test utilities in the project look mismatched with the framework (e.g. a React project with no DOM testing utility installed) — it usually means a missing setup step.
- No existing tests at all in the area you're about to touch — propose the convention you'll establish and confirm before generating files.

Surfacing these is more useful than silently picking a default.
