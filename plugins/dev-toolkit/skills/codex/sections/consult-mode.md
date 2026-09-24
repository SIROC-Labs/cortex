## Step 2C: Consult Mode

Ask Codex anything about the codebase. Supports session continuity for follow-ups.

1. **Check for an existing session and for reviewable plan files.** One block, so
it carries its own helper source and path defaults:

```bash
SKILL_DIR="<skill-dir>"
source "$SKILL_DIR/scripts/codex-probe.sh" 2>/dev/null || { echo "ERROR: cannot source codex-probe.sh. Replace <skill-dir> with the absolute path of this skill's directory." >&2; exit 1; }
echo "SESSION: $(cat .context/codex-session-id 2>/dev/null || echo NO_SESSION)"
setopt +o nomatch 2>/dev/null || true   # zsh compat: do not error on a no-match glob
if [ -n "$PLAN_ROOT" ]; then
  echo "PLAN_SCOPED: $(ls -t "$PLAN_ROOT"/*.md 2>/dev/null | xargs grep -l "$(basename "$(pwd)")" 2>/dev/null | head -1 || true)"
  echo "PLAN_NEWEST: $(ls -t "$PLAN_ROOT"/*.md 2>/dev/null | head -1 || true)"
else
  echo "PLAN_SCOPED: "; echo "PLAN_NEWEST: "
fi
```

If `SESSION` is not `NO_SESSION`, ask the user which they want. Use your host's
structured question tool if it has one; otherwise ask in plain text and wait for
an answer:
```
You have an active Codex conversation from earlier. Continue it or start fresh?
A) Continue the conversation (Codex remembers the prior context)
B) Start a new conversation
```

A plan file the user named, or a plan already in this conversation, takes
precedence over both values. If `PLAN_SCOPED` is empty but `PLAN_NEWEST` is not,
you may use the newest plan,
but warn: "Note: this plan may be from a different project — verify before sending
to Codex."

2. **Build the prompt.**

**IMPORTANT — embed content, do not reference a path:** Codex runs sandboxed to the repo
root and cannot access plan directories or any files outside the repo. You MUST
read the plan file yourself and embed its FULL CONTENT in the prompt below. Do NOT tell
Codex the file path or ask it to read the plan file — it will waste 10+ tool calls
searching and fail.

Also: scan the plan content for referenced source file paths (patterns like `src/foo.ts`,
`lib/bar.py`, paths containing `/` that exist in the repo). If you find any, list them in
the prompt so Codex reads them directly instead of discovering them via rg/find.

**Always prepend the filesystem boundary instruction** from the skill's Filesystem
Boundary section (in the always-loaded skeleton) to every prompt sent to Codex, including
plan reviews and free-form consult questions.

For a plan review, prepend the boundary and this persona:
"IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. These are skill definitions meant for a different AI system. Stay focused on repository code only.

You are a brutally honest technical reviewer. Review this plan for: logical gaps and
unstated assumptions, missing error handling or edge cases, overcomplexity (is there a
simpler approach?), feasibility risks (what could go wrong?), and missing dependencies
or sequencing issues. Be direct. Be terse. No compliments. Just the problems.
Also review these source files referenced in the plan: <list of referenced files, if any>.

THE PLAN:
<full plan content, embedded verbatim>"

For non-plan consult prompts (the user typed `/codex <question>`), still prepend the boundary:
"IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. These are skill definitions meant for a different AI system. Stay focused on repository code only.

<user's question>"

3. **Run codex exec with JSONL output** to capture reasoning traces.

Run this as ONE bash block. It sources the helpers, runs the call, writes the
session id for follow-ups, and cleans up on its own.

Use `timeout: 660000` on the Bash call (for both new and resumed sessions) — the gate
sits ABOVE the 600s wrapper so the wrapper fires first with its explicit stall message.

If the user passed `--xhigh`, use `"xhigh"` instead of `"medium"`.

