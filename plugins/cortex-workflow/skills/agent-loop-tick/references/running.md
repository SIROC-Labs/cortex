# Running the loop

The plugin ships no scheduler. The loop is two kinds of tick, each one invocation: the **build tick** (`agent-loop-tick`) takes a card from the queue, and the **review tick** (`agent-loop-review-tick`) takes a card from in-review and merges it into its milestone branch. How often they run, and from where, is the operator's: every way below is set up by hand, from the templates here. `agent-loop-setup check` is a cheap pre-flight that validates the cache against the live board without asking.

## What every way must keep

- **One session per kind.** The build tick and the review tick run in sessions of their own, side by side: each takes cards from a different column and works in its own worktree.
- **One tick of each kind at a time on this machine.** Two ticks of one kind would both read the same column before either claims. Other people's ticks on the same board are safe; each takes only its own or unassigned cards. `~/.cortex/agent-loop/<key>.last-run.json` (build) and `<key>.review.last-run.json` (review) with `outcome: "running"` and a recent `started` mean a run of that kind is in flight.
- **Fresh context per tick.** Inheriting the previous card's context is how one task silently adopts another's assumptions. The ways marked *shared* below break this; use them to watch or to drain a board once, not as the standing loop.
- **A trusted working directory.** Run from `<repos_root>`, a parent of every repository and worktree the runs touch, so no trust prompt blocks the run.
- **No permission prompt.** Grant what a tick needs up front: shell, git, `gh`, the task-manager transport, the browser MCP for rung 5 (enabled where the tick starts, in `<repos_root>`, not per project; see `../../start-task/references/skill-dependencies.md` → MCP Servers), network, and writes outside one repository (worktrees, `~/.cortex`).
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
| `/loop` | Claude Code | *shared* | fixed interval, in two open sessions, 7-day expiry |
| `/goal` | Claude Code, Codex | *shared* | none: runs until the board is drained |
| System scheduler | all | fresh | cron or launchd on this machine |
| agterm sessions | Claude Code, Codex, on macOS with agterm | fresh (`/clear`) | launchd, into two watchable sessions |

### By hand

1. Open two terminals in `<repos_root>`.
2. Run the build tick from the table above in one and the review tick in the other.
3. Read the last line of each: `tick complete — …` and `review tick complete — …`.

### `/loop` — Claude Code, shared context

1. Start two dedicated sessions in `<repos_root>`: `claude --permission-mode auto` in each.
2. In the build session type `/loop 1h /agent-loop-tick`; in the review session, `/loop 1h /agent-loop-review-tick`.
3. Leave both sessions open; each loop ends with its session, when you cancel it, or after 7 days.

### `/goal` — Claude Code or Codex, shared context

1. Start two dedicated sessions in `<repos_root>` (`claude --permission-mode auto`, or `codex --approve-for-me`, in each).
2. In the build session: `/goal Repeat /agent-loop-tick. Done when it ends with "queue empty" or "queue blocked".` In the review session: `/goal Repeat /agent-loop-review-tick. Done when it ends with "nothing to review".` Codex: the same text with `$agent-loop-tick` and `$agent-loop-review-tick`.
3. `/goal` shows a session's state; `/goal clear` stops it (Codex also has `/goal pause` and `/goal resume`).

### System scheduler — cron or launchd

One runner script takes the kind as its argument and holds that kind's lock; the scheduler calls it hourly once per kind, so the two kinds run side by side. Both cron and launchd start jobs with a near-empty `PATH` and never read `~/.zshrc`, so the runner sets both itself.

