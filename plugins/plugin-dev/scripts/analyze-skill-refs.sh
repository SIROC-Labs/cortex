#!/bin/bash
# Analyzes cross-skill references when a SKILL.md is written or edited.
# Fires as a PostToolUse hook on Write|Edit events.
# Outputs a systemMessage challenging the user if new dependencies appear.
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

# Only process SKILL.md files inside a skills/ directory
case "$file_path" in
  */skills/*/SKILL.md) ;;
  *) exit 0 ;;
esac

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
if [[ -z "$PROJECT_DIR" ]]; then
  PROJECT_DIR=$(git -C "$(dirname "$file_path")" rev-parse --show-toplevel 2>/dev/null || pwd)
fi

GRAPH_FILE="$PROJECT_DIR/plugins/plugin-dev/references/skill-graph.md"
CACHE_FILE="/tmp/cortex-skill-refs-cache.txt"
edited_skill=$(basename "$(dirname "$file_path")")

# Collect all skill names from the plugins directory tree
skill_names=()
while IFS= read -r sp; do
  skill_names+=("$(basename "$(dirname "$sp")")")
done < <(find "$PROJECT_DIR/plugins" -name "SKILL.md" -path "*/skills/*" 2>/dev/null | sort)

if [[ ${#skill_names[@]} -eq 0 ]]; then
  exit 0
fi

# Build reference graph: "from->to" one per line
tmp_graph=$(mktemp /tmp/skill-graph-XXXXXX.txt)
while IFS= read -r sp; do
  from=$(basename "$(dirname "$sp")")
  for to in "${skill_names[@]}"; do
    if [[ "$to" != "$from" ]] && grep -qw "$to" "$sp" 2>/dev/null; then
      echo "$from->$to" >> "$tmp_graph"
    fi
  done
done < <(find "$PROJECT_DIR/plugins" -name "SKILL.md" -path "*/skills/*" 2>/dev/null | sort)

# Detect new references for the skill that was just edited
new_refs=()
while IFS= read -r ref; do
  to="${ref##*->}"
  if ! grep -qxF "$ref" "$CACHE_FILE" 2>/dev/null; then
    new_refs+=("$to")
  fi
done < <(grep "^${edited_skill}->" "$tmp_graph" 2>/dev/null || true)

# Persist graph as new cache baseline
cp "$tmp_graph" "$CACHE_FILE" 2>/dev/null || true

# Regenerate Mermaid diagram
mkdir -p "$(dirname "$GRAPH_FILE")"
{
  printf '# Skill Reference Graph\n\n'
  printf '> Auto-generated — do not edit manually.\n'
  printf '> Last updated: %s\n\n' "$(date '+%Y-%m-%d %H:%M')"
  printf '```mermaid\ngraph TD\n'
  if [[ -s "$tmp_graph" ]]; then
    while IFS= read -r ref; do
      from="${ref%%->*}"
      to="${ref##*->}"
      printf '    %s --> %s\n' "$from" "$to"
    done < <(sort -u "$tmp_graph")
  fi
  printf '```\n'
} > "$GRAPH_FILE"

rm -f "$tmp_graph"

# Emit systemMessage
if [[ ${#new_refs[@]} -gt 0 ]]; then
  refs_str=$(IFS=', '; echo "${new_refs[*]}")
  cat <<MSG
{"systemMessage": "SKILL DEPENDENCY DETECTED: '${edited_skill}' now references: ${refs_str}. Invoke the /skill-graph skill now to regenerate the full dependency diagram and present it to the user. Then challenge the user: Is this cross-skill dependency truly necessary? Could this logic live within '${edited_skill}' itself?"}
MSG
else
  cat <<MSG
{"systemMessage": "Invoke the /skill-graph skill now to regenerate the dependency diagram and confirm no unintended references were introduced in '${edited_skill}'."}
MSG
fi
