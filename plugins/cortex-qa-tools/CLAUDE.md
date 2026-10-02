# cortex-qa-tools Plugin — Development Guide

Ships the two MCP servers that the cortex-workflow QA skills drive: `chrome-devtools`
(web-qa) and `mobile-mcp` (mobile-qa). It has no skills.

They live in their own plugin because a runtime starts a plugin's stdio MCP servers in
every session where the plugin is enabled, used or not. Bundled into cortex-workflow, they
cost every session on every repo a Chrome DevTools server and a mobile server. Here, each
project opts in.

## Plugin Structure

```
cortex-qa-tools/
├── CLAUDE.md              ← you are here
├── .mcp.json              ← the two servers — single source of truth for every runtime
├── .claude-plugin/
│   └── plugin.json        ← Claude Code manifest (picks up .mcp.json from the plugin root)
└── .codex-plugin/
    └── plugin.json        ← Codex manifest ("mcpServers": "./.mcp.json")
```

## Enabling it

| Runtime | Command | Scope |
|---|---|---|
| Claude Code | `claude plugin install cortex-qa-tools@siroc-cortex --scope project` (shared via `.claude/settings.json`) or `--scope local` (just you) | Per project |
| Codex | `codex plugin add cortex-qa-tools@siroc-cortex` | Global: Codex has no per-project plugins |
| OpenCode | Copy the servers into the project's `opencode.json` (see `.opencode/INSTALL.md`) | Per project |

`setup.sh` never installs this plugin; it prints these commands instead.

## How the servers launch

Each entry runs `sh -c` that asks `npx` for the package's binary path and then `exec`s it:

```sh
bin=$(npx -y --package=<pkg>@latest -c "command -v <bin>") || exit 1; exec "$bin" ...
```

`npx <pkg>` would leave an `npm exec` wrapper alive for the whole session; this leaves
one process per server. Keep `command`/`args` plain (no `${CLAUDE_PLUGIN_ROOT}`) so Codex
and OpenCode can run the same entries.

`chrome-devtools-mcp` runs with `--no-usage-statistics`: with statistics on, it keeps a
telemetry watchdog process alive next to each server.

## Testing a change

Talk to a server over stdio without any agent runtime:

```bash
python3 - <<'PY'
import json, subprocess
s = json.load(open("plugins/cortex-qa-tools/.mcp.json"))["mcpServers"]["chrome-devtools"]
p = subprocess.Popen([s["command"], *s["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
p.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}\n'); p.stdin.flush()
print(p.stdout.readline().decode()[:200]); p.stdin.close(); p.wait()
PY
```
