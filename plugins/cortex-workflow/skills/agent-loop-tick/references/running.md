# Running the loop

The plugin ships no scheduler. The loop is two kinds of tick, each one invocation: the **build tick** (`agent-loop-tick`) takes a card from the queue, and the **review tick** (`agent-loop-review-tick`) takes a card from in-review and merges it into its milestone branch, or approves it when it targets the default branch. How often they run, and from where, is the operator's: every way below is set up by hand, from the templates here. `agent-loop-setup check <name>` is a cheap pre-flight that validates a profile's cache against the live board without asking.

## What every way must keep

- **One profile per session.** A profile is one agent board under one provider account (`~/.cortex/agent-loop/<name>.json`). `CORTEX_PROJECT=<name>` in the environment of the runtime process selects it: both ticks read it, and so does the task-manager seam, so every call in the run uses that profile's account, board and repos root. The runner exports it; a hand-started session exports it before starting the runtime. Never export it in a shell profile: an attended session in a repository would then read the loop's cache instead of the repository's. A machine with two profiles runs two pairs of loops.
- **One session per kind.** The build tick and the review tick run in sessions of their own, side by side: each takes cards from a different column and works in its own worktree.
- **One tick of each kind at a time per profile on this machine.** Two ticks of one kind would both read the same column before either claims. Other people's ticks on the same board are safe; each takes only its own or unassigned cards. `~/.cortex/agent-loop/<name>.last-run.json` (build) and `<name>.review.last-run.json` (review) with `outcome: "running"` and a recent `started` mean a run of that kind is in flight.
- **Fresh context per tick.** Inheriting the previous card's context is how one task silently adopts another's assumptions. The ways marked *shared* below break this; use them to watch or to drain a board once, not as the standing loop.
- **A trusted working directory.** Run from `<repos_root>`, a parent of every repository and worktree the runs touch, so no trust prompt blocks the run.
- **No permission prompt.** Grant what a tick needs up front: shell, git, `gh`, the task-manager transport, the browser MCP for rung 5, network, and writes outside one repository (worktrees, `~/.cortex`).
- **Stuck runs.** A `running` outcome older than a few hours is wedged. Warn a human; never kill it blind: the card stays claimed either way and the next tick adopts it.

## One tick, per runtime

Every command runs with `CORTEX_PROJECT=<name>` set (`CORTEX_PROJECT=<name> claude -p …`, or exported first).

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

1. Open two terminals in `<repos_root>` and `export CORTEX_PROJECT=<name>` in each.
2. Run the build tick from the table above in one and the review tick in the other.
3. Read the last line of each: `tick complete — …` and `review tick complete — …`.

### `/loop` — Claude Code, shared context

1. Start two dedicated sessions in `<repos_root>`: `CORTEX_PROJECT=<name> claude --permission-mode auto` in each.
2. In the build session type `/loop 1h /agent-loop-tick`; in the review session, `/loop 1h /agent-loop-review-tick`.
3. Leave both sessions open; each loop ends with its session, when you cancel it, or after 7 days.

### `/goal` — Claude Code or Codex, shared context

1. Start two dedicated sessions in `<repos_root>` (`CORTEX_PROJECT=<name> claude --permission-mode auto`, or `CORTEX_PROJECT=<name> codex --approve-for-me`, in each).
2. In the build session: `/goal Repeat /agent-loop-tick. Done when it ends with "queue empty" or "queue blocked".` In the review session: `/goal Repeat /agent-loop-review-tick. Done when it ends with "nothing to review".` Codex: the same text with `$agent-loop-tick` and `$agent-loop-review-tick`.
3. `/goal` shows a session's state; `/goal clear` stops it (Codex also has `/goal pause` and `/goal resume`).

### System scheduler — cron or launchd

