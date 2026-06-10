# Backend Investigation Techniques

Backend-specific observation. For generic guidance (source cross-referencing, completion criteria), see `../../generic-qa/references/investigation.md`. For the tools, see `tooling.md`.

## The loop

1. **Reproduce via the API.** Send the request that triggers the behavior in question; save the transcript.
2. **Correlate the logs.** Find the log lines for that request (match on request-id/trace-id); save the excerpt.
3. **Confirm the side effect in the DB.** Snapshot the affected rows before and after; prove the write happened or didn't.
4. **Cross-reference source** (if available) to explain *why* — trace the request to the handler and the exact line that produces the behavior.

## What counts as the assertion point

The single request+response (plus its DB/log corroboration) that answers the question. Capture evidence there specifically — not for every incidental call.

## Evidence is brief, clear, and obvious

The report is **not** a pile of files. It leads with the answer and a verdict; evidence is one compact block; raw artifacts are linked.

Headline block (goes in the report and, at ship time, the PR body):

```
### Backend QA Evidence
Request:  POST /api/orders → 422 (expected 201)
Cause:    missing-tenant validation rejects valid payload — orders/service.py:88
DB:       no row written (orders count unchanged: 1041 → 1041)
Logs:     ValidationError logged at req-id 7f3a (orders/service.py:88)
Verdict:  ❌ Bug confirmed
Details:  transcript · before/after snapshot · logs → Asana task XYZ-123
```

- One screen. Lead with what happened and the verdict.
- Raw transcripts, snapshots, and log excerpts attach to the Asana task (see `../../generic-qa/process.md` → Step 6), referenced by `Details:`.
- Follow `../../generic-qa/references/reporting.md` for confidence levels (Confirmed / Likely / Suspicion) and the full report structure.

## Anti-patterns

| Doing this... | Means you're off track |
|---|---|
| Reading source without sending a request | Observe the running API first |
| Dumping full logs/transcripts into the report | Brief block; link the raw files |
| Reporting "likely" without trying to reproduce | Send the request first |
| Destructive writes against production | Non-prod only |
| Asserting on an incidental call, not the behavior | Capture at the assertion point |
