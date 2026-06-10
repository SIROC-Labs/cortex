---
name: backend-qa
version: 0.1.0
description: >
  Use when the operator asks to investigate a specific question or problem in a running backend /
  API / service — triggers include "QA this API", "why does this endpoint return X", "test this
  flow", "/backend-qa", or any specific question about a running backend's behavior. Requires a
  running backend (local or staging) reachable over HTTP.
argument-hint: <base-url-or-question>
---

# Backend QA

Investigate questions and problems in running **backend** applications — APIs, services, and workers — and produce concise evidence.

## Base Process

Read and follow `../generic-qa/process.md` as the QA process. This skill provides the backend platform bindings below.

## Platform Bindings

- **Testing tool:** HTTP client + logs + DB access — see `references/tooling.md`
- **SUT discovery:** base-URL based, with a manual auth bootstrap — see `references/discovery.md`
- **Investigation techniques:** request/response, log correlation, DB snapshots — see `references/investigation.md`

## Backend-specific rules

- **Writes are allowed, against non-prod only.** Driving the API — including `POST`/`PUT`/`DELETE` — is the point of backend QA. Run against a local or staging environment. **Never run destructive operations against production data.** Source and deployment stay read-only.
- **Auth bootstrap is blocking.** Protected endpoints need a token the operator obtains manually once; the agent reuses it for the session. See `references/discovery.md`.
- **Evidence is brief.** The report leads with the answer and verdict; the evidence is one compact block; raw artifacts are linked, never dumped. See `references/investigation.md`.

## Reference Files

- **`../generic-qa/process.md`** — Universal QA flow (the process to follow)
- **`../generic-qa/references/reporting.md`** — Confidence levels, report structure
- **`../generic-qa/references/investigation.md`** — Generic investigation guidance
- **`references/tooling.md`** — HTTP client, log access, DB access, evidence saving
- **`references/discovery.md`** — base-URL discovery and manual auth bootstrap
- **`references/investigation.md`** — backend observation techniques and the brief-evidence rule
