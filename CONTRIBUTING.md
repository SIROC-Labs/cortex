# Contributing to SIROC Cortex

## One-time setup

1. Clone the repo
2. Run the setup script in **developer mode** (`--dev`) so the install points at your local clone instead of the remote repo — validates GitHub CLI auth, SSH config, and sets `ASANA_PERSONAL_ACCESS_TOKEN` in your shell profile:
   ```bash
   bash setup.sh --dev              # Claude Code
   bash setup.sh --opencode --dev   # OpenCode
   bash setup.sh --codex --dev      # Codex
   ```
   Without `--dev` the script does the normal install from the remote `SIROC-Labs/cortex` repo (no clone needed) — that's the end-user path.
3. The script completes installation for you. To do it manually instead:
   - **Claude Code:**
     ```
     /plugin marketplace add /path/to/cortex
     /plugin install asana-workflow@siroc-cortex
     /plugin install dev-toolkit@siroc-cortex
     ```
   - **OpenCode:** Point your `opencode.json` at the local clone:
     ```json
     { "plugin": ["/absolute/path/to/cortex"] }
     ```
   - **Codex:** Add the local clone as the marketplace (use the repo root, which contains `.agents/plugins/marketplace.json`), then install the plugins:
     ```bash
     codex plugin marketplace add /path/to/cortex
     codex plugin add asana-workflow@siroc-cortex
     codex plugin add dev-toolkit@siroc-cortex
     codex plugin add superpowers@openai-curated
     ```
     `superpowers` comes from the official `openai-curated` catalog, not from `siroc-cortex`.

## Development loop

Skills are Markdown files — no build step. After editing a file, start a new conversation and changes are picked up automatically. If you're already in a session:
- **Claude Code:** `/plugin reload <plugin>` (the plugin you edited)
- **OpenCode:** Restart the agent session
- **Codex:** Restart the agent session

## Editing an existing skill

Skills live at `plugins/<plugin>/skills/<name>/SKILL.md`, where `<plugin>` is the plugin folder the skill belongs to. Edit the file directly.

Keep SKILL.md under ~100 lines. For larger reference content, create a `references/` subdirectory and link to it from SKILL.md.

## Adding a new skill

1. Choose the plugin folder that fits the skill's purpose (browse `plugins/`; each plugin's `CLAUDE.md` describes its scope).
2. Create `plugins/<plugin>/skills/<name>/SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: skill-name
   description: one-line description of when this skill triggers
   ---
   ```
3. Start a new Claude Code or Codex session, run `/plugin reload <plugin>` in Claude Code, or restart OpenCode to test

## Before opening a PR

Skill changes must include evidence that the change improves behavior. PRs without evaluation should not be merged.

Accepted forms of evidence:
- Before/after examples showing improved outputs
- Specific cases where the old behavior failed and the new one handles them correctly
- Metrics or observations from real usage

## Git workflow

- Never commit directly to `main`
- Create a feature branch, make your changes, open a PR to `main`
- Use conventional commits: `type(scope): description`
  - Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`, `perf`

## Versioning

Never edit version numbers in `plugin.json`, `marketplace.json`, or `package.json` manually. Version bumps are done via GitHub Actions:

**Actions → Bump Plugin Version → Run workflow**

| Input | Description |
|-------|-------------|
| `plugin` | Plugin folder name (e.g. `asana-workflow`) |
| `level` | `patch` · `minor` · `major` |

- `patch` — bug fixes, copy tweaks, non-breaking skill changes
- `minor` — new skills, backwards-compatible changes
- `major` — breaking changes, removed or renamed skills
