# Testing Tool: Chrome DevTools MCP

## Verification

Call `list_pages` to verify Chrome DevTools MCP is connected and functional. This must succeed before any investigation begins.

**Expected success:** Returns a list of open browser pages/tabs.

**Failure means:**
- Chrome DevTools MCP is not configured or not started
- Node.js is not installed (required for npx)
- Chrome is not installed

## Setup Guide

**HARD GATE** — do not proceed with investigation if the testing tool is not working. If Chrome DevTools MCP is unavailable, immediately run the diagnostics below **before** doing anything else.

### When Chrome DevTools MCP is unavailable

Run this first:

```bash
which node 2>/dev/null && node --version
```

- **No `node`:** Node.js is required for the MCP to run via npx — tell the operator to install it, then restart Claude Code.
- **`node` found:** The MCP should auto-launch and manage its own Chrome instance. If tools are still unavailable, the operator needs to restart their Claude Code session so the MCP server is picked up.

## Taking Screenshots

Use Chrome DevTools MCP screenshot capabilities to capture evidence at key moments:
- Before reproducing the issue (baseline state)
- During reproduction (the problematic state)
- After any state changes relevant to the investigation

**Evidence capture is an inline action, not a stopping point.** After taking a screenshot or any evidence step, immediately continue with the next investigation step. Do not pause, summarize, or wait for operator input unless explicitly asked.

Use `take_screenshot` with `filePath` to save directly to `$EVIDENCE_DIR`:

```
take_screenshot filePath: "$EVIDENCE_DIR/01-initial-state.png"
```

For small captures (< 2MB) without a filePath it returns base64 — always use `filePath` for evidence that needs to be uploaded. Use descriptive, ordered names (`01-`, `02-`, etc.). Always include screenshots in the report — they are primary evidence.

## Screen Recording

Use `screencast_start` / `screencast_stop` for issues involving:
- Transitions or animations
- Multi-step flows where timing matters
- Flicker, flash, or transient visual bugs
- Race conditions visible in the UI

**HARD GATE** — `ffmpeg` must be installed and in PATH. Before attempting to record:

```bash
which ffmpeg 2>/dev/null && ffmpeg -version | head -1
```

- **No `ffmpeg`:** Tell the operator: "Video recording requires ffmpeg. Please install it and restart your terminal." Do not proceed with recording until confirmed.
- **`ffmpeg` found:** Proceed with recording.

If the operator declines to install ffmpeg, fall back to sequential screenshots and note in the report that video evidence was not available.

**Start recording** (saves to `$EVIDENCE_DIR`):
```
screencast_start path: "$EVIDENCE_DIR/recording.mp4"
```

**Stop recording:**
```
screencast_stop
```

The tool produces an MP4 file directly. Include it in the evidence upload alongside the assertion-point screenshot.