One runner script takes the profile and the kind as its arguments and holds that pair's lock; the scheduler calls it hourly once per kind and profile, so the kinds run side by side. Both cron and launchd start jobs with a near-empty `PATH` and never read `~/.zshrc`, so the runner sets both itself. The repos root comes from the profile's cache, so one script serves every profile.

1. Save as `~/.cortex/agent-loop/run-tick.sh` and `chmod +x` it. Fill the `PATH` entry holding the runtime binary and one token line per credential a profile's provider uses (delete them on the Asana MCP transport).

   ```bash
   #!/bin/bash
   # One tick of the given profile and kind. A second runner of the same pair exits while the first is alive.
   set -uo pipefail
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   export ASANA_PERSONAL_ACCESS_TOKEN="<token>"
   export ASANA_TOKEN_<NAME>="<token of another profile's account>"
   NAME="${1:-}"
   case "${2:-}" in
   build) PROMPT='/agent-loop-tick' ;;          # Codex: '$agent-loop-tick'
   review) PROMPT='/agent-loop-review-tick' ;;  # Codex: '$agent-loop-review-tick'
   *) echo "usage: $0 <profile> build|review" >&2; exit 2 ;;
   esac
   export CORTEX_PROJECT="$NAME"
   DIR="$HOME/.cortex/agent-loop"
   CACHE="$DIR/$NAME.json"
   LOG="$DIR/run-tick.$NAME.$2.log"
   LOCK="$DIR/run-tick.$NAME.$2.lock"
   log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }
   REPOS_ROOT=$(jq -r '.repos_root // empty' "$CACHE" 2>/dev/null)
   [ -n "$REPOS_ROOT" ] || { log "FATAL: no profile at $CACHE — run agent-loop-setup $NAME"; exit 1; }

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

   cd "$REPOS_ROOT" || { log "FATAL: no repos root $REPOS_ROOT"; exit 1; }
   log "start: $NAME $PROMPT"
   claude -p "$PROMPT" --permission-mode auto >>"$LOG" 2>&1   # Codex: codex exec --approve-for-me "$PROMPT"
   log "end: $NAME $PROMPT (exit $?)"
   ```

2. Run `run-tick.sh <name> build` and `run-tick.sh <name> review` once by hand and read `~/.cortex/agent-loop/run-tick.<name>.build.log` and `run-tick.<name>.review.log`.
3. Schedule it once per kind and profile, one of:
   - **cron** (Linux; on macOS cron needs Full Disk Access, so prefer launchd): `crontab -e`, add `0 * * * * $HOME/.cortex/agent-loop/run-tick.sh <name> build` and `0 * * * * $HOME/.cortex/agent-loop/run-tick.sh <name> review`.
   - **launchd** (macOS): save the plist twice per profile, as `~/Library/LaunchAgents/<label>.<name>.build.plist` with `<kind>` = `build` and as `<label>.<name>.review.plist` with `<kind>` = `review`. `<label>` is a reverse-DNS name such as `com.<you>.agent-loop`, and `<home>` your home directory spelled out (launchd expands no variables):

     ```xml
     <?xml version="1.0" encoding="UTF-8"?>
     <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
     <plist version="1.0">
     <dict>
         <key>Label</key>
         <string><label>.<name>.<kind></string>
         <key>ProgramArguments</key>
         <array>
             <string>/bin/bash</string>
             <string><home>/.cortex/agent-loop/run-tick.sh</string>
             <string><name></string>
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
         <string><home>/.cortex/agent-loop/launchd.<name>.<kind>.out.log</string>
         <key>StandardErrorPath</key>
         <string><home>/.cortex/agent-loop/launchd.<name>.<kind>.err.log</string>
         <key>ProcessType</key>
         <string>Background</string>
     </dict>
     </plist>
     ```

     Per kind and profile: enable `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.<name>.<kind>.plist`, run now `launchctl kickstart gui/$(id -u)/<label>.<name>.<kind>`, disable `launchctl bootout gui/$(id -u)/<label>.<name>.<kind>`.

