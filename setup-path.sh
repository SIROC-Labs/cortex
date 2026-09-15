#!/usr/bin/env bash
set -euo pipefail

# SIROC Cortex — PATH Setup
# Puts the tools in bin/ on your PATH by adding two exports to your shell
# profile. No symlinks, nothing copied outside this clone — move or rename the
# clone and you re-run this.
#
# Usage:
#   bash setup-path.sh          # add the exports
#   bash setup-path.sh --check  # report what is set, change nothing

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Each entry is a directory under bin/ holding a directly executable tool.
# PATH needs the tool's own directory, not bin/, because bin/ holds directories.
TOOL_DIRS=("bin/fast-task")

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✔${NC} $1"; }
fail() { echo -e "  ${RED}✘${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
info() { echo -e "  ${BLUE}→${NC} $1"; }

if [ -f "$HOME/.zshrc" ]; then
  PROFILE="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
  PROFILE="$HOME/.bashrc"
else
  PROFILE="$HOME/.zshrc"
fi

SECTION_HEADER="# ─── SIROC Cortex ───────────────────────────"
SECTION_FOOTER="# ─────────────────────────────────────────────"

CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

echo -e "${BOLD}SIROC Cortex — PATH Setup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
info "clone:   ${ROOT}"
info "profile: ${PROFILE}"
echo ""

# Lines to ensure, in order. CORTEX_HOME first — the PATH entries reference it.
LINES=("export CORTEX_HOME=\"${ROOT}\"")
for dir in "${TOOL_DIRS[@]}"; do
  LINES+=("export PATH=\"\$CORTEX_HOME/${dir}:\$PATH\"")
done

# An existing CORTEX_HOME pointing at a different clone is the one case worth
# stopping for: appending a second one silently shadows the first.
EXISTING_HOME=$(grep '^export CORTEX_HOME=' "$PROFILE" 2>/dev/null \
  | head -1 | sed 's/^export CORTEX_HOME="//' | sed 's/"$//' || true)
if [ -n "$EXISTING_HOME" ] && [ "$EXISTING_HOME" != "$ROOT" ]; then
  fail "CORTEX_HOME already points elsewhere: ${EXISTING_HOME}"
  info "Edit ${PROFILE} by hand, or remove that line and re-run"
  exit 1
fi

CHANGED=false
for line in "${LINES[@]}"; do
  if grep -qxF "$line" "$PROFILE" 2>/dev/null; then
    pass "already set: ${line}"
    continue
  fi
  if [ "$CHECK_ONLY" = true ]; then
    warn "missing: ${line}"
    continue
  fi
  if ! grep -qF "$SECTION_HEADER" "$PROFILE" 2>/dev/null; then
    printf '\n%s\n%s\n' "$SECTION_HEADER" "$SECTION_FOOTER" >> "$PROFILE"
  fi
  tmp="${PROFILE}.tmp.$$"
  NEW_LINE="$line" awk -v footer="$SECTION_FOOTER" '
    $0 == footer { print ENVIRON["NEW_LINE"] }
    { print }
  ' "$PROFILE" > "$tmp" && mv "$tmp" "$PROFILE"
  pass "added: ${line}"
  CHANGED=true
done

if [ "$CHECK_ONLY" = false ]; then
  for dir in "${TOOL_DIRS[@]}"; do
    find "${ROOT}/${dir}" -maxdepth 1 -name '*.py' -exec chmod +x {} + 2>/dev/null || true
  done
fi

echo ""
if [ "$CHECK_ONLY" = true ]; then
  if command -v fast_task.py &>/dev/null; then
    pass "fast_task.py resolves to $(command -v fast_task.py)"
  else
    warn "fast_task.py is not on PATH in this shell"
  fi
  exit 0
fi

if [ "$CHANGED" = true ]; then
  echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${YELLOW}${BOLD}  ⚠  Reload your shell to apply changes!${NC}"
  echo ""
  echo -e "${BOLD}    source ${PROFILE}${NC}"
  echo ""
  echo -e "${YELLOW}  Or simply open a new terminal window.${NC}"
  echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  info "Then, from inside any repo: fast_task.py run <task-url>"
else
  echo -e "${GREEN}Nothing to do — PATH already set up.${NC}"
  echo ""
  info "From inside any repo: fast_task.py run <task-url>"
fi
echo ""
