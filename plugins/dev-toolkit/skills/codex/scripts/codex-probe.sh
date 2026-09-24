#!/usr/bin/env bash
# codex-probe.sh — shared helpers for the /codex skill.
# Sourced from SKILL.md bash blocks; never execute directly.
#
# Functions:
#   _codex_auth_probe      — multi-signal auth check (env vars + auth file)
#   _codex_model_probe     — round-trip probe of the selected model
#   _codex_version_check   — warn on known-bad Codex CLI versions
#   _codex_timeout_wrapper — gtimeout -> timeout -> bash-native watchdog
#
# Hygiene rules:
#   - Never set -e / set -u / trap / IFS= / PATH= in this file. It is SOURCED
#     into a caller's shell; changing global shell state there breaks the caller.
#   - All internal vars prefix with _CODEX_.
#   - All functions prefix with _codex_.
#   - No command execution at source time. The only source-time work is the
#     idempotent path defaulting below, which uses := so it never clobbers a
#     value the caller already set.
#
# Model selection: $CODEX_MODEL overrides the default below.

_CODEX_DEFAULT_MODEL="gpt-6-astra"

# --- Portable roots (set at source time, idempotently) ----------------------
# Shell state does not survive between an agent's separate bash invocations, so
# every block sources this file and gets these for free rather than depending on
# a variable an earlier block set.
#
# TMP_ROOT: where ephemeral stderr/response captures land. Honors TMPDIR/TMP for
#   Windows and container compatibility.
# PLAN_ROOT: where plan files live, for consult mode's plan auto-detection.
#   Only set from CODEX_PLAN_DIR; empty means no auto-detection.
: "${TMP_ROOT:=${TMPDIR:-${TMP:-/tmp}}}"
# macOS exports TMPDIR with a trailing slash; "$TMP_ROOT/x-XXXXXX" would then
# carry a double slash and any consumer comparing paths gets a false mismatch.
TMP_ROOT="${TMP_ROOT%/}"
[ -z "$TMP_ROOT" ] && TMP_ROOT="/"   # a bare "/" collapses to "" above
mkdir -p "$TMP_ROOT" 2>/dev/null || true
: "${PLAN_ROOT:=${CODEX_PLAN_DIR:-}}"

# --- Auth probe -------------------------------------------------------------

_codex_auth_probe() {
  # Multi-signal: env vars OR auth file. A file-only check would falsely reject
  # env-auth users (CI, platform engineers).
  local _codex_home="${CODEX_HOME:-$HOME/.codex}"
  # Strip whitespace before testing: bash's [ -n ] alone accepts a space.
  local _k1 _k2
  _k1=$(printf '%s' "${CODEX_API_KEY:-}" | tr -d '[:space:]')
  _k2=$(printf '%s' "${OPENAI_API_KEY:-}" | tr -d '[:space:]')
  if [ -n "$_k1" ] || [ -n "$_k2" ] || [ -f "$_codex_home/auth.json" ]; then
    echo "AUTH_OK"
    return 0
  fi
  echo "AUTH_FAILED"
  return 1
}

# --- Model round-trip probe -------------------------------------------------

