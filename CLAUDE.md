# CLAUDE.md

This file provides guidance to coding agents (Claude Code, OpenCode, etc.) when working with code in this repository. Also used as contributor reference.

## Git Workflow

- `main` is the only long-lived branch
- Every change must be on a new feature branch with a PR back to `main`
- Never commit directly to `main`

## Commits

Use conventional commits: `type(scope): description`
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`, `perf`

## Environment Variables

Required in `~/.zshrc` (or set by `setup.sh`):
- `ASANA_PERSONAL_ACCESS_TOKEN` — Asana REST API access
- `GITHUB_TOKEN` or `GH_TOKEN` — marketplace auto-updates (optional)

## Plugin Versioning

Do not manually edit version fields in `plugin.json`, `marketplace.json`, or `package.json`. Version bumps are done via the GitHub Actions workflow (`bump-version.yml`): Actions → Bump Plugin Version → choose plugin and semver level (patch/minor/major).

## Skill Development

Each skill lives at `plugins/<plugin>/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `version`, `description`). Keep SKILL.md under ~100 lines; move larger docs to a `references/` subdirectory and link from SKILL.md. See `plugins/asana-workflow/CLAUDE.md` for the full plugin development guide.

## Multi-Agent Support

This plugin supports both Claude Code and OpenCode:

- **Claude Code** — install via the official plugin marketplace (`/plugin install asana-workflow@siroc-cortex`)
- **OpenCode** — install via `setup.sh --opencode` or by adding to `opencode.json` (see `.opencode/INSTALL.md`)

Skills are agent-agnostic and work with both runtimes. OpenCode gets a thin adapter at `.opencode/plugins/asana-workflow.js` that handles skill registration, tool name mapping, and bootstrap injection.

## Behavior

Don't add comments, docstrings, or features beyond what was asked.
