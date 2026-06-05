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

Do not manually edit version fields in `plugin.json`, `marketplace.json`, `package.json`, or `.codex-plugin/plugin.json`. Version bumps are done via the GitHub Actions workflow (`bump-version.yml`): Actions → Bump Plugin Version → choose plugin and semver level (patch/minor/major). The workflow keeps all of a plugin's manifests in lockstep.

## Skill Development

Each skill lives at `plugins/<plugin>/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `version`, `description`). Keep SKILL.md under ~100 lines; move larger docs to a `references/` subdirectory and link from SKILL.md. See `plugins/asana-workflow/CLAUDE.md` for the full plugin development guide.

### Skill Design Principles

- **External skills go through an interface, never invoked directly.** A skill must not name a skill from another plugin in its prose. Express the need as a capability (e.g. `CREATE_PLAN`, `APPLY_TDD`) and resolve it through the bindings table (`plugins/asana-workflow/references/runtime-bindings.md`). Skills bundled in the same plugin may invoke each other directly — they ship together, so there is no implementation to vary.
- **Skills should not know about each other unless strictly necessary.** Callers name their callees; callees never name their callers — finish by returning control to "the invoking workflow" generically, so the skill also works standalone. Do not reference another skill's step numbers, internals, or structure: every such reference breaks silently when the other file changes.
- **Skills are runtime-agnostic by default.** Do not reference a specific client (Claude Code, OpenCode, Codex) or its tools, commands, or paths in skill prose unless the skill exists solely for that client. Per-runtime differences belong in the bindings table or the client adapter (e.g. `.opencode/plugins/asana-workflow.js`), never inline in the skill.

## Multi-Agent Support

The `asana-workflow` plugin supports Claude Code, OpenCode, and Codex (`dev-toolkit` is Claude Code-only for now):

- **Claude Code** — `bash setup.sh` or `/plugin install asana-workflow@siroc-cortex`
- **OpenCode** — `bash setup.sh --opencode` (see `.opencode/INSTALL.md`)
- **Codex** — `bash setup.sh --codex` (see `.codex/INSTALL.md`)

Skills are agent-agnostic and work with all runtimes. Per-runtime skill resolution goes through `plugins/asana-workflow/references/runtime-bindings.md`; OpenCode additionally gets a thin adapter at `.opencode/plugins/asana-workflow.js` that handles skill registration, MCP registration, tool name mapping, and bootstrap injection.

## Behavior

Don't add comments, docstrings, or features beyond what was asked.
