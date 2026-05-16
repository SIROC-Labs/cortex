#!/usr/bin/env bash
set -euo pipefail

# SIROC Cortex — Setup Script
# Validates prerequisites, fetches available plugins, and installs selected ones
#
# Usage:
#   bash setup.sh             Claude Code setup (default)
#   bash setup.sh --opencode   OpenCode setup

MARKETPLACE_REPO="Siroc-Lab/cortex"
MARKETPLACE_NAME="siroc-cortex"
MARKETPLACE_JSON_URL="https://raw.githubusercontent.com/${MARKETPLACE_REPO}/main/.claude-plugin/marketplace.json"

OP_ENCODE=false
for arg in "$@"; do
  case "$arg" in
    --opencode) OP_ENCODE=true ;;
  esac
done

# Colors
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
step() { echo -e "\n${BOLD}[$1/$TOTAL_STEPS]${NC} $2"; }

TOTAL_STEPS=5

if [ "$OP_ENCODE" = true ]; then
  TOTAL_STEPS=6
fi

ERRORS=0
PROFILE_CHANGED=false

# Detect shell profile
if [ -f "$HOME/.zshrc" ]; then
  PROFILE="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
  PROFILE="$HOME/.bashrc"
else
  PROFILE="$HOME/.zshrc"
fi

SECTION_HEADER="# ─── SIROC Cortex ───────────────────────────"
SECTION_FOOTER="# ─────────────────────────────────────────────"

# Ensure the SIROC Cortex section exists in the profile
ensure_section() {
  if ! grep -qF "$SECTION_HEADER" "$PROFILE" 2>/dev/null; then
    echo "" >> "$PROFILE"
    echo "$SECTION_HEADER" >> "$PROFILE"
    echo "$SECTION_FOOTER" >> "$PROFILE"
  fi
}

# Check if an export already exists in the profile
exists_in_profile() {
  local var_name="$1"
  grep -q "^export ${var_name}=" "$PROFILE" 2>/dev/null
}

# Add an export inside the SIROC Cortex section if it doesn't already exist
add_to_profile() {
  local var_name="$1"
  local var_value="$2"
  local comment="${3:-}"

  if exists_in_profile "$var_name"; then
    warn "${var_name} already exists in ${PROFILE} — skipping write"
    return 1
  fi

  ensure_section

  # Insert the export line before the section footer
  local tmp="${PROFILE}.tmp.$$"
  AWKS_LINE="export ${var_name}=\"${var_value}\"" \
  awk -v header="$SECTION_FOOTER" '
    $0 == header { print ENVIRON["AWKS_LINE"] }
    { print }
  ' "$PROFILE" > "$tmp" && mv "$tmp" "$PROFILE"

  # Verify it was written
  if exists_in_profile "$var_name"; then
    export "${var_name}=${var_value}"
    PROFILE_CHANGED=true
    pass "${var_name} added to ${PROFILE}"
    return 0
  else
    fail "Failed to write ${var_name} to ${PROFILE}"
    return 1
  fi
}

# Note: we no longer source the profile mid-script because sourcing a .zshrc
# in a bash script can fail on zsh-specific syntax and kill the script.
# add_to_profile already exports the var for the current session.
# The end-of-script banner tells the user to reload for future sessions.

echo -e "${BOLD}SIROC Cortex — Setup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─────────────────────────────────────────────
# Step 1: GitHub CLI
# ─────────────────────────────────────────────
step 1 "GitHub CLI"

if ! command -v gh &>/dev/null; then
  fail "gh CLI not installed"
  info "Install with: brew install gh"
  ERRORS=$((ERRORS + 1))
else
  pass "gh CLI installed ($(gh --version | head -1))"

  if gh auth status &>/dev/null; then
    GH_USER=$(gh api user --jq '.login' 2>/dev/null || echo "unknown")
    pass "Authenticated as ${GH_USER}"
  else
    fail "Not authenticated"
    info "Run: gh auth login"
    ERRORS=$((ERRORS + 1))
  fi

  if gh repo view "$MARKETPLACE_REPO" &>/dev/null; then
    pass "Access to ${MARKETPLACE_REPO} confirmed"
  else
    fail "Cannot access ${MARKETPLACE_REPO}"
    info "Check your permissions or run: gh auth login"
    ERRORS=$((ERRORS + 1))
  fi
fi

# ─────────────────────────────────────────────
# Step 2: Git SSH config
# ─────────────────────────────────────────────
step 2 "Git SSH configuration"

SSH_OUTPUT=$(ssh -T git@github.com 2>&1 || true)
if echo "$SSH_OUTPUT" | grep -qi "successfully authenticated"; then
  pass "SSH authentication to GitHub works"
