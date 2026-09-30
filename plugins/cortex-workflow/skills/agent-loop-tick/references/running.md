# Running the loop

The plugin ships no scheduler. The loop is two kinds of tick, each one invocation: the **build tick** (`agent-loop-tick`) takes a card from the queue, and the **review tick** (`agent-loop-review-tick`) takes a card from in-review and merges it into its milestone branch. How often they run, and from where, is the operator's: every way below is set up by hand, from the templates here. `agent-loop-setup check` is a cheap pre-flight that validates the cache against the live board without asking.

## What every way must keep

- **Review before build.** A merged card frees dependents in the queue, and a handed-back card is rework the next build tick should see.
- **One tick at a time on this machine**, build or review: both mutate the board and the repositories. Other people's ticks on the same board are safe; each takes only its own or unassigned cards. `~/.cortex/agent-loop/<key>.last-run.json` (build) and `<key>.review.last-run.json` (review) with `outcome: "running"` and a recent `started` mean a run is in flight.
- **Fresh context per tick.** Inheriting the previous card's context is how one task silently adopts another's assumptions. The ways marked *shared* below break this; use them to watch or to drain a board once, not as the standing loop.
- **A trusted working directory.** Run from `<repos_root>`, a parent of every repository and worktree the runs touch, so no trust prompt blocks the run.
- **No permission prompt.** Grant what a tick needs up front: shell, git, `gh`, the task-manager transport, the browser MCP for rung 5, network, and writes outside one repository (worktrees, `~/.cortex`).
- **Stuck runs.** A `running` outcome older than a few hours is wedged. Warn a human; never kill it blind: the card stays claimed either way and the next tick adopts it.

## One tick, per runtime

| Runtime | Build tick | Review tick |
|---|---|---|
| Claude Code | `claude -p '/agent-loop-tick' --permission-mode auto` | `claude -p '/agent-loop-review-tick' --permission-mode auto` |
| Codex | `codex exec --approve-for-me '$agent-loop-tick'` | `codex exec --approve-for-me '$agent-loop-review-tick'` |
| OpenCode | `opencode run '/agent-loop-tick'` | `opencode run '/agent-loop-review-tick'` |

Codex (the CLI) invokes a skill as `$<skill-name>`. `--approve-for-me` keeps the run in the `workspace-write` sandbox and routes each request to leave it (network, writes outside the repository) through automatic review instead of a prompt.

## The ways

| Way | Runtimes | Context | Schedule |
|---|---|---|---|
| By hand | all | fresh | none: the first run, watched end to end |
| `/loop` | Claude Code | *shared* | fixed interval, in one open session, 7-day expiry |
| `/goal` | Claude Code, Codex | *shared* | none: runs until the board is drained |
| System scheduler | all | fresh | cron or launchd on this machine |
| agterm session | Claude Code, Codex, on macOS with agterm | fresh (`/clear`) | launchd, into one watchable session |

### By hand

1. Open a terminal in `<repos_root>`.
2. Run the review tick from the table above, then the build tick.
3. Read the last line of each: `review tick complete — …` and `tick complete — …`.

### `/loop` — Claude Code, shared context

1. Start a dedicated session in `<repos_root>`: `claude --permission-mode auto`.
2. Type `/loop 1h Run /agent-loop-review-tick, then /agent-loop-tick.` One loop runs both in order; two loops would run them at once.
3. Leave the session open; the loop ends with it, when you cancel it, or after 7 days.

### `/goal` — Claude Code or Codex, shared context

1. Start a dedicated session in `<repos_root>` (`claude --permission-mode auto`, or `codex --approve-for-me`).
2. Type the goal. Claude Code: `/goal Repeat: run /agent-loop-review-tick, then /agent-loop-tick. Done when, in one round, the review tick ends with "nothing to review" and the build tick ends with "queue empty" or "queue blocked".` Codex: the same text with `$agent-loop-review-tick` and `$agent-loop-tick`.
3. `/goal` shows its state; `/goal clear` stops it (Codex also has `/goal pause` and `/goal resume`).

### System scheduler — cron or launchd

A runner script holds the lock and runs the two ticks in order; the scheduler calls it hourly. Both cron and launchd start jobs with a near-empty `PATH` and never read `~/.zshrc`, so the runner sets both itself.

