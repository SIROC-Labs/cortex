# Mobile Investigation Techniques

Mobile-specific observation using mobile-mcp. For generic guidance (source cross-referencing, completion criteria), see `../../generic-qa/references/investigation.md`.

## Interaction Modes

### Fast mode (default)

Minimize tool calls for fluid, natural interaction:

- Query accessibility tree **once per screen**, reuse coordinates until the screen changes.
- **Skip screenshots** between actions — only screenshot at the assertion point.
- Batch sequential actions on the same screen (tap field → type → tap button) without re-querying.
- Re-query the tree only after navigation, modal appear/dismiss, or list load.

### Standard mode

Screenshot after each action for step-by-step verification. Use only when:
- Exercising the **fixed or created** part of the app
- Operator explicitly requests it
- Unexpected state — need to understand what is on screen

At the **assertion point**, always take a screenshot regardless of mode.

## Accessibility Tree

`mobile_list_elements_on_screen` — the primary way to understand what's on screen. Returns element labels, types, states, accessibility IDs, and bounding boxes.

Use to find interaction targets and verify element presence/absence after actions.

## Gestures

All gestures are coordinate-based. Get element bounds from `mobile_list_elements_on_screen`, calculate center: `x + width/2`, `y + height/2`. **Never hardcode coordinates** — always get fresh bounds when the screen changes.

Tool names and parameters are available via the MCP schema. Key non-obvious tips:
- **Tap before typing** — focus the input field with a tap before calling `mobile_type_keys`.
- **Android back button** — `mobile_press_button` with `back` is essential for navigation, dismissing dialogs, and closing keyboards. iOS has no equivalent (use UI buttons or swipe gestures).

## Navigation Patterns

**iOS:** Tab bars (bottom), back button (top-left) or swipe-from-left, modals dismissed via "Done"/"X"/swipe-down.

**Android:** Bottom navigation, back via `mobile_press_button` with `back` (essential), dialogs dismissed via back button or tap outside. Snackbars/toasts are transient — screenshot immediately.

## Device Logs

mobile-mcp doesn't expose logs directly. Use shell when UI evidence is insufficient:

- **iOS:** `xcrun simctl spawn booted log stream --predicate 'processImagePath contains "<AppName>"' --level debug`
- **Android:** `adb logcat --pid=$(adb shell pidof <package.name>)` (clear buffer first with `adb logcat -c`)

Capture logs **during reproduction** — start stream, then trigger the issue.

## Evidence Capture

Choose mode before starting:

- **Screenshot mode** — single-screen checks, 1–2 images. Take before/after the key action.
- **Video mode** — flows, multi-step validations, or anything needing >2 screenshots:
  1. `mobile_start_screen_recording`
  2. Execute flow in fast mode (no screenshots during recording)
  3. `mobile_stop_screen_recording`
  4. Screenshot at the assertion point

Android recordings max at 180 seconds — split longer flows.

## Known Limitations

- **No network inspection** — suggest proxy tools (Charles, mitmproxy, Proxyman) if needed.
- **No runtime debugging** — use source code cross-referencing to explain "why."
- **No file system access** — suggest `xcrun simctl get_app_container` (iOS) or `adb shell run-as` (Android) if local storage is relevant.