else
  warn "SSH authentication to GitHub not confirmed"
  info "If you use SSH keys, run: ssh -T git@github.com"
fi

INSTEADOF=$(git config --global --get url."git@github.com:".insteadOf 2>/dev/null || echo "")
if [ "$INSTEADOF" = "https://github.com/" ]; then
  pass "Git HTTPS→SSH rewrite configured"
else
  warn "Git HTTPS→SSH rewrite not configured"
  info "Claude Code uses HTTPS internally. To route through SSH, run:"
  info "git config --global url.\"git@github.com:\".insteadOf \"https://github.com/\""
  echo ""
  read -rp "  Configure this now? [Y/n] " REPLY
  REPLY=${REPLY:-Y}
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    git config --global url."git@github.com:".insteadOf "https://github.com/"
    pass "HTTPS→SSH rewrite configured"
  else
    warn "Skipped — HTTPS auth must work for marketplace install"
  fi
fi

# ─────────────────────────────────────────────
# Step 3: Asana token
# ─────────────────────────────────────────────
step 3 "Asana personal access token"

# If not in env but exists in profile, extract it directly
if [ -z "${ASANA_PERSONAL_ACCESS_TOKEN:-}" ] && exists_in_profile "ASANA_PERSONAL_ACCESS_TOKEN"; then
  ASANA_PERSONAL_ACCESS_TOKEN=$(grep "^export ASANA_PERSONAL_ACCESS_TOKEN=" "$PROFILE" | head -1 | sed 's/^export ASANA_PERSONAL_ACCESS_TOKEN="//' | sed 's/"$//')
  export ASANA_PERSONAL_ACCESS_TOKEN
  pass "Loaded ASANA_PERSONAL_ACCESS_TOKEN from ${PROFILE}"
fi

# If still not set, prompt the user (required — loop until provided)
if [ -z "${ASANA_PERSONAL_ACCESS_TOKEN:-}" ]; then
  fail "ASANA_PERSONAL_ACCESS_TOKEN not set"
  info "This token is required for Asana API operations (task management, comments, board moves)"
  info "Generate one at: https://app.asana.com/0/my-apps → Create new token"
  echo ""
  while true; do
    read -rp "  Paste your Asana personal access token: " ASANA_TOKEN_INPUT || true
    if [ -n "$ASANA_TOKEN_INPUT" ]; then
      add_to_profile "ASANA_PERSONAL_ACCESS_TOKEN" "$ASANA_TOKEN_INPUT"
      break
    else
      warn "Token is required — please paste your Asana personal access token"
    fi
  done
fi

if [ -n "${ASANA_PERSONAL_ACCESS_TOKEN:-}" ]; then
  pass "ASANA_PERSONAL_ACCESS_TOKEN is set"

  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
    "https://app.asana.com/api/1.0/users/me")

  if [ "$HTTP_STATUS" = "200" ]; then
    ASANA_USER=$(curl -s -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
      "https://app.asana.com/api/1.0/users/me?opt_fields=name,email" \
      | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f\"{d['name']} ({d['email']})\")" 2>/dev/null || echo "unknown")
    pass "Token valid — ${ASANA_USER}"
  elif [ "$HTTP_STATUS" = "401" ]; then
    warn "Token is invalid or expired (HTTP 401) — you can regenerate later"
    info "Regenerate at: https://app.asana.com/0/my-apps"
  else
    warn "Asana API returned HTTP ${HTTP_STATUS} — could not verify token"
  fi
fi

# Optional: additional Asana accounts
if [ -n "${ASANA_PERSONAL_ACCESS_TOKEN:-}" ]; then
  echo ""
  read -rp "  Add additional Asana accounts (ASANA_TOKEN_<NAME>)? [y/N] " ADD_MORE || true
  ADD_MORE=${ADD_MORE:-N}
  if [[ "$ADD_MORE" =~ ^[Yy]$ ]]; then
    while true; do
      echo ""
      read -rp "  Account name (e.g. 'work', 'client_x') — leave blank to stop: " ACCT_NAME
      [ -z "$ACCT_NAME" ] && break

      # Uppercase and prefix
      ACCT_VAR="ASANA_TOKEN_$(printf "%s" "$ACCT_NAME" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9_' '_')"

      if exists_in_profile "$ACCT_VAR"; then
        warn "${ACCT_VAR} already exists in ${PROFILE} — skipping"
        continue
      fi

      read -rp "  Paste token for ${ACCT_VAR}: " ACCT_TOKEN_INPUT
      if [ -z "$ACCT_TOKEN_INPUT" ]; then
        warn "No token provided — skipping ${ACCT_VAR}"
        continue
      fi

      add_to_profile "$ACCT_VAR" "$ACCT_TOKEN_INPUT"

      # Validate
      ACCT_HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $ACCT_TOKEN_INPUT" \
        "https://app.asana.com/api/1.0/users/me")

      if [ "$ACCT_HTTP" = "200" ]; then
        ACCT_USER=$(curl -s -H "Authorization: Bearer $ACCT_TOKEN_INPUT" \
          "https://app.asana.com/api/1.0/users/me?opt_fields=name,email" \
          | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f\"{d['name']} ({d['email']})\")" 2>/dev/null || echo "unknown")
        pass "${ACCT_VAR} valid — ${ACCT_USER}"
      elif [ "$ACCT_HTTP" = "401" ]; then
        warn "${ACCT_VAR} token is invalid or expired (HTTP 401)"
        info "Regenerate at: https://app.asana.com/0/my-apps"
      else
        warn "Asana API returned HTTP ${ACCT_HTTP} for ${ACCT_VAR} — could not verify"
      fi
    done
  fi