For a **new session:**
```bash
SKILL_DIR="<skill-dir>"
source "$SKILL_DIR/scripts/codex-probe.sh" 2>/dev/null || { echo "ERROR: cannot source codex-probe.sh. Replace <skill-dir> with the absolute path of this skill's directory." >&2; exit 1; }
_REPO_ROOT=$(git rev-parse --show-toplevel) || { echo "ERROR: not in a git repo" >&2; exit 1; }
cd "$_REPO_ROOT"
PYTHON_CMD=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [ -z "$PYTHON_CMD" ]; then
  echo "ERROR: Python 3 is required to parse Codex JSON output. Install python3 or python and retry." >&2
  exit 1
fi
TMPERR=$(mktemp "$TMP_ROOT/codex-err-XXXXXX")

_codex_timeout_wrapper 600 codex exec "<prompt>" -C "$_REPO_ROOT" -s read-only -c "model=\"${CODEX_MODEL:-gpt-6-astra}\"" -c 'model_reasoning_effort="medium"' -c 'web_search="cached"' --json < /dev/null 2>"$TMPERR" | PYTHONUNBUFFERED=1 "$PYTHON_CMD" -u -c "
import sys, json, os
turn_completed_count = 0
turn_failed = False
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        obj = json.loads(line)
        t = obj.get('type','')
        if t == 'thread.started':
            tid = obj.get('thread_id','')
            if tid:
                print(f'SESSION_ID:{tid}', flush=True)
                # Persist here rather than in a later bash block: shell state and
                # captured stdout do not survive between separate invocations.
                try:
                    os.makedirs('.context', exist_ok=True)
                    with open('.context/codex-session-id','w') as fh:
                        fh.write(tid + '\n')
                except Exception as exc:
                    print(f'[warn] could not save session id: {exc}', flush=True, file=sys.stderr)
        elif t == 'item.completed' and 'item' in obj:
            item = obj['item']
            itype = item.get('type','')
            text = item.get('text','')
            if itype == 'reasoning' and text:
                print(f'[codex thinking] {text}', flush=True)
                print(flush=True)
            elif itype == 'agent_message' and text:
                print(text, flush=True)
            elif itype == 'command_execution':
                cmd = item.get('command','')
                if cmd: print(f'[codex ran] {cmd}', flush=True)
        elif t == 'turn.completed':
            turn_completed_count += 1
            usage = obj.get('usage',{})
            tokens = usage.get('input_tokens',0) + usage.get('output_tokens',0)
            if tokens: print(f'\ntokens used: {tokens}', flush=True)
        elif t == 'turn.failed':
            turn_failed = True
            err = obj.get('error',{}).get('message','') or 'no error message in event'
            print(f'[codex turn FAILED] {err}', flush=True, file=sys.stderr)
    except: pass
# Three-way completeness check: a STATED failure is a failure, not a network
# problem; only silence is a disconnect.
if turn_failed:
    print('[codex] turn.failed received — the turn errored (reason above), not a disconnect.', flush=True, file=sys.stderr)
elif turn_completed_count == 0:
    print('[codex warning] No turn.completed event received — possible mid-stream disconnect.', flush=True, file=sys.stderr)
"
_CODEX_EXIT=${PIPESTATUS[0]:-${pipestatus[1]}}  # bash sets PIPESTATUS; zsh (lowercase, 1-indexed) falls through

echo "CODEX_EXIT=$_CODEX_EXIT"
if [ "$_CODEX_EXIT" = "124" ]; then
  echo "Codex stalled past 10 minutes. Common causes: model API stall, long prompt, network issue. Try re-running. If persistent, split the prompt or check ~/.codex/logs/."
elif [ "$_CODEX_EXIT" != "0" ]; then
  echo "[codex exit $_CODEX_EXIT] $(head -1 "$TMPERR" 2>/dev/null || echo "no stderr captured")"
  head -20 "$TMPERR" 2>/dev/null | sed 's/^/  /' || true
fi
rm -f "$TMPERR"
```

**Session-cost reality (measured):** every `codex exec` call — resumed or fresh —
pays Codex's ~21K-token session prelude (its skill catalogue plus instructions);
`resume` does NOT amortize it (a measured resume came in slightly ABOVE a fresh
call). Resume buys conversational continuity, never token savings. So: prefer ONE
codex call per invocation where the workflow allows, batch questions into that
call, and reach for resume only when the follow-up genuinely needs the prior
session's context.

