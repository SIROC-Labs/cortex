# SIROC Cortex

Central repository for SIROC's AI context: skills, agents, hooks, and orchestration logic. Distributed as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces), an OpenCode plugin, and a Codex plugin marketplace.

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
| `implement-feature` | Routes implementation work to the right development skill per runtime — plan-aware (create plan / execute plan / implement inline); works standalone or invoked from `start-task` |
| `mobile-qa` | Investigates and verifies bugs in iOS simulators and Android emulators via mobile-mcp |
| `web-qa` | Investigates and verifies bugs in running web applications via Chrome DevTools MCP |
| `mobile-testing` | Unit + integration testing patterns for native iOS, native Android, and Kotlin Multiplatform |
| `create-prd` | Generates a complete PRD from any combination of sources: Asana task URL, Notion page, Figma file, local folder, or any web URL |
| `task-breakdown` | Decomposes product specs into milestone-based task roadmaps with rationale, dependencies, and acceptance criteria |
| `submit-breakdown` | Faithfully replicates a task breakdown into Asana as Refinement-status tasks; handles originating task disposition |
| `refine-tasks` | Turn Refinement-status Asana tasks into one-shotters with attached implementation plans |

### dev-toolkit

Independent, reusable development utilities. A home for self-contained skills that aren't tied to any particular workflow and work in any repository.

**Skills included:**

| Skill | Description |
|-------|-------------|
| `update-pr` | Sync PR branch with its base branch: fetch → rebase/merge → resolve conflicts → push |

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

### Codex

```bash
bash setup.sh --codex
```

This validates prerequisites, adds the `SIROC-Labs/cortex` marketplace (remote by default — no clone needed; pass `--dev` to use your local working copy), and installs `asana-workflow` (from `siroc-cortex`) and its required `superpowers` dependency (from the official `openai-curated` catalog) with `codex plugin add`. The MCP servers declared by the plugin load automatically. Restart Codex afterwards — no `/plugins` step needed.

See [.codex/INSTALL.md](.codex/INSTALL.md) for manual install and detailed instructions.

### All agents

```bash
bash setup.sh --all
```

Installs for every supported agent in one run. Each agent is installed independently — if one fails (or its CLI isn't installed), the others still proceed — and a per-agent success/failure summary is printed at the end. Add `--dev` to source from your local clone.

### What the Script Does

**GitHub CLI** — Checks that `gh` is installed, authenticated, and has access to the private `SIROC-Labs/cortex` repo.

**Git SSH** — Tests SSH authentication to GitHub. If you use SSH keys, it offers to configure the HTTPS-to-SSH rewrite:

```bash
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

**Asana token** — Looks for `ASANA_PERSONAL_ACCESS_TOKEN` in your environment. If missing, prompts you to paste one (from https://app.asana.com/0/my-apps) and writes it to your profile.

**GitHub token** — Checks for `GITHUB_TOKEN` or `GH_TOKEN` for marketplace auto-updates. Can extract one from `gh auth token` if not set.

**Plugin installation** — Once all prerequisites pass:
- Claude Code: installs the marketplace, `asana-workflow`, and `dev-toolkit` (user scope) via the `claude` CLI — dependencies (`feature-dev`, `superpowers`) auto-resolve; falls back to printing `/plugin` commands if the CLI isn't on PATH
- OpenCode: merges the plugin configuration into `opencode.json` and clears the cache (the adapter registers both asana-workflow and dev-toolkit skills)
- Codex: adds the `SIROC-Labs/cortex` marketplace (remote by default; `--dev` for a local clone) and installs `asana-workflow`, `dev-toolkit` (from `siroc-cortex`) and `superpowers` (from `openai-curated`) via `codex plugin add`; declared MCP servers load automatically from the plugin manifest

> If the script added tokens to your shell profile, reload your terminal (`source ~/.zshrc`) before continuing.

## Updating

### Claude Code

```
/plugin marketplace update siroc-cortex
/plugin update asana-workflow@siroc-cortex
/plugin update dev-toolkit@siroc-cortex
```

### OpenCode

```bash
bash setup.sh --opencode
```

The script is idempotent — it re-merges the latest configuration and clears the plugin cache.

### Codex

Update with the Codex CLI:

```bash
codex plugin marketplace upgrade siroc-cortex
codex plugin add asana-workflow@siroc-cortex
codex plugin add dev-toolkit@siroc-cortex
```

Restart Codex afterwards. For a `--dev` install, `git pull` your clone and re-run the `codex plugin add` commands instead — `marketplace upgrade` only applies to the remote Git marketplace.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License

Proprietary - SIROC Team