1. Save as `~/.cortex/agent-loop/run-ticks.sh` and `chmod +x` it. Fill `<repos_root>`, the `PATH` entry holding the runtime binary, and the token line (or delete it on the Asana MCP transport).

   ```bash
   #!/bin/bash
   # One review tick, then one build tick. A second runner exits while the first is alive.
   set -uo pipefail
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   export ASANA_PERSONAL_ACCESS_TOKEN="<token>"
   DIR="$HOME/.cortex/agent-loop"
   LOG="$DIR/run-ticks.log"
   LOCK="$DIR/run-ticks.lock"
   log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

   # The pid inside the lock tells a live runner from one killed mid-tick.
   if ! mkdir "$LOCK" 2>/dev/null; then
       pid=$(cat "$LOCK/pid" 2>/dev/null)
       if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
           log "skip: runner $pid still running"
           exit 0
       fi
       rm -rf "$LOCK"
       mkdir "$LOCK" || exit 1
   fi
   echo $$ >"$LOCK/pid"
   trap 'rm -rf "$LOCK"' EXIT

   cd "<repos_root>" || { log "FATAL: no <repos_root>"; exit 1; }
   tick() {
       log "start: $1"
       claude -p "$1" --permission-mode auto >>"$LOG" 2>&1   # Codex: codex exec --approve-for-me "$1"
       log "end: $1 (exit $?)"
   }
   tick '/agent-loop-review-tick'   # Codex: '$agent-loop-review-tick'
   tick '/agent-loop-tick'          # Codex: '$agent-loop-tick'
   ```