fi

# ─────────────────────────────────────────────
# Step 4: GitHub token for auto-updates
# ─────────────────────────────────────────────
step 4 "GitHub token (for background auto-updates)"

# If not in env but exists in profile, extract it directly
if [ -z "${GITHUB_TOKEN:-}" ] && [ -z "${GH_TOKEN:-}" ] && exists_in_profile "GITHUB_TOKEN"; then
  GITHUB_TOKEN=$(grep "^export GITHUB_TOKEN=" "$PROFILE" | head -1 | sed 's/^export GITHUB_TOKEN="//' | sed 's/"$//')
  export GITHUB_TOKEN
  pass "Loaded GITHUB_TOKEN from ${PROFILE}"
fi

if [ -n "${GITHUB_TOKEN:-}" ] || [ -n "${GH_TOKEN:-}" ]; then
  pass "GITHUB_TOKEN or GH_TOKEN is set"
else
  warn "No GITHUB_TOKEN or GH_TOKEN set"
  info "Auto-updates for private marketplaces won't work without this"

  # Try to get token from gh CLI
  if command -v gh &>/dev/null && gh auth status &>/dev/null; then
    GH_AUTH_TOKEN=$(gh auth token 2>/dev/null || echo "")
    if [ -n "$GH_AUTH_TOKEN" ]; then
      info "Found a token from gh CLI"
      read -rp "  Add GITHUB_TOKEN to ${PROFILE} from gh auth? [Y/n] " REPLY
      REPLY=${REPLY:-Y}
      if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        add_to_profile "GITHUB_TOKEN" "$GH_AUTH_TOKEN"
      else
        warn "Skipped"
      fi
    fi
  fi

  if [ -z "${GITHUB_TOKEN:-}" ] && [ -z "${GH_TOKEN:-}" ]; then
    info "You can set it manually later:"
    info "  echo 'export GITHUB_TOKEN=\"\$(gh auth token)\"' >> ${PROFILE}"
  fi
fi

# ─────────────────────────────────────────────
# Step 5: OpenCode configuration
# ─────────────────────────────────────────────