1. Save as `~/.cortex/agent-loop/run-tick.sh` and `chmod +x` it. Fill `<repos_root>`, the `PATH` entry holding the runtime binary, and the token line (or delete it on the Asana MCP transport).

   ```bash
   #!/bin/bash
   # One tick of the given kind. A second runner of the same kind exits while the first is alive.
   set -uo pipefail
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   export ASANA_PERSONAL_ACCESS_TOKEN="<token>"
   case "${1:-}" in
   build) PROMPT='/agent-loop-tick' ;;          # Codex: '$agent-loop-tick'
   review) PROMPT='/agent-loop-review-tick' ;;  # Codex: '$agent-loop-review-tick'
   *) echo "usage: $0 build|review" >&2; exit 2 ;;
   esac
   DIR="$HOME/.cortex/agent-loop"
   LOG="$DIR/run-tick.$1.log"
   LOCK="$DIR/run-tick.$1.lock"
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
   log "start: $PROMPT"
   claude -p "$PROMPT" --permission-mode auto >>"$LOG" 2>&1   # Codex: codex exec --approve-for-me "$PROMPT"
   log "end: $PROMPT (exit $?)"
   ```

2. Run `run-tick.sh build` and `run-tick.sh review` once by hand and read `~/.cortex/agent-loop/run-tick.build.log` and `run-tick.review.log`.
3. Schedule it once per kind, one of:
   - **cron** (Linux; on macOS cron needs Full Disk Access, so prefer launchd): `crontab -e`, add `0 * * * * $HOME/.cortex/agent-loop/run-tick.sh build` and `0 * * * * $HOME/.cortex/agent-loop/run-tick.sh review`.
   - **launchd** (macOS): save the plist twice, as `~/Library/LaunchAgents/<label>.build.plist` with `<kind>` = `build` and as `<label>.review.plist` with `<kind>` = `review`. `<label>` is a reverse-DNS name such as `com.<you>.agent-loop`, and `<home>` your home directory spelled out (launchd expands no variables):

     ```xml
     <?xml version="1.0" encoding="UTF-8"?>
     <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
     <plist version="1.0">
     <dict>
         <key>Label</key>
         <string><label>.<kind></string>
         <key>ProgramArguments</key>
         <array>
             <string>/bin/bash</string>
             <string><home>/.cortex/agent-loop/run-tick.sh</string>
             <string><kind></string>
         </array>
         <key>StartCalendarInterval</key>
         <dict>
             <key>Minute</key>
             <integer>0</integer>
         </dict>
         <key>RunAtLoad</key>
         <false/>
         <key>StandardOutPath</key>
         <string><home>/.cortex/agent-loop/launchd.<kind>.out.log</string>
         <key>StandardErrorPath</key>
         <string><home>/.cortex/agent-loop/launchd.<kind>.err.log</string>
         <key>ProcessType</key>
         <string>Background</string>
     </dict>
     </plist>
     ```

     Per kind: enable `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.<kind>.plist`, run now `launchctl kickstart gui/$(id -u)/<label>.<kind>`, disable `launchctl bootout gui/$(id -u)/<label>.<kind>`.

### agterm sessions — macOS

launchd types each tick into a long-lived interactive session of its kind in agterm's `Agent Loop` workspace, `build` and `review`, so every run of a kind lands in one scrollback you can open, read and type into. agterm's agent-status hooks give single flight per session: while it is `active` a firing skips, while it is `blocked` it skips and notifies. Each kind fires hourly; a long run skips the firings it overlaps.

