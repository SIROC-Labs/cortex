# Contributing to SIROC Cortex

## One-time setup

1. Clone the repo
2. Run the setup script — validates GitHub CLI auth, SSH config, and sets `ASANA_PERSONAL_ACCESS_TOKEN` in your shell profile:
   ```bash
   bash setup.sh
   ```
3. Load the plugin:
   - **Claude Code:** Add the local marketplace and install:
     ```
     /plugin marketplace add /path/to/cortex
     /plugin install asana-workflow@siroc-cortex
     ```
   - **OpenCode:** Point your `opencode.json` at the local clone:
     ```json
     { "plugin": ["/absolute/path/to/cortex"] }
     ```

## Development loop

Skills are Markdown files — no build step. After editing a file, start a new conversation and changes are picked up automatically. If you're already in a session:
- **Claude Code:** `/plugin reload asana-workflow`
- **OpenCode:** Restart the agent session

## Editing an existing skill

Skills live at `plugins/asana-workflow/skills/<name>/SKILL.md`. Edit the file directly.

Keep SKILL.md under ~100 lines. For larger reference content, create a `references/` subdirectory and link to it from SKILL.md.

## Adding a new skill

1. Create `plugins/asana-workflow/skills/<name>/SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: skill-name
   description: one-line description of when this skill triggers
   ---
   ```
2. Start a new Claude Code session or run `/plugin reload asana-workflow` to test

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
