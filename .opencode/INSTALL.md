# Installing asana-workflow for OpenCode

## Prerequisites

- [OpenCode](https://opencode.ai) installed
- `ASANA_PERSONAL_ACCESS_TOKEN` set in your environment

## Quick Install

Run the setup script:

```bash
bash setup.sh --opencode
```

This validates prerequisites (gh, ssh, tokens) and merges the required
configuration into your `opencode.json`. Restart OpenCode after.

## Manual Install

Add to your `opencode.json` plugin array:

```json
{
  "plugin": ["asana-workflow@git+https://github.com/Siroc-Lab/cortex.git"]
}
```

### Optional: superpowers

For brainstorming, TDD, and git worktree support, also install superpowers:

```json
{
  "plugin": [
    "asana-workflow@git+https://github.com/Siroc-Lab/cortex.git",
    "superpowers@git+https://github.com/obra/superpowers.git"
  ]
}
```

### Optional: MCP servers for QA

If you test mobile or web apps, add these MCP servers:

```json
{
  "mcp": {
    "mobile-mcp": {
      "type": "local",
      "command": ["npx", "-y", "@mobilenext/mobile-mcp@latest"]
    },
    "chrome-devtools": {
      "type": "local",
      "command": ["npx", "-y", "chrome-devtools-mcp@latest", "--experimentalScreencast"]
    }
  }
}
```

## Updating

Re-run `setup.sh --opencode`. It is idempotent — it merges the latest config
and clears the plugin cache so OpenCode picks up the newest commit.

## Verify

Ask OpenCode: "list available skills"

You should see asana-workflow skills. Key entry point: use the skill tool to
load `asana-workflow/start-task` with an Asana task URL.

## Getting Help

- Report issues: https://github.com/Siroc-Lab/cortex/issues
