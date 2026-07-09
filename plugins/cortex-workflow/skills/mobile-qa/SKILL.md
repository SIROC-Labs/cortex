---
name: mobile-qa
version: 0.1.0
description: >
  Use when the operator asks to investigate a specific question or problem in a running mobile application —
  triggers include "/mobile-qa", "QA this app", "test this on mobile", or any specific question about
  a mobile app's behavior. Requires a running app on an iOS simulator or Android emulator and mobile-mcp.
argument-hint: <app-bundle-id-or-device>
---

# Mobile QA

Investigate questions and problems in running **mobile** applications (iOS or Android) using [mobile-mcp](https://github.com/mobile-next/mobile-mcp).

## Platform Detection

Determine the target platform **before** beginning investigation. See `references/discovery.md` for the full resolution flow.

Resolution priority:
1. **Project structure** — Which platform targets exist. Single-platform project → use that platform.
2. **Operator input** — Multi-platform projects (KMP, React Native, Flutter): ask which platform to QA, offering the option to test both.

If the operator chooses **both**, run the same test on each platform sequentially.

## Interaction Mode

**Default: fast mode.** Minimize tool calls — query the accessibility tree once per screen, skip screenshots between actions, batch sequential actions. See `references/investigation.md` → Fast Interaction Mode.

Switch to **standard mode** (screenshot verification after each action) only when:
- Exercising the specific part that was **fixed or created**
- The operator explicitly asks for step-by-step verification
- You hit an unexpected state and need to understand what's on screen

## Base Process

Read and follow `../generic-qa/process.md` as the QA process. This skill provides the mobile platform bindings below.

## Platform Bindings

- **Testing tool:** mobile-mcp — see `references/tooling.md`
- **SUT discovery:** App + device — see `references/discovery.md`
- **Investigation:** Accessibility tree, gestures, device logs — see `references/investigation.md`

## Reference Files

- **`../generic-qa/process.md`** — Universal QA flow
- **`../generic-qa/references/reporting.md`** — Confidence levels, report structure
- **`../generic-qa/references/investigation.md`** — Generic investigation guidance
- **`references/tooling.md`** — mobile-mcp verification, setup, tool reference
- **`references/discovery.md`** — App + device discovery
- **`references/investigation.md`** — Mobile-specific observation and log capture
