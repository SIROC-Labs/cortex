# cortex-qa-mobile Plugin — Development Guide

Ships the `mobile-mcp` MCP server that the cortex-workflow `mobile-qa` skill drives. It has no skills.

It lives in its own plugin because a runtime starts a plugin's stdio MCP servers in
every session where the plugin is enabled, used or not. Each project opts in, and enables
only the QA servers it needs: `cortex-qa-web` ships `chrome-devtools` separately.

## Plugin Structure

```
cortex-qa-mobile/
├── CLAUDE.md              ← you are here
├── .mcp.json              ← the server — single source of truth for every runtime
├── .claude-plugin/
│   └── plugin.json        ← Claude Code manifest (picks up .mcp.json from the plugin root)
├── .codex-plugin/
│   └── plugin.json        ← Codex manifest ("mcpServers": "./.mcp.json")
└── tests/
    └── test_server_docs.py ← the OpenCode and Codex doc copies match .mcp.json
```

## Enabling it

| Runtime | Command | Scope |
|---|---|---|
| Claude Code | `claude plugin install cortex-qa-mobile@siroc-cortex --scope project` (shared via `.claude/settings.json`) or `--scope local` (just you) | Per project |
| Codex | `codex plugin add cortex-qa-mobile@siroc-cortex` | Global: Codex has no per-project plugins |
| OpenCode | Copy the server into the project's `opencode.json` (see `.opencode/INSTALL.md`) | Per project |

`setup.sh` never installs this plugin; it prints these commands instead.

## How the server launches

The entry runs `sh -c` that asks `npx` for the package's binary path and then `exec`s it:

```sh
bin=$(npx -y --package=<pkg>@latest -c "command -v <bin>") || exit 1; exec "$bin" ...
```

`npx <pkg>` would leave an `npm exec` wrapper alive for the whole session; this leaves
one process. Keep `command`/`args` plain (no `${CLAUDE_PLUGIN_ROOT}`) so Codex
and OpenCode can run the same entry.

## Testing a change

Talk to the server over stdio without any agent runtime:

```bash
python3 - <<'PY'
import json, subprocess
s = json.load(open("plugins/cortex-qa-mobile/.mcp.json"))["mcpServers"]["mobile-mcp"]
p = subprocess.Popen([s["command"], *s["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
p.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}\n'); p.stdin.flush()
print(p.stdout.readline().decode()[:200]); p.stdin.close(); p.wait()
PY
```
