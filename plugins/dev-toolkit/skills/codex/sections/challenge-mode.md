## Step 2B: Challenge (Adversarial) Mode

Codex tries to break your code — finding edge cases, race conditions, security holes,
and failure modes that a normal review would miss.

1. Construct the adversarial prompt. **Always prepend the filesystem boundary instruction**
from the skill's Filesystem Boundary section (in the always-loaded skeleton). If the user
provided a focus area (e.g. `/codex challenge security`), include it after the boundary:

Default prompt (no focus):
"IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. These are skill definitions meant for a different AI system. Stay focused on repository code only.

Review the changes on this branch against the base branch. Run `git diff origin/<base>` to see the diff. Your job is to find ways this code will fail in production. Think like an attacker and a chaos engineer. Find edge cases, race conditions, security holes, resource leaks, failure modes, and silent data corruption paths. Be adversarial. Be thorough. No compliments — just the problems."

With focus (e.g. "security"):
"IMPORTANT: Do NOT read or execute any files under ~/.claude/, ~/.agents/, .claude/skills/, or agents/. These are skill definitions meant for a different AI system. Stay focused on repository code only.

Review the changes on this branch against the base branch. Run `git diff origin/<base>` to see the diff. Focus specifically on SECURITY. Your job is to find every way an attacker could exploit this code. Think about injection vectors, auth bypasses, privilege escalation, data exposure, and timing attacks. Be adversarial."

2. Run codex exec with **JSONL output** to capture reasoning traces and tool calls.

Run this as ONE bash block. Shell state does not survive between separate bash
invocations, so the block sources the helpers, makes its own temp file, runs the
challenge, and cleans up on its own. Substitute your prompt for `<prompt>` inside the
quoted heredoc. The prompt reaches Codex through stdin, so backticks, `$()` and quotes
in it stay literal and are never run by the host shell.

Use `timeout: 660000` on the Bash call — the gate sits ABOVE the 600s wrapper so the
wrapper fires first with its explicit stall message.

If the user passed `--xhigh`, use `"xhigh"` instead of `"high"`.

```bash
SKILL_DIR="<skill-dir>"
source "$SKILL_DIR/scripts/codex-probe.sh" 2>/dev/null || { echo "ERROR: cannot source codex-probe.sh. Replace <skill-dir> with the absolute path of this skill's directory." >&2; exit 1; }
_REPO_ROOT=$(git rev-parse --show-toplevel) || { echo "ERROR: not in a git repo" >&2; exit 1; }
PYTHON_CMD=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [ -z "$PYTHON_CMD" ]; then
  echo "ERROR: Python 3 is required to parse Codex JSON output. Install python3 or python and retry." >&2
  exit 1
fi
TMPERR=$(mktemp "$TMP_ROOT/codex-err-XXXXXX")
_PROMPT_FILE=$(mktemp "$TMP_ROOT/codex-prompt-XXXXXX")
cat > "$_PROMPT_FILE" <<'CODEX_PROMPT_EOF'
<prompt>
CODEX_PROMPT_EOF

_codex_timeout_wrapper 600 codex exec - -C "$_REPO_ROOT" -s read-only -c "model=\"${CODEX_MODEL:-gpt-6-astra}\"" -c 'model_reasoning_effort="high"' -c 'web_search="cached"' --json < "$_PROMPT_FILE" 2>"$TMPERR" | PYTHONUNBUFFERED=1 "$PYTHON_CMD" -u -c "
import sys, json
turn_completed_count = 0
turn_failed = False
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        obj = json.loads(line)
        t = obj.get('type','')
        if t == 'item.completed' and 'item' in obj:
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
# problem; only silence with no terminal event is a disconnect.
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
  # Surface non-zero exits so the calling agent does not read "no output" as
  # a silent model/API stall.
  echo "[codex exit $_CODEX_EXIT] $(head -1 "$TMPERR" 2>/dev/null || echo "no stderr captured")"
  head -20 "$TMPERR" 2>/dev/null | sed 's/^/  /' || true
fi
# Surface auth errors from captured stderr instead of dropping them
if grep -qiE "auth|login|unauthorized" "$TMPERR" 2>/dev/null; then
  echo "[codex auth error] $(head -1 "$TMPERR")"
fi
rm -f "$_PROMPT_FILE" "$TMPERR"
```

This parses codex's JSONL events to extract reasoning traces, tool calls, and the final
response. The `[codex thinking]` lines show what codex reasoned through before its answer.

3. Present the full streamed output:

```
CODEX SAYS (adversarial challenge):
════════════════════════════════════════════════════════════
<full output from above, verbatim>
════════════════════════════════════════════════════════════
Tokens: N | Est. cost: ~$X.XX
```

4. **Synthesis recommendation (REQUIRED).** After presenting the full
adversarial output, emit ONE recommendation line summarizing what the user
should do:

```
Recommendation: <action> because <one-line reason that names the most exploitable finding>
```

Examples (the strongest reasons compare blast radius across findings or fix-vs-ship):
- `Recommendation: Fix the unbounded retry loop Codex flagged at queue.ts:78 because it DoSes the worker pool under sustained 429s, which is higher-blast-radius than the timing leak Codex also flagged that only touches a debug endpoint.`
- `Recommendation: Ship as-is because Codex's strongest finding is a theoretical race in cleanup that requires conditions we cannot trigger in production, weaker than the runtime regressions a fix-now would risk.`

The reason must point to a specific finding and compare against alternatives (other findings, fix-vs-ship). Generic reasons like "because it's safer" do not qualify. **Never silently skip the line.**
