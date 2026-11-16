# product Plugin — Development Guide

Product definition skills: turn raw material into a one-pager, a PRD, or a
technical spec. The plugin is standalone and installs without any other plugin.

## Plugin Structure

```
product/
├── CLAUDE.md              ← you are here
├── .claude-plugin/
│   └── plugin.json        ← plugin manifest (name, version) — skills are auto-discovered
├── .codex-plugin/
│   └── plugin.json        ← Codex manifest
├── references/
│   └── runtime-bindings.md ← capability → skill mapping per runtime (READ_TASK, RUN_INTERVIEW)
└── skills/
    ├── product-one-pager/ ← One-pager/brief generation & review against a senior-PM + product-owner bar + references/
    ├── create-prd/        ← PRD generation from a task URL, Notion, Figma, local files, or any URL + references/
    └── create-spec/       ← Technical spec authoring from any source (interview-driven → docs/cortex/specs/) + references/
```

Each skill follows: `skills/<name>/SKILL.md` + optional `references/` subdirectory.
Skills are auto-discovered from `skills/` — there is no `skills` array in `plugin.json`.

## Skill Dependency Graph

```
product-one-pager      (generate or review a product one-pager/brief)
  └── → hands off to create-prd (optional: turn the one-pager into a full PRD)

create-prd             (reads sources, interviews user, writes PRD)
  ├── READ_TASK          (optional: fetch a task when a task URL is a source)
  └── (external MCPs)    (Notion, Figma, Google Drive, WebFetch — source ingestion)

create-spec            (reads any source, interviews user, writes docs/cortex/specs/…md)
  ├── READ_TASK          (optional: fetch a task when a task URL is a source)
  ├── RUN_INTERVIEW      (drives the interview phase)
  └── (external MCPs)    (Notion, Figma, Drive, Loom, WebFetch — source ingestion)
```

## External Dependencies

None are required. Skills never name a skill from another plugin: a need that
another plugin fulfils is a capability, resolved through
`references/runtime-bindings.md`, with a fallback when the binding is missing.

## Development Workflow

### Adding a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `version`, `description`)
2. Add optional `references/` files and reference them from SKILL.md
3. **Update this CLAUDE.md** — add the skill to the Plugin Structure diagram and the dependency graph
4. **Update the repo `README.md`** if the skill belongs in the lifecycle table

### Reloading after changes

```bash
/plugin reload product
```

## Versioning

Do not manually edit the `version` field in `plugin.json` or `marketplace.json`.
Version bumps go through the GitHub Actions workflow (`bump-version.yml`).