configure_opencode() {
  local CONFIG_DIR="${HOME}/.config/opencode"
  local CACHE_DIR="${HOME}/.cache/opencode/node_modules"
  local CONFIG_FILE="${CONFIG_DIR}/opencode.json"

  info "Configuring OpenCode..."

  # Ensure config directory exists
  mkdir -p "$CONFIG_DIR"

  # Add plugins and merge mcpServers into opencode.json
  # Detect repo root for local development
  local SCRIPT_DIR
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  python3 - "$CONFIG_FILE" "$SCRIPT_DIR" <<'PYEOF'
import json, sys, os

config_path = sys.argv[1]
cortex_entry = "asana-workflow@git+https://github.com/Siroc-Lab/cortex.git"
superpowers_entry = "superpowers@git+https://github.com/obra/superpowers.git"

# If running from within the repo clone, use local path instead of git+ URL
script_root = sys.argv[2] if len(sys.argv) > 2 else ""
if script_root and os.path.isfile(os.path.join(script_root, "package.json")):
    cortex_entry = script_root

try:
    with open(config_path) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    config = {}

plugins = config.get("plugin", [])
if cortex_entry not in plugins:
    plugins.append(cortex_entry)
if superpowers_entry not in plugins:
    plugins.append(superpowers_entry)
config["plugin"] = plugins

mcp = config.get("mcp", {})
mcp["mobile-mcp"] = {"type": "local", "command": ["npx", "-y", "@mobilenext/mobile-mcp@latest"]}
mcp["chrome-devtools"] = {"type": "local", "command": ["npx", "-y", "chrome-devtools-mcp@latest", "--experimentalScreencast"]}
config["mcp"] = mcp

perm = config.get("permission", {})
ext = perm.get("external_directory", {})
# Whitelist paths the plugin needs to read/write outside the project directory
ext["~/.cortex/asana-workflow/*"] = "allow"
# ^ checkpoint files and board registry cache (written by checkpoint.sh, read by skills)
ext["~/.config/opencode/opencode.json"] = "allow"
# ^ dependency check reads opencode.json to verify superpowers is installed
ext["/tmp/qa-evidence/*"] = "allow"
# ^ QA screenshots and recordings saved during web-qa / mobile-qa investigations
perm["external_directory"] = ext
config["permission"] = perm

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")

print("OK")
PYEOF

  if [ $? -eq 0 ]; then
    pass "opencode.json configured at ${CONFIG_FILE}"
  else
    fail "Failed to configure opencode.json"
    return 1
  fi

  # Clear plugin cache to force fresh install on restart
  if [ -d "$CACHE_DIR" ]; then
    rm -rf "${CACHE_DIR}/asana-workflow" 2>/dev/null || true
    info "Plugin cache cleared"
  fi

  return 0
}
if [ "$OP_ENCODE" = true ]; then
  # ─────────────────────────────────────────────
  # OpenCode: configure plugin and show instructions
  # ─────────────────────────────────────────────
  if [ "$ERRORS" -gt 0 ]; then
    echo ""
    fail "${ERRORS} error(s) found — fix them and re-run this script"
    echo ""
    exit 1
  fi

  step 5 "OpenCode plugin configuration"
  configure_opencode

  step 6 "Done"
  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  Environment ready!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo "  Restart OpenCode to pick up the changes."
  echo ""
  echo "  Verify by asking: list available skills"
  echo ""
  echo "  To update later, re-run: bash setup.sh --opencode"
  echo ""

  if [ "$PROFILE_CHANGED" = true ]; then
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}${BOLD}  ⚠  IMPORTANT: Reload your shell to apply changes!${NC}"
    echo ""
    echo -e "${YELLOW}  Run one of the following:${NC}"
    echo ""
    echo -e "${BOLD}    source ${PROFILE}${NC}"
    echo ""
    echo -e "${YELLOW}  Or simply open a new terminal window.${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
  fi
else
  # ─────────────────────────────────────────────
  # Claude Code: show install commands
  # ─────────────────────────────────────────────
  step 5 "Next steps"

  if [ "$ERRORS" -gt 0 ]; then
    echo ""
    fail "${ERRORS} error(s) found — fix them and re-run this script"
    echo ""
    exit 1
  fi

  pass "All prerequisites met"

  # Fetch marketplace.json to show available plugins
  MARKETPLACE_JSON=$(gh api "repos/${MARKETPLACE_REPO}/contents/.claude-plugin/marketplace.json" \
    --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || echo "")

  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  Environment ready!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo "  Open Claude Code and run these commands:"
  echo ""
  echo -e "    ${BOLD}1.${NC} Add the marketplace:"
  echo -e "       ${GREEN}/plugin marketplace add ${MARKETPLACE_REPO}${NC}"
  echo ""

  if [ -n "$MARKETPLACE_JSON" ]; then
    echo -e "    ${BOLD}2.${NC} Install plugins:"
    echo "$MARKETPLACE_JSON" | python3 -c "
import sys, json
plugins = json.load(sys.stdin)['plugins']
for p in plugins:
    name = p['name']
    desc = p.get('description', '')
    version = p.get('version', '?')
    print(f'       \033[0;32m/plugin install {name}@${MARKETPLACE_NAME}\033[0m  (v{version})')
    if desc:
        print(f'         {desc}')
    print()
" 2>/dev/null
  else
    echo -e "    ${BOLD}2.${NC} Install plugins:"
    echo -e "       ${GREEN}/plugin install <plugin-name>@${MARKETPLACE_NAME}${NC}"
    echo ""
  fi

  echo "  Manage plugins:"
  echo -e "    /plugin list                              — See installed plugins"
  echo -e "    /plugin marketplace update ${MARKETPLACE_NAME}  — Pull latest versions"
  echo ""

  if [ "$PROFILE_CHANGED" = true ]; then
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}${BOLD}  ⚠  IMPORTANT: Reload your shell to apply changes!${NC}"
    echo ""
    echo -e "${YELLOW}  Run one of the following:${NC}"
    echo ""
    echo -e "${BOLD}    source ${PROFILE}${NC}"
    echo ""
    echo -e "${YELLOW}  Or simply open a new terminal window.${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
  fi
fi