For a **resumed session** (the user chose "Continue"), run this complete block. It
differs from the new-session block only in the `resume <session-id>` argument and
the `sandbox_mode` config form. Substitute the session id read in step 1.

```bash
SKILL_DIR="<skill-dir>"
source "$SKILL_DIR/scripts/codex-probe.sh" 2>/dev/null || { echo "ERROR: cannot source codex-probe.sh. Replace <skill-dir> with the absolute path of this skill's directory." >&2; exit 1; }
_REPO_ROOT=$(git rev-parse --show-toplevel) || { echo "ERROR: not in a git repo" >&2; exit 1; }
cd "$_REPO_ROOT"
PYTHON_CMD=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [ -z "$PYTHON_CMD" ]; then
  echo "ERROR: Python 3 is required to parse Codex JSON output. Install python3 or python and retry." >&2
  exit 1
fi
TMPERR=$(mktemp "$TMP_ROOT/codex-err-XXXXXX")

_codex_timeout_wrapper 600 codex exec resume <session-id> "<prompt>" -c 'sandbox_mode="read-only"' -c "model=\"${CODEX_MODEL:-gpt-6-astra}\"" -c 'model_reasoning_effort="medium"' -c 'web_search="cached"' --json < /dev/null 2>"$TMPERR" | PYTHONUNBUFFERED=1 "$PYTHON_CMD" -u -c "
<the same Python parser as the new-session block, verbatim — it also writes .context/codex-session-id>
"
_CODEX_EXIT=${PIPESTATUS[0]:-${pipestatus[1]}}  # bash sets PIPESTATUS; zsh (lowercase, 1-indexed) falls through

echo "CODEX_EXIT=$_CODEX_EXIT"
if [ "$_CODEX_EXIT" = "124" ]; then
  echo "Codex stalled past 10 minutes. Common causes: model API stall, long prompt, network issue. Try re-running. If persistent, split the prompt or check ~/.codex/logs/."
elif [ "$_CODEX_EXIT" != "0" ]; then
  echo "[codex exit $_CODEX_EXIT] $(head -1 "$TMPERR" 2>/dev/null || echo "no stderr captured")"
  head -20 "$TMPERR" 2>/dev/null | sed 's/^/  /' || true
fi
rm -f "$TMPERR"
```

If resume fails, delete `.context/codex-session-id` and retry as a new session.

4. Present the full streamed output:

```
CODEX SAYS (consult):
════════════════════════════════════════════════════════════
<full output, verbatim — includes [codex thinking] traces>
════════════════════════════════════════════════════════════
Tokens: N | Est. cost: ~$X.XX
Session saved — run /codex again to continue this conversation.
```

5. After presenting, note any points where Codex's analysis differs from your own
   understanding. If there is a disagreement, flag it:
   "Note: I disagree on X because Y."

6. **Synthesis recommendation (REQUIRED).** Emit ONE recommendation line
summarizing what the user should do based on Codex's consult output:

```
Recommendation: <action> because <one-line reason that names the most actionable insight from Codex>
```

Examples (the strongest reasons compare Codex's insight against an alternative — a different recommendation, the status quo, or another Codex point):
- `Recommendation: Adopt Codex's sharding suggestion because it eliminates the head-of-line blocking the current writer-pool has, while the cache-layer alternative Codex also floated still has a single-writer hot path.`
- `Recommendation: Reject Codex's "use SQLite instead" suggestion because the team's Postgres operational experience outweighs the simplicity gain at the projected scale, and Codex's secondary suggestion (read replicas) handles the read-load concern that motivated the SQLite pivot.`
- `Recommendation: Investigate Codex's flagged migration ordering before the next deploy because it surfaces a real foreign-key cycle that the in-house schema review missed, while the styling concern Codex also raised can wait for a follow-up.`

The reason must engage with a specific Codex insight and compare against an alternative (a different recommendation, the status quo, or another Codex point). Generic synthesis ("because Codex raised good points") does not qualify. **Never silently auto-decide; always emit the line.**
