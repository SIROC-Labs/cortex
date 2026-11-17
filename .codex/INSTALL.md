# Installing SIROC Cortex for Codex

## Prerequisites

- Codex installed

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
`codex plugin add` for `dev-toolkit` and `product` from the `siroc-cortex`
marketplace.

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
`.agents/plugins/marketplace.json` and not a folder under `plugins/`. Codex
expects a marketplace root directory that contains
`.agents/plugins/marketplace.json`.

Then install the plugins from the shell:

```bash
codex plugin add dev-toolkit@siroc-cortex
codex plugin add product@siroc-cortex
```

The marketplace manifest is:

```text
.agents/plugins/marketplace.json
```

Each plugin's manifest is:

```text
plugins/<plugin>/.codex-plugin/plugin.json
```

## Verify

Start a new Codex session and check that the `dev-toolkit` and `product` skills
are available.

In the Codex CLI, use `/plugins` to verify the plugins are installed and enabled,
then use `/skills` to browse and invoke plugin skills. You can also ask in
natural language, for example: "Use create-prd with this document: <url>".

In the Codex app, enabled skills also appear in the slash command list, and you
can explicitly invoke skills by typing `$` in the composer.

## Updating

Pull the latest repository changes and restart Codex so it reloads the plugin
metadata and skills.

## Getting Help

- Report issues: https://github.com/SIROC-Labs/cortex/issues
