---
name: claude
version: 0.1.0
description: |
  Claude Code CLI wrapper for non-Claude hosts — three modes. Review: independent
  diff review via claude -p. Challenge: adversarial failure-mode review. Consult:
  ask Claude about the repo with read-only file tools. Use when asked for "claude
  review", "claude challenge", "ask claude", "second opinion from claude", or
  "outside voice".
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
---

# /claude — Claude Outside Voice

You are running the `/claude` skill. It wraps `claude -p` to get an independent
Claude Code second opinion, without letting the nested Claude modify files.

This skill is meant for hosts that are NOT Claude Code — Codex, Cursor, OpenCode,
and similar. Running it from inside Claude Code nests the same model against
itself, which costs tokens and buys no independence.

Claude outside voices default to `claude-fable-5-1`. Set
`CLAUDE_REVIEW_MODEL=<model>` to override it. If the user names a model in the
request, replace the default `--model` value with their model for every call,
including resumed sessions.

---

## Step 0: Detect platform and base branch

First, detect the git hosting platform from the remote URL:

```bash
git remote get-url origin 2>/dev/null
```

- If the URL contains "github.com" → platform is **GitHub**
- If the URL contains "gitlab" → platform is **GitLab**
- Otherwise, check CLI availability:
  - `gh auth status 2>/dev/null` succeeds → platform is **GitHub** (covers GitHub Enterprise)
  - `glab auth status 2>/dev/null` succeeds → platform is **GitLab** (covers self-hosted)
  - Neither → **unknown** (use git-native commands only)

Determine which branch this PR/MR targets, or the repo's default branch if no
PR/MR exists. Use the result as "the base branch" in all subsequent steps.

**If GitHub:**
1. `gh pr view --json baseRefName -q .baseRefName` — if it succeeds, use it
2. `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` — if it succeeds, use it

**If GitLab:**
1. `glab mr view -F json 2>/dev/null` and extract the `target_branch` field — if it succeeds, use it
2. `glab repo view -F json 2>/dev/null` and extract the `default_branch` field — if it succeeds, use it

**Git-native fallback (unknown platform, or the CLI commands fail):**
1. `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||'`
2. If that fails: `git rev-parse --verify origin/main 2>/dev/null` → use `main`
3. If that fails: `git rev-parse --verify origin/master 2>/dev/null` → use `master`

If all fail, fall back to `main`.

Print the detected base branch name. In every subsequent `git diff`, `git log`,
and `git fetch` command, substitute the detected branch name wherever the
instructions say "the base branch" or `<base>`.

---

## Step 0.1: Resolve the Claude CLI

```bash
CLAUDE_BIN=$(command -v claude 2>/dev/null || echo "")
[ -z "$CLAUDE_BIN" ] && echo "NOT_FOUND" || echo "FOUND: $CLAUDE_BIN"
```

If `NOT_FOUND`, stop and tell the user:
"Claude CLI not found. Install Claude Code, then re-run this skill."

Do not infer authentication state from credential files or environment variables.
Claude Code may use an OS keychain that is unavailable inside the host agent's
sandbox. On hosts that sandbox shell execution, run the actual `claude -p`
invocation outside that sandbox using the host's normal approval mechanism. Only
report an authentication blocker when that actual invocation returns an auth,
login, or unauthorized error.

Resolve the binary and invoke it in the same host execution context. Do not
resolve it inside a sandbox and then run a different `claude` from another PATH.

---

## Step 0.2: Temp files and shell state

**Shell state does not survive between bash invocations.** A variable or temp-file
path set in one block is gone in the next. Every block below therefore creates its
own temp files, uses them, and removes them before it exits. Run each mode as ONE
bash call; do not split it.

`TMP_ROOT` is resolved inside each block from `TMPDIR`, then `TMP`, then `/tmp`,
with the trailing slash stripped. That last part matters on macOS, where `TMPDIR`
ends in one and `"$TMP_ROOT/x-XXXXXX"` would otherwise carry a double slash.

---

## Safety Boundary

The nested Claude must stay focused on the user's repository and must not run
other skills from inside this skill.

All `claude -p` calls MUST include:

