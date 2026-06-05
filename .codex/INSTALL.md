# Installing asana-workflow for Codex

## Prerequisites

- Codex installed
- `ASANA_PERSONAL_ACCESS_TOKEN` set in your environment

## Quick Install

Run the setup script:

```bash
bash setup.sh --codex
```

This validates prerequisites and adds the `SIROC-Labs/cortex` marketplace (remote by
default — no local clone needed; pass `--dev` to source from your working copy
instead).

The setup script asks whether to install all plugins now or only register the
marketplace so you can choose plugins yourself. When installing, it runs
`codex plugin add` for you:
`asana-workflow` and `dev-toolkit` from the `siroc-cortex` marketplace, and the
required `superpowers` dependency from the official `openai-curated` catalog
(its single canonical source — Codex does not dedupe identically named plugins
across marketplaces, so it is not shipped in `siroc-cortex`). The QA MCP servers
declared in `plugins/asana-workflow/.mcp.json` load automatically when the
plugin is enabled — no `codex mcp add` step.

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
codex plugin add dev-toolkit@siroc-cortex
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

The MCP servers declared there load automatically when the plugin is enabled.
If one is unavailable, register it manually with `codex mcp add <name> -- <command> <args>`
using the command and args from `.mcp.json` (the single source of truth).

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
