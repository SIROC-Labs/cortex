# dev-toolkit Plugin — Development Guide

A home for independent, reusable development utilities. Skills here are
self-contained — they don't depend on any particular workflow or external
service, and can be used in any repository.

## Plugin Structure

```
dev-toolkit/
├── CLAUDE.md              ← you are here
├── .claude-plugin/
│   └── plugin.json        ← plugin manifest (name, version) — skills are auto-discovered
└── skills/
    ├── update-pr/         ← Sync a PR branch with its base (fetch → rebase/merge → resolve → push)
    └── cso/               ← Chief Security Officer audit (secrets, deps, CI/CD, OWASP, STRIDE, LLM/AI) + references/audit-phases.md
```

Each skill follows: `skills/<name>/SKILL.md` + optional `references/` subdirectory.
Skills are auto-discovered from `skills/` — there is no `skills` array in `plugin.json`.

## External Dependencies

Skills in this plugin are self-contained and do not depend on other plugins.
Cross-plugin skill references should point *into* this plugin, not out of it —
that's what keeps these utilities independent.

## Development Workflow

### Adding a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `version`, `description`)
2. Add optional `references/` files and reference them from SKILL.md
3. **Update this CLAUDE.md** — add the skill to the Plugin Structure diagram above
4. **Update the repo `README.md`** — add a row to the dev-toolkit skill table if user-invokable

### Reloading after changes

```bash
/plugin reload dev-toolkit
```

## Versioning

Do not manually edit the `version` field in `plugin.json` or `marketplace.json`.
Version bumps go through the GitHub Actions workflow (`bump-version.yml`).
