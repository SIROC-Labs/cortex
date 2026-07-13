# Web Investigation Techniques

Chrome DevTools MCP observation capabilities. For generic investigation guidance (source code cross-referencing, completion criteria, anti-patterns), see `../../generic-qa/references/investigation.md`.

## Page Navigation
- Navigate to the relevant page/route
- Observe the rendered state
- Check for visual anomalies, missing elements, incorrect states

## Interaction
- Click buttons, fill forms, trigger flows
- Observe state changes after interaction
- Test the specific behavior the operator asked about

## Console Monitoring
- Check for JavaScript errors
- Watch for warnings that indicate problems
- Note any uncaught exceptions or promise rejections

## Network Inspection
- Monitor API calls during the flow
- Check response codes, payloads, timing
- Identify failed requests, slow responses, or missing calls

## DOM Inspection
- Inspect element states (disabled, hidden, aria attributes)
- Check computed styles
- Verify element presence/absence in the DOM