_codex_model_probe() {
  # Auth-exists is a weaker signal than it looks: a ChatGPT account can be valid
  # while the model this skill requests is not entitled to it. A short real round
  # trip catches model rejection in one shot, before four expensive invocations
  # all fail on the same HTTP 400.
  #
  # Contract:
  #   MODEL_OK (exit 0)               — round trip succeeded; cached 1h.
  #   MODEL_UNUSABLE (exit 1)         — deterministic model 400; hints printed.
  #     Cached 15 min: the 400 is entitlement-driven, so re-probing every
  #     preflight would charge a 30s round trip plus real tokens forever.
  #     Editing config.toml (the fix) changes the cache signature and re-probes
  #     immediately; the short TTL covers server-side entitlement recovery that
  #     the signature cannot see.
  #   MODEL_UNUSABLE_INSTALL (exit 2) — the CLI cannot execute at all (spawn
  #     ENOENT, non-executable binary, missing vendor payload). Deterministic,
  #     so fail-open is wrong: retrying never helps. Never cached — a reinstall
  #     must be picked up on the very next probe.
  #   MODEL_PROBE_INCONCLUSIVE (exit 0) — timeout/transient; FAIL-OPEN so a slow
  #     network never wedges the skill. The per-invocation Error Handling entry
  #     still covers a later 400.
  #
  # Only call this AFTER _codex_auth_probe passes — probing without auth just
  # measures the auth failure again.
  local _codex_home="${CODEX_HOME:-$HOME/.codex}"
  local _cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/codex-skill"
  local _cache="$_cache_dir/model-probe"
  local _model="${CODEX_MODEL:-$_CODEX_DEFAULT_MODEL}"
  # Cache signature: config.toml + auth.json mtimes + the model selection.
  # Editing the model or re-logging-in invalidates the cache immediately.
  # GNU stat first: on GNU, `-f` means FILESYSTEM mode and emits a multi-line
  # block, so a BSD-first order made the signature never match its own cache on
  # Linux. BSD stat rejects `-c` cleanly, so GNU-first degrades correctly on macOS.
  local _cfg_m _auth_m _model_sig _sig
  _cfg_m=$(stat -c %Y "$_codex_home/config.toml" 2>/dev/null || stat -f %m "$_codex_home/config.toml" 2>/dev/null || echo 0)
  _auth_m=$(stat -c %Y "$_codex_home/auth.json" 2>/dev/null || stat -f %m "$_codex_home/auth.json" 2>/dev/null || echo 0)
  case "$_cfg_m" in ''|*[!0-9]*) _cfg_m=0 ;; esac
  case "$_auth_m" in ''|*[!0-9]*) _auth_m=0 ;; esac
  _model_sig=$(printf '%s' "$_model" | sed 's/[^A-Za-z0-9._:-]/_/g')
  _sig="${_cfg_m}-${_auth_m}-${_model_sig}"
  local _now
  _now=$(date +%s 2>/dev/null || echo 0)
  if [ -f "$_cache" ]; then
    local _c_line _c_status _c_ts _c_sig
    _c_line=$(head -1 "$_cache" 2>/dev/null)
    _c_status=$(printf '%s' "$_c_line" | cut -d' ' -f1)
    _c_ts=$(printf '%s' "$_c_line" | cut -d' ' -f2)
    _c_sig=$(printf '%s' "$_c_line" | cut -d' ' -f3)
    case "$_c_ts" in ''|*[!0-9]*) _c_ts=0 ;; esac
    if [ "$_c_status" = "MODEL_OK" ] && [ "$_c_sig" = "$_sig" ] && [ $((_now - _c_ts)) -lt 3600 ]; then
      echo "MODEL_OK (cached)"
      return 0
    fi
    if [ "$_c_status" = "MODEL_UNUSABLE" ] && [ "$_c_sig" = "$_sig" ] && [ $((_now - _c_ts)) -lt 900 ]; then
      echo "MODEL_UNUSABLE (cached)"
      echo "HINT: requested model '$_model'."
      echo "HINT: set CODEX_MODEL=<supported-model> or pass an explicit -c model=... override."
      return 1
    fi
  fi
  local _out _code
  _out=$(_codex_timeout_wrapper 30 codex exec --skip-git-repo-check -s read-only -c "model=\"$_model\"" "reply OK" </dev/null 2>&1)
  _code=$?
  if [ "$_code" -eq 0 ]; then
    mkdir -p "$_cache_dir" 2>/dev/null || true
    printf 'MODEL_OK %s %s\n' "$_now" "$_sig" > "$_cache" 2>/dev/null || true
    echo "MODEL_OK"
    return 0
  fi
  if printf '%s' "$_out" | grep -qiE 'model.{0,40}is not supported|"status":[[:space:]]*400'; then
    mkdir -p "$_cache_dir" 2>/dev/null || true
    printf 'MODEL_UNUSABLE %s %s\n' "$_now" "$_sig" > "$_cache" 2>/dev/null || true
    echo "MODEL_UNUSABLE"
    printf '%s\n' "$_out" | grep -i "model" | head -3
    echo "HINT: requested model '$_model'."
    echo "HINT: set CODEX_MODEL=<supported-model> or pass an explicit -c model=... override."
    return 1
  fi
  # A CLI that cannot execute is deterministic, not transient: the fail-open
  # below exists for network luck. Swallowing this here is what lets a missing
  # vendor binary report "ready" while every Codex pass is silently skipped.
  # 126 = found but not executable, 127 = not found.
  # String signatures only count on a FAILED, NON-TIMEOUT spawn: a successful
  # response that happens to mention "permission denied" must not classify as
  # broken, and neither may a timed-out (124) probe whose partial output quotes
  # such strings — 124 keeps its fail-open contract below.
  _CODEX_BROKEN_SIG='ENOENT|ENOEXEC|EACCES|no such file or directory|cannot execute binary file|not executable|permission denied'
  if [ "$_code" -eq 126 ] || [ "$_code" -eq 127 ] || { [ "$_code" -ne 0 ] && [ "$_code" -ne 124 ] && printf '%s' "$_out" | grep -qiE "$_CODEX_BROKEN_SIG"; }; then
    echo "MODEL_UNUSABLE_INSTALL"
    printf '%s\n' "$_out" | grep -iE "$_CODEX_BROKEN_SIG" | head -3
    echo "HINT: the Codex CLI is on PATH but cannot run — its binary or vendor payload is missing."
    echo "HINT: reinstall with: npm install -g @openai/codex"
    return 2
  fi
  # Timeout (124) or transient failure: fail-open with a warning. The probe
  # exists to catch the deterministic model 400, not to gate on network luck.
  echo "MODEL_PROBE_INCONCLUSIVE (exit $_code) — proceeding; if invocations fail with a model 400, see the skill's Error Handling section."
  return 0
}

