---
name: skill-graph
version: 1.0.0
description: Regenerate the skill dependency diagram and review cross-skill coupling across all plugins in this repo.
---

# skill-graph

Use to regenerate the skill reference graph or audit cross-skill coupling.

## What This Skill Does

1. Scans all `plugins/*/skills/*/SKILL.md` files for references to other skills
2. Rebuilds `plugins/plugin-dev/references/skill-graph.md` with an up-to-date Mermaid diagram
3. Reports which skills are most-referenced (high coupling) and flags any unexpected dependencies

## When to Use

- After adding or removing a skill, to refresh the diagram
- When reviewing the plugin architecture to spot over-coupled skills
- After merging a branch that adds new skill references

## Steps

1. Run the analysis script:
   ```bash
   CLAUDE_PROJECT_DIR="$(pwd)" bash plugins/plugin-dev/scripts/analyze-skill-refs.sh <<'EOF'
   {"tool_name": "Write", "tool_input": {"file_path": "plugins/asana-workflow/skills/start-task/SKILL.md"}}
   EOF
   ```
2. Read `plugins/plugin-dev/references/skill-graph.md` and display the diagram to the user
3. Identify skills with many outbound references — these are coupling hotspots
4. Ask the user if any dependency looks unintentional or could be inlined

## Hook Behavior

The `PostToolUse` hook in this plugin fires automatically whenever a `SKILL.md` is written or edited. It:
- Detects if the edit introduced a **new** cross-skill reference
- Challenges the user: "Is this dependency truly necessary?"
- Updates the diagram silently if no new references appear

The challenge questions to ask the user:
- Could this logic live within the skill itself instead of delegating?
- Does invoking another skill create a dependency that makes both harder to change?
- Is the referenced skill truly a prerequisite, or just a convenience?

## Reference

Diagram lives at: `plugins/plugin-dev/references/skill-graph.md`
Hook script: `plugins/plugin-dev/scripts/analyze-skill-refs.sh`
