# SIROC Cortex

**Governance from the idea, not from the code.**

Cortex is a set of skills for Claude Code, OpenCode, and Codex that put software delivery on a defined path, from validating a problem through to a documented release. It holds the coding agent to that path at every step. This repo is the implementation: the skills, agents, and orchestration, distributed as a [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces), an OpenCode plugin, and a Codex plugin marketplace.

## The problem it addresses

AI made teams produce code faster. It did not give leaders back visibility into what actually ships. Writing code is quick now; the disciplined parts (spec, evidence, traceability, release notes) still depend on people remembering to do them. The bottleneck moved from writing code to governing what gets built.

## Where it fits

- Cursor, Copilot, and raw agents help inside the code.
- Jira and Asana track the work but don't enforce how it's done, and they skip the "is this worth building" step.
- Cortex covers the whole path: problem validation and success metrics before the code, evidence and docs after it, not just the build in the middle.

## How it works

Two pieces:

- A **delivery lifecycle**: a fixed sequence of phases (validate, design, plan, execute), each of which completes only when it produces the artifact it's supposed to (a one-pager, a PRD, a task breakdown, QA evidence). This part doesn't depend on which AI you use.
- The **plugin** in this repo: skills that run each phase on a coding agent and check the gates. The agent underneath is swappable (today it's closest to Claude Code), so you're not tied to one vendor.

## The lifecycle, and the skills that run it

| Phase | What you get tools to do | Skills |
|---|---|---|
| **Ideation & discovery** | Frame the problem, validate it's real, define how you'll measure success | `create-prd`, `task-breakdown` |
| **Solution design** | Turn the validated problem into a complete, agreed definition of what to build | `create-prd` |
| **Breakdown & estimation** | Break the solution into tasks with a real effort estimate | `task-breakdown`, `submit-breakdown`, `refine-tasks` |
| **Development** | A workflow that enforces delivery discipline and gets more out of the coding agent | `start-task`, `implement-feature`, `fix-bug` |
| **QA & release** | Validate the build, generate verifiable evidence, ship a documented release | `web-qa`, `mobile-qa`, `backend-qa`, `pre-ship-check`, `ship-it`, `create-pr` |

Each phase has a gate, so work only moves forward once it has produced what the next phase needs: the problem validated, the PRD written, the plan estimated, the evidence collected.

## Early results

From internal projects. These are early and still being validated with more teams:

- End-to-end delivery cycle: roughly 19 days down to under 5.
- Developer onboarding: months down to about a week.
- 2x–3x productivity, depending on how well the developer knows the project.
- QA evidence per feature: hours down to under one.
- Documentation kept close to real time instead of drifting.

## Plugins

Marketplace name: `siroc-cortex`.

### cortex-workflow

End-to-end development workflow: from ticket to shipped PR with automated task tracking, git management, and team communication. This is where most of the lifecycle above lives.

> For the complete `start-task` lifecycle map (init, checkpointing, routing, QA sub-flow, pause/resume, ship), see [FLOW.md](plugins/cortex-workflow/skills/start-task/FLOW.md).

**Skills included:**

| Skill | Description |
|-------|-------------|
| `start-task` | Validates the task, creates branch and draft PR, routes to feature-dev or debugging. Writes a per-step checkpoint for resumability; add `fast` to skip sub-skill routing |
| `ship-it` | Orchestrates pre-checks, summary, PR creation, and task update |
| `pre-ship-check` | Validates git state, lint, build, and tests |
| `git-check` | Branch safety, working tree cleanliness, debug artifact detection |
| `work-summary` | Session recap for standups, handoffs, and PRs |
| `create-pr` | Full PR lifecycle with task linking and reviewer assignment |
| `task-manager` | Neutral task-manager interface (Asana, Jira, …) |
| `task-manager-asana` | Asana provider implementation |
| `task-manager-jira` | Jira provider implementation |
| `log-task` | Creates a task from work discovered or completed in conversation |
| `fix-bug` | Full bug-fix lifecycle orchestrator: root cause investigation, TDD hard gate, and ship |
| `implement-feature` | Routes implementation work to the right development skill per runtime. Plan-aware (create plan / execute plan / implement inline); works standalone or invoked from `start-task` |
| `mobile-qa` | Investigates and verifies bugs in iOS simulators and Android emulators via mobile-mcp |
| `web-qa` | Investigates and verifies bugs in running web applications via Chrome DevTools MCP |
| `mobile-testing` | Unit + integration testing patterns for native iOS, native Android, and Kotlin Multiplatform |
| `backend-qa` | Investigates and verifies bugs in running backend APIs/services via HTTP, logs, and DB snapshots |
| `backend-testing` | Integration-first testing patterns for backend APIs/services using testcontainers, spec-driven fakes, and contract tests |
| `create-prd` | Generates a complete PRD from any combination of sources: Asana task URL, Notion page, Figma file, local folder, or any web URL |
| `task-breakdown` | Decomposes product specs into milestone-based task roadmaps with rationale, dependencies, and acceptance criteria |
| `submit-breakdown` | Faithfully replicates a task breakdown into the task manager as Refinement-status tasks; handles originating task disposition |
| `refine-tasks` | Turn Refinement-status tasks into one-shotters with attached implementation plans |

### dev-toolkit

Independent, reusable development utilities. A home for self-contained skills that aren't tied to any particular workflow and work in any repository.

**Skills included:**

| Skill | Description |
|-------|-------------|
| `update-pr` | Sync PR branch with its base branch: fetch → rebase/merge → resolve conflicts → push |
| `cso` | Chief Security Officer audit: secrets archaeology, dependency supply chain, CI/CD, infra, webhooks, LLM/AI security, skill supply chain, OWASP Top 10, STRIDE, and mobile app security (iOS/Android). Detects Python/FastAPI, React/React Native, Swift, Kotlin. Daily (8/10 gate) and `--comprehensive` (2/10) modes |

## Installation

### Claude Code

Run the setup script. It validates prerequisites, configures tokens, and guides you through plugin installation:

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

This validates prerequisites, adds the `SIROC-Labs/cortex` marketplace (remote by default, no clone needed; pass `--dev` to use your local working copy), and installs `cortex-workflow` (from `siroc-cortex`) and its required `superpowers` dependency (from the official `openai-curated` catalog) with `codex plugin add`. The MCP servers declared by the plugin load automatically. Restart Codex afterwards; no `/plugins` step needed.

See [.codex/INSTALL.md](.codex/INSTALL.md) for manual install and detailed instructions.

### All agents

```bash
bash setup.sh --all
```

Installs for every supported agent in one run. Each agent is installed independently. If one fails (or its CLI isn't installed) the others still proceed, and a per-agent success/failure summary is printed at the end. Add `--dev` to source from your local clone.

### What the Script Does

**GitHub CLI**: Checks that `gh` is installed, authenticated, and has access to the private `SIROC-Labs/cortex` repo.

**Git SSH**: Tests SSH authentication to GitHub. If you use SSH keys, it offers to configure the HTTPS-to-SSH rewrite:

```bash
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

**Asana token**: Looks for `ASANA_PERSONAL_ACCESS_TOKEN` in your environment. If missing, prompts you to paste one (from https://app.asana.com/0/my-apps) and writes it to your profile.

**GitHub token**: Checks for `GITHUB_TOKEN` or `GH_TOKEN` for marketplace auto-updates. Can extract one from `gh auth token` if not set.

**Plugin installation**: Once all prerequisites pass, the script asks whether to install all plugins now or only register the marketplace so you can pick plugins yourself (Claude Code and Codex; OpenCode has no marketplace, so its plugins always install directly):
- Claude Code: installs the marketplace, `cortex-workflow`, and `dev-toolkit` (user scope) via the `claude` CLI (dependencies `feature-dev` and `superpowers` auto-resolve); falls back to printing `/plugin` commands if the CLI isn't on PATH
- OpenCode: merges the plugin configuration into `opencode.json` and clears the cache (the adapter registers both cortex-workflow and dev-toolkit skills)
- Codex: adds the `SIROC-Labs/cortex` marketplace (remote by default; `--dev` for a local clone) and installs `cortex-workflow`, `dev-toolkit` (from `siroc-cortex`) and `superpowers` (from `openai-curated`) via `codex plugin add`; declared MCP servers load automatically from the plugin manifest

> If the script added tokens to your shell profile, reload your terminal (`source ~/.zshrc`) before continuing.

## Updating

### Claude Code

```
/plugin marketplace update siroc-cortex
/plugin update cortex-workflow@siroc-cortex
/plugin update dev-toolkit@siroc-cortex
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
codex plugin add cortex-workflow@siroc-cortex
codex plugin add dev-toolkit@siroc-cortex
```

Restart Codex afterwards. For a `--dev` install, `git pull` your clone and re-run the `codex plugin add` commands instead; `marketplace upgrade` only applies to the remote Git marketplace.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License

Proprietary - SIROC Team