2. Run it once by hand and read `~/.cortex/agent-loop/run-ticks.log`.
3. Schedule it, one of:
   - **cron** (Linux; on macOS cron needs Full Disk Access, so prefer launchd): `crontab -e`, add `0 * * * * $HOME/.cortex/agent-loop/run-ticks.sh`.
   - **launchd** (macOS): save as `~/Library/LaunchAgents/<label>.plist`, with `<label>` a reverse-DNS name such as `com.<you>.agent-loop` and `<home>` your home directory spelled out (launchd expands no variables):

     ```xml
     <?xml version="1.0" encoding="UTF-8"?>
     <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
     <plist version="1.0">
     <dict>
         <key>Label</key>
         <string><label></string>
         <key>ProgramArguments</key>
         <array>
             <string>/bin/bash</string>
             <string><home>/.cortex/agent-loop/run-ticks.sh</string>
         </array>
         <key>StartCalendarInterval</key>
         <dict>
             <key>Minute</key>
             <integer>0</integer>
         </dict>
         <key>RunAtLoad</key>
         <false/>
         <key>StandardOutPath</key>
         <string><home>/.cortex/agent-loop/launchd.out.log</string>
         <key>StandardErrorPath</key>
         <string><home>/.cortex/agent-loop/launchd.err.log</string>
         <key>ProcessType</key>
         <string>Background</string>
     </dict>
     </plist>
     ```

     Enable: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`. Run now: `launchctl kickstart gui/$(id -u)/<label>`. Disable: `launchctl bootout gui/$(id -u)/<label>`.

### agterm session — macOS

launchd types each tick into one long-lived interactive session in agterm's `Agent Loop` workspace, so every run lands in one scrollback you can open, read and type into. agterm's agent-status hooks give single flight: while the session is `active` a firing skips, while it is `blocked` it skips and notifies. The review tick fires at `:00`, the build tick at `:30`; a long run skips the firings it overlaps.

1. Save as `~/.cortex/agent-loop/agterm-tick.sh` and `chmod +x` it. Fill `<repos_root>` and `<key>`; for Codex, swap the `AGENT` line and the prompts as the comments say.

   ```bash
   #!/bin/bash
   # One firing: type the due tick into the Agent Loop session, unless it is busy or waiting on you.
   set -uo pipefail
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   DIR="$HOME/.cortex/agent-loop"
   LOG="$DIR/agterm-tick.log"
   CACHE="$DIR/<key>.json"
   WORKSPACE="Agent Loop"
   SESSION="Agent Loop"
   SOCKET="$HOME/Library/Application Support/agterm/agterm.sock"
   WORKDIR="<repos_root>"
   MAX_RUN_SECONDS=14400
   AGENT="claude --permission-mode auto"   # Codex: AGENT="codex --approve-for-me"
   case "${1:-$( [ "$(date +%M)" -lt 30 ] && echo review || echo build )}" in
   review) PROMPT='/agent-loop-review-tick' ;;   # Codex: '$agent-loop-review-tick'
   build) PROMPT='/agent-loop-tick' ;;           # Codex: '$agent-loop-tick'
   *) echo "usage: $0 [review|build]" >&2; exit 2 ;;
   esac
   log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }
   notify() { agtermctl notify "$1" --title "Agent Loop" >/dev/null 2>&1; }

   command -v "${AGENT%% *}" >/dev/null 2>&1 || { log "FATAL: ${AGENT%% *} not on PATH"; notify "${AGENT%% *} is not on the loop's PATH"; exit 1; }
   jq -e '.board.ref' "$CACHE" >/dev/null 2>&1 || { log "FATAL: no cache at $CACHE"; notify "Agent loop not configured — run agent-loop-setup"; exit 1; }

   if [ ! -S "$SOCKET" ]; then
       open -g -a agterm || { log "FATAL: could not launch agterm"; exit 1; }
       for _ in $(seq 1 30); do [ -S "$SOCKET" ] && break; sleep 0.5; done
       [ -S "$SOCKET" ] || { log "FATAL: agterm socket never appeared"; exit 1; }
   fi

   # id <tab> status <tab> foreground command of the loop session; empty when there is none.
   row() {
       agtermctl tree --json 2>/dev/null | jq -r --arg ws "$WORKSPACE" --arg name "$SESSION" '
           .result.tree.workspaces[]? | select(.name == $ws) | .sessions[]? | select(.name == $name)
           | [.id, (.status // "idle"), (.foreground // [] | join(" "))] | @tsv'
   }
   IFS=$'\t' read -r sid status foreground <<<"$(row)"

   if [ -n "$sid" ]; then
       age=$(( $(date +%s) - $(cat "$DIR/agterm-tick.started" 2>/dev/null || date +%s) ))
       if [ "$status" = "active" ]; then
           log "skip: run in flight ($((age / 60))m)"
           [ "$age" -gt "$MAX_RUN_SECONDS" ] && notify "Run active for $((age / 60))m — check the Agent Loop session"
           exit 0
       fi
       if [ "$status" = "blocked" ]; then
           log "skip: the session is waiting for you"
           notify "The loop session needs you"
           exit 0
       fi
       case "$foreground" in
       *claude* | *codex*) ;;
       *) log "session lost its agent — recreating"; agtermctl session close --target "$sid" >/dev/null 2>&1; sid="" ;;
       esac
   fi

   date +%s >"$DIR/agterm-tick.started"
   if [ -z "$sid" ]; then
       # The first prompt goes in as argv: keystrokes typed before the agent has booted are lost.
       # Unsetting CLAUDE_CODE_CHILD_SESSION keeps the transcript saved, so a run can be resumed.
       # The prompt's `$` is escaped because the command passes through a double-quoted zsh -lc.
       agtermctl session new --workspace-name "$WORKSPACE" --create-workspace --name "$SESSION" \
           --cwd "$WORKDIR" --no-select --wait \
           --command "zsh -lc \"export PATH='$PATH'; unset CLAUDE_CODE_CHILD_SESSION; $AGENT '${PROMPT//\$/\\\$}'\"" >/dev/null 2>&1 \
           || { log "FATAL: agtermctl session new failed"; exit 1; }
       # agtermctl reports the session, not the process in it: confirm the agent is in the foreground.
       sleep 8
       case "$(row | cut -f3)" in
       *claude* | *codex*) log "start: new session, $PROMPT" ;;
       *) log "FATAL: the agent exited at start — read the session"; notify "The loop session's agent exited at start"; exit 1 ;;
       esac
   else
       agtermctl session type $'/clear\n' --target "$sid" >/dev/null 2>&1
       sleep 2
       agtermctl session type "$PROMPT"$'\n' --target "$sid" >/dev/null 2>&1
       log "start: $PROMPT"
   fi
   ```

2. Run `~/.cortex/agent-loop/agterm-tick.sh review` by hand; the `Agent Loop` session appears in agterm with the review tick running.
3. Save the launchd plist from "System scheduler" with `agterm-tick.sh` in place of `run-ticks.sh`, `agterm.out.log`/`agterm.err.log` for the logs, and two firings:

   ```xml
   <key>StartCalendarInterval</key>
   <array>
       <dict><key>Minute</key><integer>0</integer></dict>
       <dict><key>Minute</key><integer>30</integer></dict>
   </array>
   ```

4. Enable, run and disable it with the same `launchctl` commands. Watch the session with `agtermctl session select --target <id>`, or read it with `agtermctl session text --all --target <id>`; `<id>` is the first column of `agtermctl tree --json` for the `Agent Loop` session.

## Cost

A tick that finds nothing still costs a model call. Before paying for a full run, a runner can check cheaply: `agent-loop-setup check`, then list `queue` and `in_progress` (build) or `in_review` (review) with a small model, and skip when no incomplete card is unassigned or assigned to this user. Such a check fails open: an inconclusive answer runs the tick.
