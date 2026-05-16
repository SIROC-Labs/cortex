---
name: web-qa
version: 0.1.0
description: >
  Use when the operator asks to investigate a specific question or problem in a running web application —
  triggers include "QA this", "why is X broken", "test this flow", "/qa", "/web-qa", or any specific question
  about a web app's behavior. Requires a running web app (local or remote) and Chrome DevTools MCP.
argument-hint: <url-of-sut>
---

# Web QA

Investigate questions and problems in running **web** applications using Chrome DevTools MCP.

## Base Process

Read and follow `../generic-qa/process.md` as the QA process. This skill provides the web platform bindings below.

## Platform Bindings

- **Testing tool:** Chrome DevTools MCP — see `references/tooling.md`
- **SUT discovery:** URL-based — see `references/discovery.md`
- **Investigation techniques:** DOM, console, network — see `references/investigation.md`

## Reference Files

- **`../generic-qa/process.md`** — Universal QA flow (the process to follow)
- **`../generic-qa/references/reporting.md`** — Confidence levels, report structure
- **`../generic-qa/references/investigation.md`** — Generic investigation guidance
- **`references/tooling.md`** — Chrome DevTools MCP verification, screenshots, screencasts
- **`references/discovery.md`** — URL-based SUT discovery
- **`references/investigation.md`** — Web-specific observation techniques (DOM, console, network)
