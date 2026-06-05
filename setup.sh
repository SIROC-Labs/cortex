#!/usr/bin/env bash
set -euo pipefail

# SIROC Cortex — Setup Script
# Validates prerequisites, fetches available plugins, and installs selected ones
#
# Usage:
#   bash setup.sh              Claude Code setup (default)
#   bash setup.sh --opencode    OpenCode setup
#   bash setup.sh --codex       Codex setup
#   bash setup.sh --all         Install for every supported agent (each isolated;
#                               one agent failing never blocks the others; prints
#                               a per-agent success/failure summary at the end)
#   bash setup.sh --dev         Developer install: point at this local clone
#                               instead of the remote repo (combine with an
#                               agent flag or --all, e.g. `bash setup.sh --all --dev`)
#
# By default the install is "normal": the marketplace/plugin source is the remote
# SIROC-Labs/cortex repo, so no local clone of the repo is required. Pass --dev to
# source from this working copy instead.

MARKETPLACE_REPO="SIROC-Labs/cortex"
MARKETPLACE_NAME="siroc-cortex"
MARKETPLACE_JSON_URL="https://raw.githubusercontent.com/${MARKETPLACE_REPO}/main/.claude-plugin/marketplace.json"

OPENCODE=false
CODEX=false
ALL=false
DEV=false
for arg in "$@"; do
  case "$arg" in
    --opencode) OPENCODE=true ;;
    --codex) CODEX=true ;;
    --all) ALL=true ;;
    --dev) DEV=true ;;
  esac
done

if [ "$OPENCODE" = true ] && [ "$CODEX" = true ]; then
  echo "Use either --opencode or --codex, not both." >&2
  exit 1
fi

if [ "$ALL" = true ] && { [ "$OPENCODE" = true ] || [ "$CODEX" = true ]; }; then
  echo "Use --all on its own (optionally with --dev), not with --opencode/--codex." >&2
  exit 1
fi

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

TOTAL_STEPS=6

ERRORS=0
PROFILE_CHANGED=false
EXIT_CODE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# In --dev, force a clean re-point to the local clone: remove the installed plugin
# and the marketplace first, since `marketplace add` is idempotent and won't switch
# an already-registered source. $1 = CLI, $2 = its plugin-removal subcommand.
repoint_dev() {
  info "Dev mode: re-pointing ${MARKETPLACE_NAME} to the local clone"
  "$1" plugin "$2" "asana-workflow@${MARKETPLACE_NAME}" >/dev/null 2>&1 || true
  "$1" plugin "$2" "dev-toolkit@${MARKETPLACE_NAME}" >/dev/null 2>&1 || true
  "$1" plugin marketplace remove "$MARKETPLACE_NAME" >/dev/null 2>&1 || true
}

ready_banner() {
  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  Environment ready!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
}

print_reload_banner() {
  [ "$PROFILE_CHANGED" = true ] || return 0
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
}

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

# </dev/null: ssh would otherwise consume the script's stdin, eating answers
# meant for later prompts when the script runs with piped/redirected input.
SSH_OUTPUT=$(ssh -T git@github.com </dev/null 2>&1 || true)
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
  info "Marketplaces are not supported by OpenCode — installing the plugins directly..."

  # Ensure config directory exists
  mkdir -p "$CONFIG_DIR"

  # Add plugins and merge mcpServers into opencode.json. Default to the remote
  # git+ URL; only in --dev mode pass the local clone path to use instead.
  local DEV_ROOT=""
  [ "$DEV" = true ] && DEV_ROOT="$SCRIPT_DIR"

  python3 - "$CONFIG_FILE" "$DEV_ROOT" <<'PYEOF'
import json, sys, os

config_path = sys.argv[1]
cortex_entry = "asana-workflow@git+https://github.com/SIROC-Labs/cortex.git"
superpowers_entry = "superpowers@git+https://github.com/obra/superpowers.git"

