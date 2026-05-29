# Installing asana-workflow for Codex

## Prerequisites

- Codex installed
- `ASANA_PERSONAL_ACCESS_TOKEN` set in your environment

## Quick Install

Run the setup script:

```bash
bash setup.sh --codex
```

This validates prerequisites, adds this repository as a local Codex marketplace,
and configures the required MCP servers declared by the plugin.

The marketplace exposes both `asana-workflow` and the required `superpowers`
dependency. The setup script also registers the required QA MCP servers from
`plugins/asana-workflow/.mcp.json` with `codex mcp add`.

Codex CLI currently registers local marketplaces from the shell, but plugin
installation is completed from `/plugins`. After setup, open `/plugins`, search
the `siroc-cortex` marketplace, and install or enable both `asana-workflow` and
`superpowers`.

## Manual Install

Add this repository as a local Codex plugin marketplace:

```bash
codex plugin marketplace add /absolute/path/to/cortex
```

Use the repository root as the marketplace source, not
`.agents/plugins/marketplace.json` and not `plugins/asana-workflow`. Codex
expects a local marketplace root directory that contains
`.agents/plugins/marketplace.json`.

Install `asana-workflow` and `superpowers` from the `siroc-cortex` marketplace
using `/plugins`.
`superpowers` is required for brainstorming, systematic debugging, TDD, worktree
workflows, and non-Claude feature implementation routing.

The marketplace manifest is:

```text
.agents/plugins/marketplace.json
```

The plugin manifest is:

```text
plugins/asana-workflow/.codex-plugin/plugin.json
```

The required MCP manifest is:

```text
plugins/asana-workflow/.mcp.json
```

Register the declared MCPs if you are installing manually:

```bash
codex mcp add mobile-mcp -- npx -y @mobilenext/mobile-mcp@latest
codex mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --experimentalScreencast
```

## Verify

Start a new Codex session and check that both asana-workflow and superpowers
skills are available. Key entry point: use the `start-task` skill with an Asana
task URL.

In the Codex CLI, use `/plugins` to verify the plugin is installed and enabled,
then use `/skills` to browse and invoke plugin skills. You can also ask in
natural language, for example: "Use asana-workflow start-task with this Asana
task URL: <url>".

In the Codex app, enabled skills also appear in the slash command list, and you
can explicitly invoke skills by typing `$` in the composer.

## Updating

Pull the latest repository changes and restart Codex so it reloads the plugin
metadata and skills.

## Getting Help

- Report issues: https://github.com/Siroc-Lab/cortex/issues
