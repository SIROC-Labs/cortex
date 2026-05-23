---
name: skill-graph
version: 1.0.0
description: >
  Regenerate the skill dependency diagram and audit cross-skill coupling across all plugins.
  Triggered automatically by the PostToolUse hook after any SKILL.md is written or edited.
  Manually invoke to audit all skills or evaluate a single skill's dependencies.
argument-hint: "[skill-name]"
---

# Skill Graph

Builds and presents a live dependency map of cross-skill references. When called with a skill
name, evaluates whether that skill's outbound references are justified and challenges the user
on any that look unnecessary.

---

## Step 1: Determine Mode

Check `$ARGUMENTS` for a skill name.

- **No arguments** → Full Audit mode (Steps 2–5)
- **Skill name provided** (e.g., `fix-bug`) → Single Skill mode (Steps 2–3, then Steps 6–7)

---

## Step 2: Regenerate the Diagram

Run the analysis script to scan all `plugins/*/skills/*/SKILL.md` files and rebuild the graph:

```bash
CLAUDE_PROJECT_DIR="$(pwd)" bash plugins/plugin-dev/scripts/analyze-skill-refs.sh <<'EOF'
{"tool_name": "Write", "tool_input": {"file_path": "plugins/asana-workflow/skills/start-task/SKILL.md"}}
EOF
```

Then read the updated diagram:

```bash
cat plugins/plugin-dev/references/skill-graph.md
```

---

## Step 3: Present the Diagram

Display the Mermaid diagram to the user with a brief header:

> **Skill Dependency Graph** — `plugins/plugin-dev/references/skill-graph.md`
>
> _(paste diagram here)_

---

## Full Audit Mode (no arguments)

### Step 4: Identify Coupling Hotspots

From the diagram, count inbound edges per skill (how many skills reference it) and outbound edges (how many skills it references).

Present a summary table:

| Skill | Referenced by (inbound) | References (outbound) |
|---|---|---|
| start-task | N | N |
| … | … | … |

Flag any skill with **outbound ≥ 4** as a coupling hotspot — it may be doing too much orchestration.

### Step 5: Ask the User

> "Does anything in this diagram look unintentional or surprising? I can evaluate any specific skill's references in depth — just name it."

If the user names a skill, continue to Steps 6–7 with that skill. Otherwise stop.

---

## Single Skill Mode (argument provided or user named a skill)

### Step 6: Extract the Skill's Outbound References

From the diagram, collect every edge where `<skill-name> --> <other>`.

For each outbound reference, read the skill's SKILL.md and find where exactly it mentions the referenced skill — is it:

- **Explicit invocation**: the skill directly calls or hands off to the other (e.g., "invoke `ship-it`", "route to `fix-bug`")
- **Shared context mention**: the skill documents a relationship but doesn't invoke it
- **Incidental mention**: the skill name appears in an example, comment, or reference that isn't a real dependency

### Step 7: Challenge Each Dependency

For each **explicit invocation**, ask the user:

> "`<skill-name>` invokes `<other-skill>`. Is this dependency necessary?
>
> Consider:
> - Could `<skill-name>` complete its job without delegating to `<other-skill>`?
> - Is the delegation a hard requirement, or a convenience that could be inlined?
> - Does this coupling make either skill harder to use independently?"

Wait for the user's response per dependency. If they confirm it's needed, move on. If they say it's not needed, ask whether to remove the reference now.

**Incidental or shared-context mentions** — do not challenge. Note them as non-coupling references.

### Step 8: Recap

Summarize:

> **`<skill-name>` dependency review:**
> - Confirmed necessary: `fix-bug → start-task` _(handoff after fix is done)_
> - Flagged for removal: _(none / list any)_
> - Incidental mentions (not real deps): _(list if any)_