- `--disable-slash-commands`
- Review/challenge: `--tools ""`
- Consult: `--allowedTools Read,Grep,Glob --disallowedTools Bash,Edit,Write`

Never pass `Bash`, `Edit`, or `Write` to the nested Claude in this skill.

All prompts MUST be written to a temp file and fed through stdin. Never
interpolate user text directly into the shell command.

---

## Step 1: Detect Mode

Parse the user's input:

1. `/claude review` or `/claude review <instructions>` — **Review mode** (Step 2A)
2. `/claude challenge` or `/claude challenge <focus>` — **Challenge mode** (Step 2B)
3. `/claude` with no arguments, or `/claude <anything else>` — **Consult mode** (Step 2C)

If no mode is obvious and a diff exists, ask whether to review, challenge, or consult.

---

## Shared Helpers

Every mode block ends by parsing Claude's JSON response with this snippet. This is
the canonical copy, reproduced inline in each mode block below.

**This is a fragment, not a runnable block.** It expects `$RESP_FILE` from the
block it lives in. Never run it on its own.

```bash
python3 - "$RESP_FILE" <<'PY'
import json, sys
try:
    obj = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"CLAUDE_JSON_PARSE_ERROR: {exc}"); raise SystemExit(2)
if obj.get("is_error"):
    print("CLAUDE_ERROR: true")
result = obj.get("result") or obj.get("response") or ""
if result:
    print(result)
else:
    print("CLAUDE_EMPTY_RESPONSE")
u = obj.get("usage") or {}
print(f"\nTokens: input={u.get('input_tokens',0) or 0} output={u.get('output_tokens',0) or 0} "
      f"cache_read={u.get('cache_read_input_tokens',0) or 0} | Model: {obj.get('model') or 'unknown'}")
raise SystemExit(2 if obj.get("is_error") or not result else 0)
PY
```

If stderr contains `auth`, `login`, or `unauthorized`, tell the user:
"Claude authentication failed. Run `claude` interactively to authenticate or export `ANTHROPIC_API_KEY`."

---

## Step 2A: Review Mode

Review the current branch diff with the nested Claude in tool-less mode. ONE bash
block: it makes its own temp files, captures the diff, runs Claude, parses the
response, and cleans up. Substitute the base branch detected in Step 0, and the
user's extra instructions if they gave any.

