# Investigation Techniques

## Observation via Testing Tool

All findings come from **observing the running application**. The platform extension's `references/investigation.md` details the specific tools available. These are the universal techniques:

### Navigation
- Go to the relevant screen, page, or view in the SUT
- Observe the rendered state
- Check for visual anomalies, missing elements, incorrect states

### Interaction
- Trigger the flow the operator asked about
- Observe state changes after interaction
- Test the specific behavior in question

### Log Inspection
- Check for errors, warnings, or exceptions in the platform's log output
- Note uncaught errors or unexpected entries
- Correlate log entries with observed behavior

### Element Inspection
- Inspect element states (enabled/disabled, visible/hidden, properties)
- Check element presence or absence
- Verify element attributes relevant to the issue

### Evidence Capture
- Screenshot at key moments: before, during, and after the issue
- Record if the issue involves motion, transitions, or timing
- Capture log output and traces that support findings

## Source Code Cross-Reference

When source code is available in the working directory, use it to **explain** findings — not to replace runtime observation.

**Good:** "The button is disabled because [state] is true. In `src/path/file:45`, the handler sets this state but the error path on line 62 never resets it."

**Bad:** "Looking at the code, the button might be disabled when [state] is true." (No runtime verification.)

### How to Cross-Reference

1. Observe the behavior in the SUT first
2. Identify the relevant component from the screen/view
3. Read the source to understand the logic
4. Trace the specific code path that produces the observed behavior
5. Include file:line references in the report

## Completion Criteria

Investigation is done when:

- **The question is answered** — with evidence
- **Root cause is identified** — with a confidence level and supporting evidence
- **Blocked** — a tooling or access issue prevents further investigation; the operator has been told why

## Anti-Patterns

| Doing this... | Means you're off track |
|---|---|
| Reading source code without opening the app | Investigate the SUT, not the codebase |
| Reporting "likely" without trying to reproduce | Attempt reproduction first |
| Guessing the answer from code patterns | Observe the actual behavior |
| Investigating beyond the operator's question | Stay focused on what was asked |
| Silently giving up on reproduction | Tell the operator and ask for help |
