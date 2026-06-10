# SIROC Cortex

Central repository for SIROC's AI context: skills, agents, hooks, and orchestration logic. Distributed as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

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
| `mobile-testing` | Unit + integration testing patterns for native iOS, native Android, and Kotlin Multiplatform |
| `backend-qa` | Investigates and verifies bugs in running backend APIs/services via HTTP, logs, DB snapshots, and Sentry |
| `backend-testing` | Integration-first testing patterns for backend APIs/services using testcontainers, spec-driven fakes, and contract tests |
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

Run the setup script — it validates prerequisites, configures tokens, and guides you through plugin installation:

```bash
bash setup.sh
```

### What the Script Does

**GitHub CLI** — Checks that `gh` is installed, authenticated, and has access to the private `Siroc-Lab/cortex` repo.

**Git SSH** — Tests SSH authentication to GitHub. If you use SSH keys, it offers to configure the HTTPS-to-SSH rewrite Claude Code needs:

```bash
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

**Asana token** — Looks for `ASANA_PERSONAL_ACCESS_TOKEN` in your environment. If missing, prompts you to paste one (from https://app.asana.com/0/my-apps) and writes it to your profile.

**GitHub token** — Checks for `GITHUB_TOKEN` or `GH_TOKEN` for marketplace auto-updates. Can extract one from `gh auth token` if not set.

**Plugin installation** — Once all prerequisites pass, prints the exact Claude Code commands to run:

1. `/plugin marketplace add Siroc-Lab/cortex`
2. `/plugin install asana-workflow@siroc-cortex`
3. `/plugin install dev-toolkit@siroc-cortex`

> If the script added tokens to your shell profile, reload your terminal (`source ~/.zshrc`) before continuing.

## Updating

```
/plugin marketplace update siroc-cortex
/plugin update asana-workflow@siroc-cortex
/plugin update dev-toolkit@siroc-cortex
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License

Proprietary - SIROC Team