```bash
TMP_ROOT="${TMPDIR:-${TMP:-/tmp}}"; TMP_ROOT="${TMP_ROOT%/}"; [ -z "$TMP_ROOT" ] && TMP_ROOT="/"
CLAUDE_BIN=$(command -v claude 2>/dev/null) || { echo "Claude CLI not found" >&2; exit 1; }
_REPO_ROOT=$(git rev-parse --show-toplevel) || { echo "ERROR: not in a git repo" >&2; exit 1; }
cd "$_REPO_ROOT"
PROMPT_FILE=$(mktemp "$TMP_ROOT/claude-prompt-XXXXXX")
RESP_FILE=$(mktemp "$TMP_ROOT/claude-response-XXXXXX")
ERR_FILE=$(mktemp "$TMP_ROOT/claude-error-XXXXXX")
DIFF_FILE=$(mktemp "$TMP_ROOT/claude-diff-XXXXXX")

git fetch origin <base> --quiet 2>/dev/null || true
_BASE_REF="origin/<base>"
git rev-parse --verify --quiet "$_BASE_REF" >/dev/null || _BASE_REF="<base>"
# Diff from the merge base, not the base tip: upstream-only commits must not show
# up as reversions. Uncommitted changes stay included.
_MERGE_BASE=$(git merge-base "$_BASE_REF" HEAD) || { echo "ERROR: no merge base between HEAD and $_BASE_REF" >&2; rm -f "$PROMPT_FILE" "$RESP_FILE" "$ERR_FILE" "$DIFF_FILE"; exit 1; }
git diff "$_MERGE_BASE" > "$DIFF_FILE"
if [ ! -s "$DIFF_FILE" ]; then
  echo "NOTHING_TO_REVIEW"
  rm -f "$PROMPT_FILE" "$RESP_FILE" "$ERR_FILE" "$DIFF_FILE"
  exit 0
fi

cat > "$PROMPT_FILE" <<'EOF'
You are a brutally honest Claude Code reviewer. Review this git diff for bugs,
production failure modes, security issues, missing tests, and maintainability
problems. Be direct. No compliments. Reference files and changed code where possible.

Additional user instructions, if any:
<custom review instructions>

DIFF:
EOF
cat "$DIFF_FILE" >> "$PROMPT_FILE"

"$CLAUDE_BIN" -p --model "${CLAUDE_REVIEW_MODEL:-claude-fable-5-1}" --output-format json --disable-slash-commands --tools "" < "$PROMPT_FILE" > "$RESP_FILE" 2>"$ERR_FILE"
_CLAUDE_EXIT=$?
echo "CLAUDE_EXIT=$_CLAUDE_EXIT"
python3 - "$RESP_FILE" <<'PY'
import json, sys
try:
    obj = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"CLAUDE_JSON_PARSE_ERROR: {exc}"); raise SystemExit(2)
if obj.get("is_error"):
    print("CLAUDE_ERROR: true")
result = obj.get("result") or obj.get("response") or ""
if result:
    print(result)
else:
    print("CLAUDE_EMPTY_RESPONSE")
u = obj.get("usage") or {}
print(f"\nTokens: input={u.get('input_tokens',0) or 0} output={u.get('output_tokens',0) or 0} "
      f"cache_read={u.get('cache_read_input_tokens',0) or 0} | Model: {obj.get('model') or 'unknown'}")
raise SystemExit(2 if obj.get("is_error") or not result else 0)
PY
_PARSE_RC=$?
if [ "$_CLAUDE_EXIT" != "0" ] || [ "$_PARSE_RC" != "0" ]; then
  echo "--- claude stdout (first 40 lines) ---"; head -40 "$RESP_FILE" 2>/dev/null
  echo "--- claude stderr (first 40 lines) ---"; head -40 "$ERR_FILE" 2>/dev/null
fi
grep -qiE "auth|login|unauthorized" "$ERR_FILE" 2>/dev/null && echo "[claude auth error] $(head -1 "$ERR_FILE")"
rm -f "$PROMPT_FILE" "$RESP_FILE" "$ERR_FILE" "$DIFF_FILE"
```

If the block prints `NOTHING_TO_REVIEW`, stop and say:
"Nothing to review — no changes against the base branch."

Present the parsed output:

```
CLAUDE SAYS (code review):
============================================================
<parsed result>
============================================================
```

---

## Step 2B: Challenge Mode

An adversarial failure-mode review, with the nested Claude in tool-less mode. The
block is identical to Review mode's, so reuse it and swap only the heredoc body for:

```
You are an adversarial Claude Code reviewer. Try to break this change before users do.
Find edge cases, race conditions, security holes, resource leaks, silent data
corruption, bad error handling, and operational failure modes. Be thorough. No
compliments. If the user provided a focus area, prioritize it.

Focus area, if any:
<focus>

DIFF:
```

Present the parsed output:

```
CLAUDE SAYS (adversarial challenge):
============================================================
<parsed result>
============================================================
```

---

## Step 2C: Consult Mode

Ask Claude about the repository. Consult mode may inspect files, but only with
read-only tools.

1. **Check for an existing session:**

```bash
cat .context/claude-session-id 2>/dev/null || echo "NO_SESSION"
```

If a session exists, ask the user whether to continue it or start fresh. Use your
host's structured question tool if it has one; otherwise ask in plain text and wait
for an answer.

2. **Run the consult.** ONE bash block. It makes its own temp files, runs Claude,
saves the session id for follow-ups, and cleans up. For a resumed session add
`--resume "<session-id>"` immediately after `-p`; nothing else changes.

