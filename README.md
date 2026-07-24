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
| **Solution design** | Turn the validated problem into a complete, agreed definition of what to build | `create-prd`, `create-spec` |
| **Breakdown & estimation** | Break the solution into tasks with a real effort estimate | `milestone-breakdown`, `task-breakdown`, `submit-breakdown`, `refine-tasks` |
| **Development** | A workflow that enforces delivery discipline and gets more out of the coding agent | `start-task`, `implement-feature`, `fix-bug` |
| **QA & release** | Validate the build, generate verifiable evidence, ship a documented release | `web-qa`, `mobile-qa`, `backend-qa`, `pre-ship-check`, `ship-it`, `create-pr` |

Each phase has a gate, so work only moves forward once it has produced what the next phase needs: the problem validated, the PRD written, the plan estimated, the evidence collected.

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

Apache License 2.0 — see [LICENSE](LICENSE).
