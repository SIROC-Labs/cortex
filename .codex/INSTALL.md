# Installing asana-workflow for Codex

## Prerequisites

- Codex installed
- `ASANA_PERSONAL_ACCESS_TOKEN` set in your environment

## Quick Install

Run the setup script:

```bash
bash setup.sh --codex
```

This validates prerequisites, adds the `SIROC-Labs/cortex` marketplace (remote by
default — no local clone needed; pass `--dev` to source from your working copy
instead), and configures the required MCP servers declared by the plugin.

The setup script then installs the plugins for you with `codex plugin add`:
`asana-workflow` from the `siroc-cortex` marketplace, and the required
`superpowers` dependency from the official `openai-curated` catalog (its single
canonical source — Codex does not dedupe identically named plugins across
marketplaces, so it is not shipped in `siroc-cortex`). The setup script also
registers the required QA MCP servers from `plugins/asana-workflow/.mcp.json`
with `codex mcp add`.

Restart Codex afterwards to pick up the plugins and skills — no `/plugins` step
is required.

## Manual Install

Add the marketplace. Normal install (remote — no clone needed):

```bash
codex plugin marketplace add SIROC-Labs/cortex
```

Developer install (point at a local clone instead):

```bash
codex plugin marketplace add /absolute/path/to/cortex
```

For the local form, use the repository root as the marketplace source, not
`.agents/plugins/marketplace.json` and not `plugins/asana-workflow`. Codex
expects a marketplace root directory that contains
`.agents/plugins/marketplace.json`.

Then install the plugins from the shell:

```bash
codex plugin add asana-workflow@siroc-cortex
codex plugin add superpowers@openai-curated
```

`superpowers` is sourced from the official `openai-curated` catalog, not from
`siroc-cortex`. It is required for brainstorming, systematic debugging, TDD, and
non-Claude feature implementation routing.

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

- Report issues: https://github.com/SIROC-Labs/cortex/issues