# --- Version check ----------------------------------------------------------

_codex_version_check() {
  # Warn on known-bad Codex CLI versions. The anchored regex prevents false
  # positives like 0.120.10 or 0.120.20. 0.120.2-beta still matches the bad
  # release and gets warned (it IS buggy).
  # Update this list when a new Codex CLI version regresses.
  local _ver _vcode
  # Capture the exit code from codex, not from `head`: a pipeline reports the
  # LAST command's status, which is how a CLI that only ever printed a spawn
  # error still read as healthy. Keep stderr — it carries the diagnosis.
  _ver=$(codex --version 2>&1)
  _vcode=$?
  _ver=$(printf '%s' "$_ver" | head -1)
  # Only a NON-ZERO exit is evidence of a broken CLI. Empty-but-successful
  # output stays silent by design; a CLI may legitimately print nothing.
  if [ "$_vcode" -ne 0 ]; then
    echo "WARN: \`codex --version\` failed (exit $_vcode) — the CLI is on PATH but may not be runnable."
    [ -n "$_ver" ] && echo "WARN: it said: $_ver"
    echo "WARN: if Codex passes are being skipped, reinstall with: npm install -g @openai/codex"
    return 0
  fi
  [ -z "$_ver" ] && return 0
  if echo "$_ver" | grep -Eq '(^|[^0-9.])0\.120\.(0|1|2)([^0-9.]|$)'; then
    echo "WARN: Codex CLI $_ver has known stdin deadlock bugs. Run: npm install -g @openai/codex@latest"
  fi
}

# --- Timeout wrapper --------------------------------------------------------

_codex_timeout_wrapper() {
  # Resolve a wrapper binary: prefer gtimeout (Homebrew coreutils on macOS),
  # fall back to timeout (Linux), else a bash-native watchdog.
  # $1 is the duration in seconds; the rest is the command to run.
  local _duration="$1"
  shift
  local _to
  _to=$(command -v gtimeout 2>/dev/null || command -v timeout 2>/dev/null || echo "")
  if [ -n "$_to" ]; then
    "$_to" "$_duration" "$@"
  else
    # Stock macOS ships neither gtimeout nor timeout(1); running unwrapped lets
    # a hung `codex exec` block the caller indefinitely. Emulate: background the
    # command, TERM it at the deadline, mirror timeout(1)'s exit-124 contract.
    # The watchdog's stdout is detached so an early finish never blocks a
    # caller's $(...) capture on the orphaned sleep.
    # Explicit <&0: POSIX sh gives a background job /dev/null as stdin, which
    # would drop a prompt piped in on stdin.
    "$@" <&0 &
    local _cmd_pid=$!
    ( sleep "$_duration" && kill -TERM "$_cmd_pid" 2>/dev/null ) >/dev/null 2>&1 &
    local _watch_pid=$!
    local _rc
    wait "$_cmd_pid"
    _rc=$?
    if kill -0 "$_watch_pid" 2>/dev/null; then
      # The command finished before the deadline. Retiring the watchdog subshell
      # also defuses its pending kill (the `&& kill` lives in the subshell); its
      # detached sleep expires harmlessly.
      kill "$_watch_pid" 2>/dev/null
      wait "$_watch_pid" 2>/dev/null
    elif [ "$_rc" -ge 128 ]; then
      _rc=124  # killed by the watchdog: report timeout(1)'s code
    fi
    return "$_rc"
  fi
}