# In --dev mode, argv[2] is the local clone path; use it instead of the git+ URL.
script_root = sys.argv[2] if len(sys.argv) > 2 else ""
dev = bool(script_root and os.path.isfile(os.path.join(script_root, "package.json")))
if dev:
    cortex_entry = script_root

try:
    with open(config_path) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    config = {}

plugins = config.get("plugin", [])

def spec_name(spec):
    # Resolve a plugin spec to its plugin name so we dedupe across spec forms
    # (git+ URL, pinned #ref, plain npm name, or local clone path).
    s = str(spec).strip().rstrip("/")
    # Local clone path: the dir basename (e.g. "cortex") is NOT the plugin name,
    # so read the real name from its package.json.
    expanded = os.path.expanduser(s)
    if os.path.isdir(expanded):
        try:
            with open(os.path.join(expanded, "package.json")) as f:
                return json.load(f).get("name") or os.path.basename(s)
        except (FileNotFoundError, json.JSONDecodeError):
            return os.path.basename(s)
    if s.startswith("@"):  # scoped npm package: @scope/name[@version]
        return "@" + s[1:].split("@", 1)[0]
    base = s.split("@", 1)[0]
    if "/" in base:        # path or URL without a name@ prefix
        base = base.rsplit("/", 1)[-1]
    return base

# In --dev, force the local asana-workflow path by dropping any existing entry first,
# so the local clone replaces it instead of being skipped by the dedupe below.
if dev:
    plugins = [p for p in plugins if spec_name(p) != "asana-workflow"]

# Add each plugin by canonical name, so an entry already present in ANY spec form
# (e.g. a pinned or differently-sourced superpowers) is respected instead of duplicated.
existing = {spec_name(p) for p in plugins}
for name, entry in (("asana-workflow", cortex_entry), ("superpowers", superpowers_entry)):
    if name not in existing:
        plugins.append(entry)
        existing.add(name)
config["plugin"] = plugins

# MCP servers are registered at load time by the OpenCode adapter
# (.opencode/plugins/asana-workflow.js) from the plugin's bundled .mcp.json — the
# single source of truth (shared with Claude and Codex). Not written here.

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

