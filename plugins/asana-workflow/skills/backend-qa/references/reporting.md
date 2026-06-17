# QA Report

One screen. Lead with the verdict, then the coverage picture, then the run evidence. The report
answers three questions: **is it tested enough, does it pass, and what does the coverage actually
protect?**

## Verdict

One of:

- **✅ Pass** — changed behaviours are covered to the bar, the fast and integration suites are green,
  no high-severity gaps.
- **⚠️ Pass with gaps** — suites green, but medium gaps remain (weak assertions, missing error paths).
  List them; they are follow-ups, not blockers.
- **❌ Fail** — at least one of: a high-severity gap (uncovered behaviour, mock-masking, **gate
  violation — a unit test mocking a boundary that should be an integration test**, **untested new
  boundary**, skipped integration), a failing test on a changed behaviour, or a suite that never ran.

Green tests with a high-severity coverage gap is a **Fail**, not a pass — state this plainly. A
boundary covered only by a green mocked unit test is a Fail: the integration test is mandatory, and
the mock must be replaced-then-removed, not kept alongside it.

## Coverage by area

For each meaningful area of the change, a row. **"Why it matters" is mandatory** — the failure the
coverage guards against. Coverage with no articulated risk is noise.

```
Area: payments — webhook customer upsert
What's tested:  integration (real Mongo) — upsert creates, re-upsert updates, created_at immutable
Why it matters: a $set on created_at would silently break FIFO ordering of customer records
Gaps:           none
Verdict:        ✅

Area: tracking — etsy get_listing client
What's tested:  contract (WireMock) — 200 maps to model; 404/429/5xx mappings
Why it matters: a wrong status mapping silently drops listings from tracking
Gaps:           retry-then-succeed path not exercised
Verdict:        ⚠️
```

## Run evidence

The compact result of [running-tests.md](running-tests.md) — each suite separately, never merged:

```
### Backend QA — Test Run
Scope:        branch PD261-370 vs main — 12 production files, 9 test files
Fast suite:   make tests           → 1041 passed, 0 failed, 0 skipped
Integration:  make integration-tests → 188 passed, 0 failed, 3 skipped ⚠️ (CH container absent)
Environment:  pytest 8.x · Docker present · clickhouse:26.2, mongo:7.0
Verdict:      ❌ Fail — 3 ClickHouse integration tests skipped; those queries are unverified
```

A skipped integration test is called out, never folded into "passed".

## Gaps & handoff

List the gap taxonomy hits from [coverage-audit.md](coverage-audit.md), ordered by severity, each
with the behaviour it leaves unverified. For anything that needs new or fixed tests, hand off to
[backend-testing](../../backend-testing/SKILL.md) — name the behaviours to cover; do not write them
in backend-qa.

## Confidence

State it: **Confirmed** (you ran the suites and read the tests), **Likely** (read the tests, couldn't
run a suite — say which and why), or **Suspicion** (inference only). Never report a clean pass at
anything below Confirmed.
