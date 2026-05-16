# SIROC Cortex

Central repository for SIROC's AI context: skills, agents, hooks, and orchestration logic. Distributed as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces) and an OpenCode plugin.

## Marketplace

**Name:** `siroc-cortex`

## Plugins

### asana-workflow

End-to-end Asana-driven development workflow: from ticket to shipped PR with automated task tracking, git management, and team communication.

> For the complete `start-task` lifecycle map (init, checkpointing, routing, QA sub-flow, pause/resume, ship), see [FLOW.md](plugins/asana-workflow/skills/start-task/FLOW.md).

**Skills included:**

| Skill | Description |
|-------|-------------|
| `start-task` | Validates Asana task, creates branch and draft PR, routes to feature-dev or debugging. Writes a per-step checkpoint for resumability; add `fast` to skip sub-skill routing |
| `ship-it` | Orchestrates pre-checks, summary, PR creation, and Asana update |
| `pre-ship-check` | Validates git state, lint, build, and tests |
| `git-check` | Branch safety, working tree cleanliness, debug artifact detection |
| `work-summary` | Session recap for standups, handoffs, and PRs |
| `create-pr` | Full PR lifecycle with Asana linking and reviewer assignment |
| `asana-api` | Asana REST API patterns and common operations |
| `log-task` | Creates an Asana task from work discovered or completed in conversation |
| `fix-bug` | Full bug-fix lifecycle orchestrator: root cause investigation, TDD hard gate, and ship |
| `mobile-qa` | Investigates and verifies bugs in iOS simulators and Android emulators via mobile-mcp |
| `web-qa` | Investigates and verifies bugs in running web applications via Chrome DevTools MCP |

## Installation

### Claude Code

Run the setup script — it validates prerequisites, configures tokens, and guides you through plugin installation:

```bash
bash setup.sh
```

### OpenCode

```bash
bash setup.sh --opencode
```

This validates prerequisites and merges the required configuration into your `opencode.json`.

See [.opencode/INSTALL.md](.opencode/INSTALL.md) for manual install and detailed instructions.

### What the Script Does

**GitHub CLI** — Checks that `gh` is installed, authenticated, and has access to the private `Siroc-Lab/cortex` repo.

**Git SSH** — Tests SSH authentication to GitHub. If you use SSH keys, it offers to configure the HTTPS-to-SSH rewrite:

```bash
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

**Asana token** — Looks for `ASANA_PERSONAL_ACCESS_TOKEN` in your environment. If missing, prompts you to paste one (from https://app.asana.com/0/my-apps) and writes it to your profile.

**GitHub token** — Checks for `GITHUB_TOKEN` or `GH_TOKEN` for marketplace auto-updates. Can extract one from `gh auth token` if not set.

**Plugin installation** — Once all prerequisites pass:
- Claude Code: prints the exact `/plugin` commands to run
- OpenCode: merges the plugin configuration into `opencode.json` and clears the cache

> If the script added tokens to your shell profile, reload your terminal (`source ~/.zshrc`) before continuing.

## Updating

### Claude Code

```
/plugin marketplace update siroc-cortex
/plugin update asana-workflow@siroc-cortex
```

### OpenCode

```bash
bash setup.sh --opencode
```

The script is idempotent — it re-merges the latest configuration and clears the plugin cache.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License

Proprietary - SIROC Team
