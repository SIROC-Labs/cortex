# Skill Dependencies

`start-task` orchestrates external skills that are **not bundled** with the `cortex-workflow` plugin. They are mandatory and must be installed alongside `cortex-workflow` before start-task can route work correctly.

## Required External Skills

### Claude Code: `feature-dev:feature-dev`
- **Plugin:** `feature-dev@claude-plugins-official`
- **Used for:** Routing Feature Request, Tech Debt, and all non-bug task categories (Step 10)
- **Install:**
  ```
  /plugin install feature-dev@claude-plugins-official
  ```

### All runtimes: `superpowers`
- **Claude Code plugin:** `superpowers@claude-plugins-official`
- **OpenCode plugin:** `superpowers@git+https://github.com/obra/superpowers.git`
- **Codex plugin:** `superpowers@openai-curated` (the official catalog; not shipped in `siroc-cortex`)
- **Used for:** Design brainstorming, systematic debugging, TDD, and implementation-plan execution (`subagent-driven-development`) — see `plugins/cortex-workflow/references/runtime-bindings.md` for the capability mapping per runtime
- **Install:**
  ```
  /plugin install superpowers@claude-plugins-official
  ```

For OpenCode, run `bash setup.sh --opencode`; it writes the superpowers plugin
entry alongside cortex-workflow. For Codex, run `bash setup.sh --codex`; it
registers the `siroc-cortex` marketplace and runs `codex plugin add` to install
`cortex-workflow` (from `siroc-cortex`) and `superpowers` (from `openai-curated`)
automatically — no `/plugins` step required.

For Claude Code, `feature-dev` and `superpowers` are declared in the plugin
metadata and should be auto-installed when installing `cortex-workflow`, provided
the `claude-plugins-official` marketplace is available and cross-marketplace
dependencies are allowed by this marketplace.

## Required MCP Servers

The QA skills require the MCP servers declared by the plugin:

- `mobile-mcp`
- `chrome-devtools`

Both are declared in `plugins/cortex-workflow/.mcp.json` — the single source of
truth shared by all runtimes. Claude Code and Codex load them automatically from
the plugin manifest; for OpenCode the adapter registers them at load time.

## How to Check If Dependencies Are Installed

Before routing in Step 10, verify whether the relevant external skill is available in the current runtime. Missing dependencies are blocking; do not continue inline.

To check installed plugins:

### If running under Claude Code

```bash
# List installed plugins — match JSON keys like "feature-dev@..." or "superpowers@..."
cat ~/.claude/plugins/installed_plugins.json | grep -E '"feature-dev|"superpowers'
```

### If running under OpenCode

Check `opencode.json` for the `plugin` array. `superpowers` should appear as
`"superpowers@git+https://github.com/obra/superpowers.git"`. `feature-dev` is
not available for OpenCode — non-bug routing is handled by `implement-feature`
via the runtime-bindings table.

### If running under Codex

Check the available skill list for `superpowers`. If it is not available, stop
and tell the user to install it: `codex plugin add superpowers@openai-curated`
(or re-run `bash setup.sh --codex`), then restart Codex.

## Dependency Check at Start-Task Launch (Step 0)

At the very beginning of start-task (before fetching the task), check which routing path may be needed and confirm the relevant plugin is installed.

**Missing dependencies are hard blockers across all runtimes.** Stop, warn the user (⚠️ the plugin/server is required but doesn't appear to be installed), give them the recovery command from the table below, and tell them to install it, restart the agent, then re-run start-task. Do not continue inline.

| Missing | Claude Code | OpenCode | Codex |
|---|---|---|---|
| `superpowers` | `/plugin install superpowers@claude-plugins-official` | `bash setup.sh --opencode` | `bash setup.sh --codex` or `codex plugin add superpowers@openai-curated` |
| `feature-dev` | `/plugin install feature-dev@claude-plugins-official` | n/a — see below | n/a — see below |
| Declared MCP servers | Reinstall `cortex-workflow` | `bash setup.sh --opencode` | Reinstall or reload `cortex-workflow` |

**feature-dev under OpenCode/Codex:** DOES NOT EXIST — `feature-dev` appears only
in the Claude Code cells of the bindings table. Non-bug routing is owned by
`cortex-workflow:implement-feature`, which resolves the capability to enter at
(`CREATE_PLAN`, `EXECUTE_PLAN`, `EXECUTE_INLINE`) and its per-runtime binding —
detecting attached implementation plans along the way — via
`plugins/cortex-workflow/references/runtime-bindings.md`.

## Bundled Skills (No Installation Needed)

These skills are included in the `cortex-workflow` plugin itself:

| Skill | Purpose |
|---|---|
| `cortex-workflow:task-manager` | All task operations (routed to the active provider) |
| `cortex-workflow:git-check` | Git state validation |
| `cortex-workflow:pre-ship-check` | Readiness gate |
| `cortex-workflow:work-summary` | Session summary |
| `cortex-workflow:create-pr` | PR creation |
| `cortex-workflow:ship-it` | Shipping orchestrator |
| `cortex-workflow:web-qa` | Web QA investigation & verification |
| `cortex-workflow:mobile-qa` | Mobile QA investigation & verification |
| `cortex-workflow:backend-qa` | Backend (API/service) QA investigation & verification |