```bash
TMP_ROOT="${TMPDIR:-${TMP:-/tmp}}"; TMP_ROOT="${TMP_ROOT%/}"; [ -z "$TMP_ROOT" ] && TMP_ROOT="/"
CLAUDE_BIN=$(command -v claude 2>/dev/null) || { echo "Claude CLI not found" >&2; exit 1; }
_REPO_ROOT=$(git rev-parse --show-toplevel) || { echo "ERROR: not in a git repo" >&2; exit 1; }
cd "$_REPO_ROOT"
PROMPT_FILE=$(mktemp "$TMP_ROOT/claude-prompt-XXXXXX")
RESP_FILE=$(mktemp "$TMP_ROOT/claude-response-XXXXXX")
ERR_FILE=$(mktemp "$TMP_ROOT/claude-error-XXXXXX")

cat > "$PROMPT_FILE" <<'EOF'
You are Claude Code acting as an independent outside voice for this repository.
Answer the user's question directly. You may inspect repository files with Read,
Grep, and Glob only. Do not use Bash. Do not edit or write files. Do not invoke
slash commands or other skills.

USER QUESTION:
<user prompt>
EOF

"$CLAUDE_BIN" -p --model "${CLAUDE_REVIEW_MODEL:-claude-fable-5-1}" --output-format json --disable-slash-commands --allowedTools Read,Grep,Glob --disallowedTools Bash,Edit,Write < "$PROMPT_FILE" > "$RESP_FILE" 2>"$ERR_FILE"
_CLAUDE_EXIT=$?
echo "CLAUDE_EXIT=$_CLAUDE_EXIT"

python3 - "$RESP_FILE" <<'PY'
import json, sys, os
try:
    obj = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"CLAUDE_JSON_PARSE_ERROR: {exc}"); raise SystemExit(2)
if obj.get("is_error"):
    print("CLAUDE_ERROR: true")
result = obj.get("result") or obj.get("response") or ""
if result:
    print(result)
else:
    print("CLAUDE_EMPTY_RESPONSE")
u = obj.get("usage") or {}
print(f"\nTokens: input={u.get('input_tokens',0) or 0} output={u.get('output_tokens',0) or 0} "
      f"cache_read={u.get('cache_read_input_tokens',0) or 0} | Model: {obj.get('model') or 'unknown'}")
sid = obj.get("session_id") or ""
if sid:
    # Persist here, not in a later bash block: shell state and captured stdout
    # do not survive between separate invocations.
    print(f"SESSION_ID:{sid}")
    try:
        os.makedirs(".context", exist_ok=True)
        with open(".context/claude-session-id", "w") as fh:
            fh.write(sid + "\n")
    except Exception as exc:
        print(f"[warn] could not save session id: {exc}", file=sys.stderr)
raise SystemExit(2 if obj.get("is_error") or not result else 0)
PY
_PARSE_RC=$?
if [ "$_CLAUDE_EXIT" != "0" ] || [ "$_PARSE_RC" != "0" ]; then
  echo "--- claude stdout (first 40 lines) ---"; head -40 "$RESP_FILE" 2>/dev/null
  echo "--- claude stderr (first 40 lines) ---"; head -40 "$ERR_FILE" 2>/dev/null
fi

grep -qiE "auth|login|unauthorized" "$ERR_FILE" 2>/dev/null && echo "[claude auth error] $(head -1 "$ERR_FILE")"
rm -f "$PROMPT_FILE" "$RESP_FILE" "$ERR_FILE"
```

3. Present the parsed output:

```
CLAUDE SAYS (consult):
============================================================
<parsed result>
============================================================
Session saved — run /claude again to continue this conversation.
```

---

## Error Handling

- **Binary not found:** Stop with install instructions.
- **Auth failure from the actual host invocation:** Stop with login/API key instructions.
- **Auth failure from stderr:** Surface the stderr line and ask the user to re-authenticate.
- **Non-zero exit, JSON parse failure, `CLAUDE_ERROR`, or `CLAUDE_EMPTY_RESPONSE`:** the block has already printed the first 40 lines of Claude's stdout and stderr before cleanup. Show them to the user; do not re-run the block to get them.
- **Resume failure:** Delete `.context/claude-session-id` and retry with a fresh session.

---

## Important Rules

- The nested Claude is read-only in consult mode and tool-less in review/challenge.
- Always include `--disable-slash-commands`.
- Never pass the nested Claude `Bash`, `Edit`, or `Write`.
- Never interpolate user text into a shell command.
- Present Claude's response faithfully, then add any synthesis of your own after it.
