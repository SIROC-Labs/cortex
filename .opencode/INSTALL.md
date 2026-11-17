# Installing SIROC Cortex for OpenCode

## Prerequisites

- [OpenCode](https://opencode.ai) installed

## Quick Install

Run the setup script:

```bash
bash setup.sh --opencode
```

This validates prerequisites (gh, ssh, tokens) and merges the plugin entry into
your `opencode.json`. Restart OpenCode after.

## Manual Install

Add `siroc-cortex` to your `opencode.json` plugin array:

```json
{
  "plugin": [
    "siroc-cortex@git+https://github.com/SIROC-Labs/cortex.git"
  ]
}
```

The package holds both the `dev-toolkit` and `product` plugins. The adapter
registers their skills automatically; no extra `plugin` entry is needed.

If your `opencode.json` still has a `cortex-workflow@git+...` entry, remove it.
That package no longer exists.

## Updating

Re-run `setup.sh --opencode`. It is idempotent — it merges the latest config
and clears the plugin cache so OpenCode picks up the newest commit.

## Verify

Ask OpenCode: "list available skills"

You should see the `dev-toolkit` and `product` skills, for example `update-pr`
and `create-prd`.

## Getting Help

- Report issues: https://github.com/SIROC-Labs/cortex/issues
