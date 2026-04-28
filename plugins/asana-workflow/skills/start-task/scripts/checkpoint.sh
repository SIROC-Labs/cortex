#!/usr/bin/env bash
#
# checkpoint.sh — maintain the start-task checkpoint file silently
#
# Usage:
#   checkpoint.sh init        <gid> <asana_url>
#   checkpoint.sh start       <gid> "<step>"
#   checkpoint.sh complete    <gid> "<step>" "<comment>" [auto]
#   checkpoint.sh skip        <gid> "<step>" "<reason>"
#   checkpoint.sh block       <gid> "<step>" "<reason>"
#   checkpoint.sh set         <gid> <field> "<value>"
#   checkpoint.sh append-note <gid> "<text>"
#   checkpoint.sh read        <gid> ["<step>"]
#   checkpoint.sh delete      <gid>
#
# <step> is the full step label as shown in the Steps table, e.g. "3. Validate
# Sprint-Readiness" or "QA: Investigate Bug". The script matches by exact
# column text.
#
# <auto> is "yes" or "no" (default "yes"). "no" for rows that needed operator
# input (6a, 6b, 3 when it asked).
#
# Exits 0 on success, 1 on argument error, 2 on file-not-found, 3 on row-not-
# found.

set -euo pipefail

# User-global location, mirroring the convention used by log-task's project
# registry cache (~/.claude/asana-workflow/<project-key>.json). CWD-independent,
# survives worktree entry/exit, not subject to accidental git commits.
CHECKPOINTS_DIR="${HOME}/.claude/asana-workflow/checkpoints"

now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

file_for() {
  printf '%s/%s.md\n' "$CHECKPOINTS_DIR" "$1"
}

require_file() {
  local f="$1"
  [[ -f "$f" ]] || { echo "checkpoint not found: $f" >&2; exit 2; }
}

# Escape special chars for use in a sed replacement (RHS of s|...|...|).
sed_escape() {
  printf '%s' "$1" | sed -e 's/[|&\\]/\\&/g'
}

# Reject input that contains pipes or newlines (would break the markdown table).
validate_plain() {
  local s="$1"
  case "$s" in
    *"|"*|*$'\n'*)
      echo "invalid input: contains '|' or newline: $s" >&2
      exit 1
      ;;
  esac
}

set_frontmatter() {
  local file="$1" field="$2" value="$3"
  validate_plain "$value"
  local esc; esc=$(sed_escape "$value")
  sed -i.bak "s|^${field}: .*\$|${field}: \"${esc}\"|" "$file"
  rm -f "${file}.bak"
}

touch_last_updated() {
  set_frontmatter "$1" "last_updated" "$(now)"
}

# Replace the row whose first column matches <step>. New row string is passed
# verbatim. Aborts (exit 3) if no matching row exists.
replace_row() {
  local file="$1" step="$2" new_row="$3"
  if ! grep -q "^| ${step} |" "$file"; then
    echo "row not found: $step" >&2
    exit 3
  fi
  local esc_step esc_new
  esc_step=$(sed_escape "$step")
  esc_new=$(printf '%s' "$new_row" | sed -e 's/[&\\]/\\&/g')
  awk -v pfx="| $step |" -v new="$new_row" '
    {
      if (index($0, pfx) == 1) { print new } else { print }
    }
  ' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
}

# Fail loudly if a row with the given step label does not exist in the file.
# Each command that mutates a specific row calls this before reading columns.
require_row() {
  local file="$1" step="$2"
  if ! grep -q "^| ${step} |" "$file"; then
    echo "row not found: $step" >&2
    exit 3
  fi
}

# Extract a column's current value for a given row. Columns are 1-indexed from
# the first field *after* the leading pipe. Returns empty string if the row
# doesn't exist (callers should have invoked require_row first).
get_column() {
  local file="$1" step="$2" col="$3"
  awk -F ' \\| ' -v pfx="| $step |" -v c="$col" '
    index($0, pfx) == 1 { print $c; exit }
  ' "$file"
}

cmd_init() {
  local gid="$1" url="$2"
  mkdir -p "$CHECKPOINTS_DIR"
  local file; file=$(file_for "$gid")
  if [[ -f "$file" ]]; then
    echo "checkpoint already exists: $file (refusing to overwrite)" >&2
    exit 1
  fi
  local ts; ts=$(now)
  cat > "$file" <<EOF
---
task_gid: "$gid"
task_id: ""
asana_url: "$url"
branch: ""
base_branch: ""
workflow: ""
created_at: "$ts"
last_updated: "$ts"
---

## Steps

| Step | Completed | Comment | Attempts | State | Auto |
|------|-----------|---------|----------|-------|------|
| 0. Dependency Check | [ ] |  | 0 | — | [ ] |
| 1. Get Task URL | [ ] |  | 0 | — | [x] |
| 2. Fetch Task Details | [ ] |  | 0 | — | [x] |
| 3. Validate Sprint-Readiness | [ ] |  | 0 | — | [ ] |
| 4. Fetch Subtasks | [ ] |  | 0 | — | [x] |
| 5. Fetch Comments & Attachments | [ ] |  | 0 | — | [x] |
| 6. Check Existing Work | [ ] |  | 0 | — | [x] |
| 6a. Ask About Worktree | [ ] |  | 0 | — | [ ] |
| 6b. Confirm Base Branch | [ ] |  | 0 | — | [ ] |
| 7. Create Feature Branch | [ ] |  | 0 | — | [x] |
| 8. Create Draft PR | [ ] |  | 0 | — | [x] |
| 9a. Move to In Progress | [ ] |  | 0 | — | [x] |
| 9b. Post Start Comment | [ ] |  | 0 | — | [x] |
| 10. Route to Workflow | [ ] |  | 0 | — | [ ] |
| QA: Resolve | [ ] |  | 0 | — | [ ] |
| QA: Investigate Bug | [ ] |  | 0 | — | [ ] |
| QA: Fix Bug | [ ] |  | 0 | — | [x] |
| QA: Verify Fix | [ ] |  | 0 | — | [ ] |
| QA: Verify Non-Bug | [ ] |  | 0 | — | [ ] |
| 12. Ship It | [ ] |  | 0 | — | [x] |

## Notes
EOF
  echo "$file"
}

