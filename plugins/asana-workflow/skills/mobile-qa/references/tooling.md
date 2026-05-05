# Testing Tool: mobile-mcp

[mobile-mcp](https://github.com/mobile-next/mobile-mcp) — unified API for iOS simulators and Android emulators. Tool names and parameters are self-documented via the MCP schema; this file covers only what the schema doesn't tell you.

## Usage Tips

- **Fetch tool schema first** — Always use `ToolSearch` to load a mobile-mcp tool's schema before calling it for the first time. The schema is small (a few lines) and cheaper than a failed call + retry cycle. Never guess parameter names.
- **Tap before typing** — `mobile_type_keys` requires the input field to be focused first. Tap the field, then type.
- **Coordinates from bounds** — all gestures are coordinate-based. See `investigation.md` → Gestures for coordinate calculation and rules.
- **Android back button** — `mobile_press_button` with `back` is essential for navigation, dismissing dialogs, and closing keyboards. iOS has no equivalent (use UI buttons or swipe gestures).
- **Transient UI** — snackbars, toasts, and alerts disappear quickly. Screenshot immediately when they appear.
- **Evidence persistence** — at assertion points, use `mobile_save_screenshot` (not `mobile_take_screenshot`) to save to the evidence directory. For recordings, pass an explicit `output` path in the evidence directory. See `../../generic-qa/process.md` → Evidence Directory.

## Verification

1. `mobile_list_available_devices` — must return a device list.
2. `mobile_take_screenshot` — must return a screen image.

**HARD GATE** — cannot proceed without both succeeding. If mobile-mcp is unavailable, immediately run the diagnostics below **before** doing anything else.

### When mobile-mcp is unavailable

Run this first:

```bash
which node 2>/dev/null && node --version
```

Then tell the operator what they need to do:

- **No `node`:** Node.js v22+ is required — they need to install it, then restart the agent session.
- **`node` found but mobile-mcp still won't start:** Check MCP server status, then restart the agent session.

After explaining the fix, you may offer native shell commands (`xcrun simctl io`, `adb screenrecord`, etc.) as a **limited fallback** for the current session only — but always present installing Node.js/npx first.

### Prerequisites (check only for the target platform)

- **iOS:** `xcode-select -p` and `xcrun simctl list devices available`
- **Android:** `adb version`
- **Node.js:** v22+ (`node --version`)

## MCP Disconnection Recovery

If any mobile-mcp tool fails mid-session:

1. Tell the operator.
2. Ask them to check `/mcp` and restart mobile-mcp from there.
3. If that doesn't work, restart the agent session.
4. Re-verify with `mobile_list_available_devices` before continuing.

## App State Reset

Reset to clean state before investigation unless operator asks to preserve state.

- **Android:** `adb shell pm clear <package_name>` then `mobile_launch_app`
- **iOS:** No `pm clear` equivalent — uninstall and reinstall:
  ```bash
  xcrun simctl get_app_container booted <bundle_id>  # find .app path
  xcrun simctl uninstall booted <bundle_id>
  xcrun simctl install booted /path/to/App.app
  ```

**Skip reset when:** operator says to keep state, verify mode, or state-dependent investigation.