1. Save as `~/.cortex/agent-loop/agterm-tick.sh` and `chmod +x` it. Fill `<repos_root>` and `<key>`; for Codex, swap the `AGENT` line and the prompts as the comments say.

   ```bash
   #!/bin/bash
   # One firing: type the tick into its kind's session, unless that session is busy or waiting on you.
   set -uo pipefail
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   case "${1:-}" in
   build) PROMPT='/agent-loop-tick' ;;          # Codex: '$agent-loop-tick'
   review) PROMPT='/agent-loop-review-tick' ;;  # Codex: '$agent-loop-review-tick'
   *) echo "usage: $0 build|review" >&2; exit 2 ;;
   esac
   DIR="$HOME/.cortex/agent-loop"
   LOG="$DIR/agterm-tick.$1.log"
   STARTED="$DIR/agterm-tick.$1.started"
   CACHE="$DIR/<key>.json"
   WORKSPACE="Agent Loop"
   SESSION="$1"
   SOCKET="$HOME/Library/Application Support/agterm/agterm.sock"
   WORKDIR="<repos_root>"
   MAX_RUN_SECONDS=14400
   AGENT="claude --permission-mode auto"   # Codex: AGENT="codex --approve-for-me"
   log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }
   notify() { agtermctl notify "$1" --title "Agent Loop" >/dev/null 2>&1; }

   command -v "${AGENT%% *}" >/dev/null 2>&1 || { log "FATAL: ${AGENT%% *} not on PATH"; notify "${AGENT%% *} is not on the loop's PATH"; exit 1; }
   jq -e '.board.ref' "$CACHE" >/dev/null 2>&1 || { log "FATAL: no cache at $CACHE"; notify "Agent loop not configured — run agent-loop-setup"; exit 1; }

   if [ ! -S "$SOCKET" ]; then
       open -g -a agterm || { log "FATAL: could not launch agterm"; exit 1; }
       for _ in $(seq 1 30); do [ -S "$SOCKET" ] && break; sleep 0.5; done
       [ -S "$SOCKET" ] || { log "FATAL: agterm socket never appeared"; exit 1; }
   fi

   # id <tab> status <tab> foreground command of this kind's session; empty when there is none.
   row() {
       agtermctl tree --json 2>/dev/null | jq -r --arg ws "$WORKSPACE" --arg name "$SESSION" '
           .result.tree.workspaces[]? | select(.name == $ws) | .sessions[]? | select(.name == $name)
           | [.id, (.status // "idle"), (.foreground // [] | join(" "))] | @tsv'
   }
   IFS=$'\t' read -r sid status foreground <<<"$(row)"

   if [ -n "$sid" ]; then
       age=$(( $(date +%s) - $(cat "$STARTED" 2>/dev/null || date +%s) ))
       if [ "$status" = "active" ]; then
           log "skip: run in flight ($((age / 60))m)"
           [ "$age" -gt "$MAX_RUN_SECONDS" ] && notify "$SESSION run active for $((age / 60))m — check its session"
           exit 0
       fi
       if [ "$status" = "blocked" ]; then
           log "skip: the session is waiting for you"
           notify "The $SESSION session needs you"
           exit 0
       fi
       case "$foreground" in
       *claude* | *codex*) ;;
       *) log "session lost its agent — recreating"; agtermctl session close --target "$sid" >/dev/null 2>&1; sid="" ;;
       esac
   fi

   date +%s >"$STARTED"
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
       *) log "FATAL: the agent exited at start — read the session"; notify "The $SESSION session's agent exited at start"; exit 1 ;;
       esac
   else
       agtermctl session type $'/clear\n' --target "$sid" >/dev/null 2>&1
       sleep 2
       agtermctl session type "$PROMPT"$'\n' --target "$sid" >/dev/null 2>&1
       log "start: $PROMPT"
   fi
   ```

2. Run `~/.cortex/agent-loop/agterm-tick.sh build` and `agterm-tick.sh review` by hand; the `build` and `review` sessions appear in agterm's `Agent Loop` workspace with their ticks running.
3. Save the two launchd plists from "System scheduler" with `agterm-tick.sh` in place of `run-tick.sh` and `agterm.<kind>` in place of `launchd.<kind>` in the log names.
4. Enable, run and disable each with the same `launchctl` commands. Watch a session with `agtermctl session select --target <id>`, or read it with `agtermctl session text --all --target <id>`; `<id>` is the first column of `agtermctl tree --json` for the `build` or `review` session.

## Cost

A tick that finds nothing still costs a model call. Before paying for a full run, a runner can check cheaply: `agent-loop-setup check`, then list `queue` and `in_progress` (build) or `in_review` (review) with a small model, and skip when no incomplete card is unassigned or assigned to this user. Such a check fails open: an inconclusive answer runs the tick.
