# Frontend Testing Infrastructure

Frontend-specific additions on top of `../../generic-testing/references/infrastructure.md`. Read that first — coverage principles, PR gates, flake protocol, and reporting live there. This doc only covers what's different about a frontend codebase.

Before applying anything here, read the project's existing runner config and CI workflows. Adapt — don't paste.

## Coverage provider

Prefer the runner's V8 provider over Babel/Istanbul instrumentation when both are available — V8 is faster and more accurate on modern bundled code. Use whatever the runner already configures unless there's a concrete reason to switch.

Adapt include/exclude globs to the project's actual source layout. Exclude type declarations, barrel files (re-export `index.*`), stories, generated code, and configs.

## E2E as a separate CI job

E2E typically needs browser binaries and possibly a running dev server or test backend. Don't pile it onto the unit/integration job:

- Install browser binaries (cached).
- Start the dev server or point at a test environment.
- Run the E2E suite.
- Upload traces/screenshots on failure.

Whether E2E blocks merge or runs advisory is a project decision — match what the team already does.
