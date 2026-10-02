# Installing cortex-workflow for OpenCode

## Prerequisites

- [OpenCode](https://opencode.ai) installed
- `ASANA_PERSONAL_ACCESS_TOKEN` set in your environment (optional — needed for Asana-backed skills)

## Quick Install

Run the setup script:

```bash
bash setup.sh --opencode
```

This validates prerequisites (gh, ssh, tokens) and merges the required plugin
and dependency configuration into your `opencode.json`. Restart OpenCode after.

## Manual Install

Add `cortex-workflow` and its required `superpowers` dependency to your
`opencode.json` plugin array:

```json
{
  "plugin": [
    "cortex-workflow@git+https://github.com/SIROC-Labs/cortex.git",
    "superpowers@git+https://github.com/obra/superpowers.git"
  ]
}
```

The `dev-toolkit` plugin ships in the same repo package — the adapter registers
its skills automatically; no extra `plugin` entry is needed.

### MCP servers for browser and mobile QA (per project)

`web-qa` and `mobile-qa` drive two MCP servers, `chrome-devtools` and
`mobile-mcp`. OpenCode starts every configured MCP server in every session, so
they are not registered globally: add them to the `opencode.json` of each
project that runs browser or mobile QA. Copy only the one you need.

```json
{
  "mcp": {
    "chrome-devtools": {
      "type": "local",
      "command": ["sh", "-c", "bin=$(npx -y --package=chrome-devtools-mcp@latest -c \"command -v chrome-devtools-mcp\") || exit 1; exec \"$bin\" --experimentalScreencast --no-usage-statistics"]
    },
    "mobile-mcp": {
      "type": "local",
      "command": ["sh", "-c", "bin=$(npx -y --package=@mobilenext/mobile-mcp@latest -c \"command -v mcp-server-mobile\") || exit 1; exec \"$bin\""]
    }
  }
}
```

The source of truth is `plugins/cortex-qa-tools/.mcp.json`; each entry there is
`command` followed by `args`.

## Updating

Re-run `setup.sh --opencode`. It is idempotent — it merges the latest config
and clears the plugin cache so OpenCode picks up the newest commit.

## Verify

Ask OpenCode: "list available skills"

You should see cortex-workflow and superpowers skills. Key entry point: use the
skill tool to load `cortex-workflow/start-task` with an Asana task URL.

## Getting Help

- Report issues: https://github.com/SIROC-Labs/cortex/issues