configure_codex() {
  info "Configuring Codex..."

  if ! command -v codex &>/dev/null; then
    fail "Codex CLI not installed"
    info "Install Codex, then re-run: bash setup.sh --codex"
    return 2
  fi

  pass "Codex CLI installed ($(codex --version | head -1))"

  # Default to the remote marketplace (GitHub repo); --dev uses the local clone root.
  local MP_SOURCE="$MARKETPLACE_REPO"
  if [ "$DEV" = true ]; then
    MP_SOURCE="$SCRIPT_DIR"

    # Validate the local marketplace + plugin manifests before registering them.
    local MARKETPLACE_FILE="${SCRIPT_DIR}/.agents/plugins/marketplace.json"
    local PLUGIN_MANIFEST="${SCRIPT_DIR}/plugins/asana-workflow/.codex-plugin/plugin.json"
    local DEVTOOLKIT_MANIFEST="${SCRIPT_DIR}/plugins/dev-toolkit/.codex-plugin/plugin.json"
    local MCP_MANIFEST="${SCRIPT_DIR}/plugins/asana-workflow/.mcp.json"
    for manifest in "$MARKETPLACE_FILE" "$PLUGIN_MANIFEST" "$DEVTOOLKIT_MANIFEST" "$MCP_MANIFEST"; do
      if [ ! -f "$manifest" ]; then
        fail "Missing local Codex manifest: ${manifest}"
        return 1
      fi
    done
    if python3 - "$MARKETPLACE_FILE" "$PLUGIN_MANIFEST" "$DEVTOOLKIT_MANIFEST" "$MCP_MANIFEST" <<'PYEOF'
import json, sys
for path in sys.argv[1:]:
    with open(path) as f:
        json.load(f)
print("OK")
PYEOF
    then
      pass "Local Codex manifests valid"
    else
      fail "Codex plugin metadata is invalid JSON"
      return 1
    fi

    repoint_dev codex remove
  fi

  if codex plugin marketplace add "$MP_SOURCE" >/dev/null 2>&1; then
    pass "Codex marketplace added from ${MP_SOURCE}"
  elif codex plugin marketplace upgrade "$MARKETPLACE_NAME" >/dev/null 2>&1; then
    pass "Codex marketplace already present — upgraded ${MARKETPLACE_NAME}"
  else
    fail "Failed to add or upgrade Codex marketplace"
    info "Try manually: codex plugin marketplace add ${MP_SOURCE}"
    return 1
  fi

  # MCP servers (mobile-mcp, chrome-devtools) are declared in the plugin manifest
  # (.codex-plugin/plugin.json -> ./.mcp.json) and load automatically when the plugin
  # is enabled — no `codex mcp add` needed. Verified: they stay available with zero
  # [mcp_servers] entries in config.toml.

  if [ "$INSTALL_PLUGINS" != true ]; then
    info "Skipping plugin install — choose from the marketplace:"
    info "  codex plugin add asana-workflow@${MARKETPLACE_NAME}"
    info "  codex plugin add dev-toolkit@${MARKETPLACE_NAME}"
    info "  codex plugin add superpowers@openai-curated   (required by asana-workflow)"
    info "  Or browse with /plugins inside Codex."
    return 0
  fi

  # Install our plugins from the marketplace snapshot (global, in ~/.codex/config.toml).
  if codex plugin add "asana-workflow@${MARKETPLACE_NAME}" >/dev/null 2>&1; then
    pass "Codex plugin installed: asana-workflow@${MARKETPLACE_NAME}"
  else
    fail "Failed to install plugin; install manually: codex plugin add asana-workflow@${MARKETPLACE_NAME}"
    return 1
  fi

  if codex plugin add "dev-toolkit@${MARKETPLACE_NAME}" >/dev/null 2>&1; then
    pass "Codex plugin installed: dev-toolkit@${MARKETPLACE_NAME}"
  else
    warn "Could not install dev-toolkit — install manually: codex plugin add dev-toolkit@${MARKETPLACE_NAME}"
  fi

  # superpowers is sourced from the official openai-curated catalog — its single
  # canonical source — NOT from our marketplace. Codex does not dedupe identically
  # named plugins across marketplaces, so shipping our own copy too would load its
  # skills twice. `codex plugin add` is idempotent, so this runs unconditionally.
  # Non-fatal: openai-curated may be unavailable in some environments.
  if codex plugin add superpowers@openai-curated >/dev/null 2>&1; then
    pass "Codex dependency installed: superpowers@openai-curated"
  else
    warn "Could not auto-install superpowers@openai-curated — install it manually:"
    warn "  codex plugin add superpowers@openai-curated"
  fi

  return 0
}