### agterm sessions — macOS

launchd types each tick into a long-lived interactive session of its profile and kind in agterm's `Agent Loop` workspace, `<name> build` and `<name> review`, so every run of a kind lands in one scrollback you can open, read and type into. agterm's agent-status hooks give single flight per session: while it is `active` a firing skips, while it is `blocked` it skips and notifies. Each kind fires hourly; a long run skips the firings it overlaps.

1. Save as `~/.cortex/agent-loop/agterm-tick.sh` and `chmod +x` it. For Codex, swap the `AGENT` line and the prompts as the comments say.

   ```bash
   #!/bin/bash
   # One firing: type the tick into its profile's session of this kind, unless that session is busy or waiting on you.
   set -uo pipefail
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
   NAME="${1:-}"
   case "${2:-}" in
   build) PROMPT='/agent-loop-tick' ;;          # Codex: '$agent-loop-tick'
   review) PROMPT='/agent-loop-review-tick' ;;  # Codex: '$agent-loop-review-tick'
   *) echo "usage: $0 <profile> build|review" >&2; exit 2 ;;
   esac
   DIR="$HOME/.cortex/agent-loop"
   LOG="$DIR/agterm-tick.$NAME.$2.log"
   STARTED="$DIR/agterm-tick.$NAME.$2.started"
   CACHE="$DIR/$NAME.json"
   WORKSPACE="Agent Loop"
   SESSION="$NAME $2"
   SOCKET="$HOME/Library/Application Support/agterm/agterm.sock"
   MAX_RUN_SECONDS=14400
   AGENT="claude --permission-mode auto"   # Codex: AGENT="codex --approve-for-me"
   log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }
   notify() { agtermctl notify "$1" --title "Agent Loop" >/dev/null 2>&1; }

   command -v "${AGENT%% *}" >/dev/null 2>&1 || { log "FATAL: ${AGENT%% *} not on PATH"; notify "${AGENT%% *} is not on the loop's PATH"; exit 1; }
   jq -e '.board.ref' "$CACHE" >/dev/null 2>&1 || { log "FATAL: no cache at $CACHE"; notify "Agent loop $NAME not configured — run agent-loop-setup $NAME"; exit 1; }
   WORKDIR=$(jq -r '.repos_root' "$CACHE")

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
       # CORTEX_PROJECT selects the profile for the whole session; the prompt's `$` is escaped
       # because the command passes through a double-quoted zsh -lc.
       agtermctl session new --workspace-name "$WORKSPACE" --create-workspace --name "$SESSION" \
           --cwd "$WORKDIR" --no-select --wait \
           --command "zsh -lc \"export PATH='$PATH' CORTEX_PROJECT='$NAME'; unset CLAUDE_CODE_CHILD_SESSION; $AGENT '${PROMPT//\$/\\\$}'\"" >/dev/null 2>&1 \
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

2. Run `~/.cortex/agent-loop/agterm-tick.sh <name> build` and `agterm-tick.sh <name> review` by hand; the `<name> build` and `<name> review` sessions appear in agterm's `Agent Loop` workspace with their ticks running.
3. Save the two launchd plists per profile from "System scheduler" with `agterm-tick.sh` in place of `run-tick.sh` and `agterm.<name>.<kind>` in place of `launchd.<name>.<kind>` in the log names.
4. Enable, run and disable each with the same `launchctl` commands. Watch a session with `agtermctl session select --target <id>`, or read it with `agtermctl session text --all --target <id>`; `<id>` is the first column of `agtermctl tree --json` for the `<name> build` or `<name> review` session.

## Cost

A tick that finds nothing still costs a model call. Before paying for a full run, a runner can check cheaply: `agent-loop-setup check <name>`, then list `queue` and `in_progress` (build) or `in_review` (review) with a small model, and skip when no incomplete card is unassigned or assigned to this user. Such a check fails open: an inconclusive answer runs the tick.
