# SIROC Cortex

Cortex is a set of skills for Claude Code, OpenCode, and Codex. It covers two things: defining what to build before any code is written, and a few development utilities that work in any repository. This repo distributes them as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces), an OpenCode plugin, and a Codex plugin marketplace.

The earlier end-to-end workflow (task breakdown, development, QA, release, and autonomous execution) was removed from this repo. It is preserved at the [`archive/pre-skill-removal`](https://github.com/SIROC-Labs/cortex/tree/archive/pre-skill-removal) tag.

## Plugins and skills

| Plugin | Skill | What it does |
|---|---|---|
| `product` | `product-one-pager` | Drafts a product one-pager from raw notes, or reviews and strengthens an existing one |
| `product` | `create-prd` | Writes a Product Requirements Document from one or more sources (URLs, files, a problem statement) |
| `product` | `create-spec` | Writes a technical spec (architecture, data, contracts, behaviors, testing strategy) through an interview |
| `dev-toolkit` | `update-pr` | Syncs a PR branch with its base: fetch, rebase or merge, resolve conflicts, push |
| `dev-toolkit` | `cso` | Security audit: secrets, dependencies, CI/CD, infrastructure, OWASP Top 10, STRIDE, LLM/AI |
| `dev-toolkit` | `codex` | Second opinion from the Codex CLI (review, challenge, consult), for non-Codex hosts |
| `dev-toolkit` | `claude` | Second opinion from the Claude Code CLI (review, challenge, consult), for non-Claude hosts |
| `dev-toolkit` | `dependabot-setup` | Dependabot config, alerts, and a daily audit workflow, per repository or per organization |

The two plugins are independent. Install either one or both.

## Installation

### Claude Code

Run the setup script. It validates prerequisites and guides you through plugin installation:

```bash
bash setup.sh
```

### OpenCode

```bash
bash setup.sh --opencode
```

This validates prerequisites and merges the required configuration into your `opencode.json`.

See [.opencode/INSTALL.md](.opencode/INSTALL.md) for manual install and detailed instructions.

### Codex

```bash
bash setup.sh --codex
```

This validates prerequisites, adds the `SIROC-Labs/cortex` marketplace (remote by default, no clone needed; pass `--dev` to use your local working copy), and installs `dev-toolkit` and `product` with `codex plugin add`. Restart Codex afterwards; no `/plugins` step needed.

See [.codex/INSTALL.md](.codex/INSTALL.md) for manual install and detailed instructions.

### All agents

```bash
bash setup.sh --all
```

Installs for every supported agent in one run. Each agent is installed independently. If one fails (or its CLI isn't installed) the others still proceed, and a per-agent success/failure summary is printed at the end. Add `--dev` to source from your local clone.

## Updating

### Claude Code

```
/plugin marketplace update siroc-cortex
/plugin update dev-toolkit@siroc-cortex
/plugin update product@siroc-cortex
```

### OpenCode

```bash
bash setup.sh --opencode
```

The script is idempotent: it re-merges the latest configuration and clears the plugin cache.

### Codex

Update with the Codex CLI:

```bash
codex plugin marketplace upgrade siroc-cortex
codex plugin add dev-toolkit@siroc-cortex
codex plugin add product@siroc-cortex
```

Restart Codex afterwards. For a `--dev` install, `git pull` your clone and re-run the `codex plugin add` commands instead; `marketplace upgrade` only applies to the remote Git marketplace.

## Upgrading from cortex-workflow

`cortex-workflow`, `cortex-qa-web` and `cortex-qa-mobile` no longer exist in the marketplace. Uninstall them:

| Agent | How |
|---|---|
| Claude Code | `/plugin uninstall cortex-workflow@siroc-cortex`, and the same for `cortex-qa-web` and `cortex-qa-mobile` where enabled |
| Codex | `codex plugin remove cortex-workflow@siroc-cortex`, and the same for `cortex-qa-web` and `cortex-qa-mobile` if added |
| OpenCode | Re-run `bash setup.sh --opencode`. It replaces the `cortex-workflow` entry in `opencode.json` with `siroc-cortex` |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License

Proprietary - SIROC Team
