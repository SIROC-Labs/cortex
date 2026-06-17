# Installing asana-workflow for OpenCode

## Prerequisites

- [OpenCode](https://opencode.ai) installed
- `ASANA_PERSONAL_ACCESS_TOKEN` set in your environment

## Quick Install

Run the setup script:

```bash
bash setup.sh --opencode
```

This validates prerequisites (gh, ssh, tokens) and merges the required plugin,
dependency, and MCP configuration into your `opencode.json`. Restart OpenCode
after.

## Manual Install

Add `asana-workflow` and its required `superpowers` dependency to your
`opencode.json` plugin array:

```json
{
  "plugin": [
    "asana-workflow@git+https://github.com/SIROC-Labs/cortex.git",
    "superpowers@git+https://github.com/obra/superpowers.git"
  ]
}
```

The `dev-toolkit` plugin ships in the same repo package — the adapter registers
its skills automatically; no extra `plugin` entry is needed.

### Required MCP servers for QA

The QA MCP servers (`mobile-mcp`, `chrome-devtools`) are registered automatically
by the plugin adapter from `plugins/asana-workflow/.mcp.json` (the single source
of truth) when the plugin loads — no manual `mcp` config needed. If one is
unavailable, add it to `opencode.json` under `"mcp"` as
`{ "type": "local", "command": [<command>, <args>...] }` using the command and
args from `.mcp.json`.

## Updating

Re-run `setup.sh --opencode`. It is idempotent — it merges the latest config
and clears the plugin cache so OpenCode picks up the newest commit.

## Verify

Ask OpenCode: "list available skills"

You should see asana-workflow and superpowers skills. Key entry point: use the
skill tool to load `asana-workflow/start-task` with an Asana task URL.

## Getting Help

- Report issues: https://github.com/SIROC-Labs/cortex/issues