cmd_start() {
  local gid="$1" step="$2"
  local file; file=$(file_for "$gid"); require_file "$file"
  validate_plain "$step"
  require_row "$file" "$step"
  local attempts auto
  attempts=$(get_column "$file" "$step" 4)
  auto=$(get_column "$file" "$step" 6)
  local new_attempts=$((attempts + 1))
  # Strip trailing " |" from auto if present
  auto=${auto% |}
  local new_row="| $step | [ ] |  | $new_attempts | in_progress | $auto |"
  replace_row "$file" "$step" "$new_row"
  touch_last_updated "$file"
}

cmd_complete() {
  local gid="$1" step="$2" comment="$3" auto="${4:-yes}"
  local file; file=$(file_for "$gid"); require_file "$file"
  validate_plain "$step"
  validate_plain "$comment"
  require_row "$file" "$step"
  local attempts
  attempts=$(get_column "$file" "$step" 4)
  # If we were already in_progress, attempts is already bumped; if not, bump now.
  local state_now; state_now=$(get_column "$file" "$step" 5)
  if [[ "$state_now" != "in_progress" ]]; then
    attempts=$((attempts + 1))
  fi
  local auto_marker="[x]"
  [[ "$auto" == "no" ]] && auto_marker="[ ]"
  local new_row="| $step | [x] | $comment | $attempts | completed | $auto_marker |"
  replace_row "$file" "$step" "$new_row"
  touch_last_updated "$file"
}

cmd_skip() {
  local gid="$1" step="$2" reason="$3"
  local file; file=$(file_for "$gid"); require_file "$file"
  validate_plain "$step"
  validate_plain "$reason"
  require_row "$file" "$step"
  local attempts auto
  attempts=$(get_column "$file" "$step" 4)
  auto=$(get_column "$file" "$step" 6); auto=${auto% |}
  local new_row="| $step | [ ] | $reason | $attempts | skipped | $auto |"
  replace_row "$file" "$step" "$new_row"
  touch_last_updated "$file"
}

cmd_block() {
  local gid="$1" step="$2" reason="$3"
  local file; file=$(file_for "$gid"); require_file "$file"
  validate_plain "$step"
  validate_plain "$reason"
  require_row "$file" "$step"
  local attempts auto
  attempts=$(get_column "$file" "$step" 4)
  auto=$(get_column "$file" "$step" 6); auto=${auto% |}
  local new_row="| $step | [ ] | $reason | $attempts | blocked | $auto |"
  replace_row "$file" "$step" "$new_row"
  touch_last_updated "$file"
}

cmd_set() {
  local gid="$1" field="$2" value="$3"
  local file; file=$(file_for "$gid"); require_file "$file"
  set_frontmatter "$file" "$field" "$value"
  touch_last_updated "$file"
}

cmd_append_note() {
  local gid="$1" text="$2"
  local file; file=$(file_for "$gid"); require_file "$file"
  printf '\n%s\n' "$text" >> "$file"
  touch_last_updated "$file"
}

cmd_read() {
  local gid="$1" step="${2:-}"
  local file; file=$(file_for "$gid"); require_file "$file"
  if [[ -z "$step" ]]; then
    cat "$file"
  else
    grep "^| ${step} |" "$file" || { echo "row not found: $step" >&2; exit 3; }
  fi
}

cmd_delete() {
  local gid="$1"
  local file; file=$(file_for "$gid")
  if [[ -f "$file" ]]; then
    rm -f "$file"
  fi
}

main() {
  local cmd="${1:-}"; shift || { echo "usage: checkpoint.sh <cmd> <args>" >&2; exit 1; }
  case "$cmd" in
    init)        cmd_init "$@" ;;
    start)       cmd_start "$@" ;;
    complete)    cmd_complete "$@" ;;
    skip)        cmd_skip "$@" ;;
    block)       cmd_block "$@" ;;
    set)         cmd_set "$@" ;;
    append-note) cmd_append_note "$@" ;;
    read)        cmd_read "$@" ;;
    delete)      cmd_delete "$@" ;;
    *) echo "unknown command: $cmd" >&2; exit 1 ;;
  esac
}

main "$@"
