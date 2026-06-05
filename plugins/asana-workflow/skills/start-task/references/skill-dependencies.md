# Skill Dependencies

`start-task` orchestrates external skills that are **not bundled** with the `asana-workflow` plugin. They are mandatory and must be installed alongside `asana-workflow` before start-task can route work correctly.

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
- **Used for:** Brainstorming, systematic debugging, TDD, OpenCode feature implementation, and Codex feature implementation when a usable spec and implementation plan are present
- **Install:**
  ```
  /plugin install superpowers@claude-plugins-official
  ```

For OpenCode, run `bash setup.sh --opencode`; it writes the superpowers plugin
entry alongside asana-workflow. For Codex, run `bash setup.sh --codex`; it
registers the `siroc-cortex` marketplace and runs `codex plugin add` to install
`asana-workflow` (from `siroc-cortex`) and `superpowers` (from `openai-curated`)
automatically — no `/plugins` step required.

For Claude Code, `feature-dev` and `superpowers` are declared in the plugin
metadata and should be auto-installed when installing `asana-workflow`, provided
the `claude-plugins-official` marketplace is available and cross-marketplace
dependencies are allowed by this marketplace.

## Required MCP Servers

The QA skills require the MCP servers declared by the plugin:

- `mobile-mcp`
- `chrome-devtools`

Both are declared in `plugins/asana-workflow/.mcp.json` — the single source of
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
not available for OpenCode; route feature implementation to
`superpowers:subagent-driven-development`.

### If running under Codex

Check the available skill list for `superpowers`. If it is not available, stop
and tell the user to install it: `codex plugin add superpowers@openai-curated`
(or re-run `bash setup.sh --codex`), then restart Codex.

## Dependency Check at Start-Task Launch (Step 0)

At the very beginning of start-task (before fetching the Asana task), check which routing path may be needed and confirm the relevant plugin is installed.

**Missing dependencies are hard blockers across all runtimes.** Stop, warn the user (⚠️ the plugin/server is required but doesn't appear to be installed), give them the recovery command from the table below, and tell them to install it, restart the agent, then re-run start-task. Do not continue inline.

| Missing | Claude Code | OpenCode | Codex |
|---|---|---|---|
| `superpowers` | `/plugin install superpowers@claude-plugins-official` | `bash setup.sh --opencode` | `bash setup.sh --codex` or `codex plugin add superpowers@openai-curated` |
| `feature-dev` | `/plugin install feature-dev@claude-plugins-official` | n/a — see below | n/a — see below |
| Declared MCP servers | Reinstall `asana-workflow` | `bash setup.sh --opencode` | Reinstall or reload `asana-workflow` |

**feature-dev under OpenCode:** DOES NOT EXIST. Route feature implementation to
`superpowers:subagent-driven-development`.

**feature-dev under Codex:** The Claude plugin dependency is not a Codex dependency. For
Codex feature implementation, inspect the Asana notes, comments, subtasks, and
attachments for both a usable spec and a usable implementation plan:

- **Spec present:** concrete behavior, acceptance criteria, UX/API contract, or
  explicit constraints.
- **Plan present:** ordered steps, affected files/modules, migration notes, or
  test strategy.

If both are present, route implementation to
`superpowers:subagent-driven-development` and include the spec and plan excerpts
in the handoff. This is the Codex development skill for executing from a spec
and plan. If either is missing, do not invoke a feature-dev substitute; implement
inline in the current Codex session, while keeping the normal QA and ship-it
steps.

## Bundled Skills (No Installation Needed)

These skills are included in the `asana-workflow` plugin itself:

| Skill | Purpose |
|---|---|
| `asana-workflow:asana-api` | All Asana API calls |
| `asana-workflow:git-check` | Git state validation |
| `asana-workflow:pre-ship-check` | Readiness gate |
| `asana-workflow:work-summary` | Session summary |
| `asana-workflow:create-pr` | PR creation |
| `asana-workflow:ship-it` | Shipping orchestrator |
| `asana-workflow:web-qa` | Web QA investigation & verification |
| `asana-workflow:mobile-qa` | Mobile QA investigation & verification |