configure_claude() {
  # Returns: 0 installed, 1 a step failed, 2 claude CLI not found (caller prints manual steps)
  if ! command -v claude &>/dev/null; then
    return 2
  fi

  # Default to the remote GitHub marketplace; --dev uses the local clone.
  local MP_SOURCE="$MARKETPLACE_REPO"
  [ "$DEV" = true ] && MP_SOURCE="$SCRIPT_DIR"

  if [ "$DEV" = true ]; then
    repoint_dev claude uninstall
  fi

  info "Adding marketplace ${MARKETPLACE_NAME} (user scope)..."
  if claude plugin marketplace add "$MP_SOURCE" >/dev/null 2>&1; then
    pass "Marketplace ${MARKETPLACE_NAME} ready"
  else
    fail "Failed to add marketplace; add manually: claude plugin marketplace add ${MP_SOURCE}"
    return 1
  fi

  if [ "$INSTALL_PLUGINS" != true ]; then
    info "Skipping plugin install — choose from the marketplace:"
    info "  Inside Claude Code: /plugin  → browse ${MARKETPLACE_NAME}"
    info "  Or from the shell:  claude plugin install <plugin>@${MARKETPLACE_NAME}"
    info "  Available: asana-workflow, dev-toolkit (dependencies auto-resolve on install)"
    return 0
  fi

  # Installing the plugin auto-resolves its declared dependencies (feature-dev,
  # superpowers) from claude-plugins-official via allowCrossMarketplaceDependenciesOn.
  info "Installing asana-workflow plugin (user scope)..."
  if claude plugin install "asana-workflow@${MARKETPLACE_NAME}" --scope user >/dev/null 2>&1; then
    pass "Plugin installed: asana-workflow@${MARKETPLACE_NAME}"
  else
    fail "Failed to install plugin; install manually: claude plugin install asana-workflow@${MARKETPLACE_NAME}"
    return 1
  fi

  info "Installing dev-toolkit plugin (user scope)..."
  if claude plugin install "dev-toolkit@${MARKETPLACE_NAME}" --scope user >/dev/null 2>&1; then
    pass "Plugin installed: dev-toolkit@${MARKETPLACE_NAME}"
  else
    warn "Could not install dev-toolkit — install manually: claude plugin install dev-toolkit@${MARKETPLACE_NAME}"
  fi

  return 0
}

# All install paths require a clean prerequisite check
if [ "$ERRORS" -gt 0 ]; then
  echo ""
  fail "${ERRORS} error(s) found — fix them and re-run this script"
  echo ""
  exit 1
fi

# Claude Code and Codex are marketplace-based: the user can install everything now
# or register the marketplace only and pick plugins themselves. OpenCode has no
# marketplace, so its plugins are always installed directly (no question needed).
# --dev always installs all: it re-points the install at the local clone, and a
# dev re-point with nothing installed afterwards is never what a contributor wants.
INSTALL_PLUGINS=true
if [ "$OPENCODE" != true ] && [ "$DEV" != true ]; then
  echo ""
  read -rp "  Install all plugins now (asana-workflow, dev-toolkit)? [Y/n] " PLUGINS_REPLY || true
  PLUGINS_REPLY=${PLUGINS_REPLY:-Y}
  if [[ ! "$PLUGINS_REPLY" =~ ^[Yy]$ ]]; then
    INSTALL_PLUGINS=false
    info "Plugins will not be installed — the marketplace will be registered so you can choose."
  fi
fi

if [ "$ALL" = true ]; then
  # ─────────────────────────────────────────────
  # All agents: install each independently. One agent's failure never blocks the
  # others — each configure_* is called in an `|| rc=$?` context, which captures a
  # non-zero return (and suspends `set -e` inside the function) instead of aborting
  # the script. A per-agent success/failure summary is printed at the end.
  # ─────────────────────────────────────────────
  step 5 "Installing for all supported agents"

  # rc convention: 0 = installed, 2 = skipped (agent CLI absent), other = failed.
  CLAUDE_RC=0;   echo ""; info "── Claude Code ──"; configure_claude   || CLAUDE_RC=$?
  OPENCODE_RC=0; echo ""; info "── OpenCode ──";    configure_opencode || OPENCODE_RC=$?
  CODEX_RC=0;    echo ""; info "── Codex ──";       configure_codex    || CODEX_RC=$?

  agent_status() {
    case "$1" in
      0) echo -e "${GREEN}✔ installed${NC}" ;;
      2) echo -e "${YELLOW}⏭ skipped (CLI not found)${NC}" ;;
      *) echo -e "${RED}✘ failed${NC}" ;;
    esac
  }

  step 6 "Summary"
  echo ""
  echo -e "  Claude Code   $(agent_status "$CLAUDE_RC")"
  echo -e "  OpenCode      $(agent_status "$OPENCODE_RC")"
  echo -e "  Codex         $(agent_status "$CODEX_RC")"
  echo ""

  FAILED=0
  for rc in "$CLAUDE_RC" "$OPENCODE_RC" "$CODEX_RC"; do
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then FAILED=$((FAILED + 1)); fi
  done
  if [ "$FAILED" -gt 0 ]; then
    warn "${FAILED} agent install(s) failed — see messages above. The other agents were unaffected."
    EXIT_CODE=1
  else
    echo "  Restart each installed agent to load the plugin and skills."
  fi
  echo ""
