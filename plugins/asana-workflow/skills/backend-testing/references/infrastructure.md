# Backend Testing Infrastructure

Backend-specific additions on top of `../../generic-testing/references/infrastructure.md`. Read that first — coverage principles, PR gates, flake protocol, and reporting live there. This doc covers what's different about a backend codebase: the heavy-local / light-CI split and the PR evidence contract.

Before applying anything here, read the project's existing CI workflows and test config. Adapt — don't paste.

## Heavy-local / light-CI split

Testcontainer integration suites are too slow and resource-heavy to run on every push. Split the suite by tagging:

- **Fast tests** — unit tests + light integration that needs no heavy container. **Run in CI on every push**, gate merge.
- **Heavy tests** — full testcontainer integration (DB, queue, broker, external fakes). **Run locally as a pre-ship gate**, excluded from CI.

Tag with the runner's native mechanism: `pytest` markers (`@pytest.mark.integration`) + `-m "not integration"` in CI; Go build tags (`//go:build integration`); JUnit `@Tag("integration")`; Jest `testPathIgnorePatterns` / project split. CI runs the fast selection; a documented local command runs the heavy selection.

> If the project's CI *can* run Docker (Docker-in-Docker, a Docker-enabled runner) and the team wants the heavy suite gated in CI too, that's a per-project decision — but the default this skill assumes is heavy-local.

## The PR evidence contract

Because CI no longer proves the heavy suite passed, **the PR must carry the evidence**. The heavy suite is run locally before shipping and its result is captured into the PR.

The evidence is **brief, clear, and obvious — not a pile of files.** The PR body carries a compact block:

```
### Backend QA Evidence
Tests:    142 passed (38 unit · 104 integration) — 2m18s
          testcontainers: postgres:16, redis:7, clickhouse:24.3 (generic)
Coverage: business logic 87%
QA:       ✅ 4 flows verified — login, create order, payment webhook, refund
Verdict:  ✅ Ready to ship
Details:  full transcripts · DB snapshots · logs → Asana task XYZ-123
```

Rules:

- **One screen.** Counts, duration, pinned container versions, coverage on business logic, a one-line QA result, a verdict.
- **Raw artifacts are linked, not dumped** — full transcripts, DB snapshots, and logs attach to the linked Asana task (the existing QA-evidence convention), referenced by the `Details:` line.
- **`pre-ship-check`'s QA gate consumes this block**; `create-pr` embeds it in the PR body.

## CI job shape

The fast CI job:

1. Install dependencies (cached).
2. Static analysis (type check, lint).
3. Run the **fast** test selection with coverage.
4. Upload coverage as an artifact.
5. Fail on any step — no `continue-on-error` for tests.

Heavy integration is **not** a CI job by default; it is the local pre-ship gate above.
