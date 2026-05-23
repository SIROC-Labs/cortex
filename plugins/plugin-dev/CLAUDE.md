# plugin-dev — Development Guide

## Purpose

Meta-tooling for managing skills in this repo. Not an end-user workflow plugin — it watches skill authoring activity and enforces coupling discipline.

## Plugin Structure

```
plugin-dev/
├── CLAUDE.md                    ← you are here
├── .claude-plugin/
│   └── plugin.json
├── hooks/
│   └── hooks.json               ← PostToolUse hook on Write|Edit
├── references/
│   └── skill-graph.md           ← auto-generated, do not edit
├── scripts/
│   └── analyze-skill-refs.sh    ← hook implementation
└── skills/
    └── skill-graph/
        └── SKILL.md             ← /skill-graph command
```

## How the Hook Works

Fires on every `Write` or `Edit` tool call. The script:
1. Checks if the file path matches `*/skills/*/SKILL.md`
2. Scans all SKILL.md files for whole-word mentions of other skill names
3. Compares against a cached baseline at `/tmp/cortex-skill-refs-cache.txt`
4. If new references detected → emits a `systemMessage` challenging the user
5. Regenerates `references/skill-graph.md` unconditionally

## False Positives

The script uses `grep -qw` (whole-word match). Skill names that are also common words may produce spurious edges in the graph. This is intentional — a soft challenge is better than a missed coupling. The user can dismiss with "yes, intentional."

## Adding Skills to This Plugin

Follow the same conventions as `asana-workflow`: each skill in `skills/<name>/SKILL.md` with YAML frontmatter.