elif [ "$OPENCODE" = true ]; then
  # ─────────────────────────────────────────────
  # OpenCode: configure plugin and show instructions
  # ─────────────────────────────────────────────
  step 5 "OpenCode plugin configuration"
  configure_opencode

  step 6 "Done"
  ready_banner
  echo "  Restart OpenCode to pick up the changes."
  echo ""
  echo "  Verify by asking: list available skills"
  echo ""
  echo "  To update later, re-run: bash setup.sh --opencode"
  echo ""
elif [ "$CODEX" = true ]; then
  # ─────────────────────────────────────────────
  # Codex: configure marketplace, declared MCPs, and show instructions
  # ─────────────────────────────────────────────
  step 5 "Codex plugin configuration"
  configure_codex

  step 6 "Done"
  ready_banner
  if [ "$INSTALL_PLUGINS" = true ]; then
    echo "  asana-workflow, dev-toolkit + superpowers (from openai-curated) are installed;"
    echo "  the declared MCP servers load automatically from the plugin manifest."
  else
    echo "  Marketplace ${MARKETPLACE_NAME} is registered — install the plugins you want:"
    echo -e "    ${GREEN}codex plugin add <plugin>@${MARKETPLACE_NAME}${NC}"
  fi
  echo ""
  echo "  Restart Codex to pick up the plugin metadata and skills."
  echo ""
else
  # ─────────────────────────────────────────────
  # Claude Code: install marketplace + plugin (user/global scope)
  # ─────────────────────────────────────────────
  step 5 "Claude Code plugin installation"
  pass "All prerequisites met"
  # Capture the return without tripping `set -e` (a bare call would abort on
  # a non-zero return before we could read it).
  CLAUDE_RC=0
  configure_claude || CLAUDE_RC=$?

  step 6 "Done"
  ready_banner

  if [ "$CLAUDE_RC" -eq 0 ]; then
    if [ "$INSTALL_PLUGINS" = true ]; then
      echo "  asana-workflow and dev-toolkit are installed (user scope); asana-workflow's"
      echo "  dependencies (feature-dev, superpowers) were resolved automatically."
      echo ""
      echo "  Restart Claude Code to load the plugins and skills."
    else
      echo "  Marketplace ${MARKETPLACE_NAME} is registered — install the plugins you want:"
      echo -e "    ${GREEN}/plugin install asana-workflow@${MARKETPLACE_NAME}${NC}"
      echo -e "    ${GREEN}/plugin install dev-toolkit@${MARKETPLACE_NAME}${NC}"
    fi
    echo ""
    echo "  Manage plugins:"
    echo -e "    claude plugin list                                — See installed plugins"
    echo -e "    claude plugin update asana-workflow@${MARKETPLACE_NAME}  — Pull latest version"
    echo ""
  else
    echo "  Claude Code CLI not found on PATH — finish install from inside Claude Code:"
    echo ""
    echo -e "    ${GREEN}/plugin marketplace add ${MARKETPLACE_REPO}${NC}"
    echo -e "    ${GREEN}/plugin install asana-workflow@${MARKETPLACE_NAME}${NC}"
    echo -e "    ${GREEN}/plugin install dev-toolkit@${MARKETPLACE_NAME}${NC}"
    echo ""
  fi
fi

print_reload_banner
exit "$EXIT_CODE"
