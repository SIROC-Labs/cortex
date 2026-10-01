#!/usr/bin/env python3
#
# tui — browse boards, queue tasks and watch the runs that work them.
#
# A terminal UI over a per-repo background daemon. Pick the sprint, browse any
# board, queue tasks or whole sections whenever you like; the daemon starts each
# one through start-task once its dependencies are done, and watches its PR to
# merge — the same engine as `run-milestone`. Closing the TUI leaves the daemon
# working; opening it again, from any terminal, shows every daemon on the machine
# and every run still going in this repo, owned or not.
#
#   cortex tui                    # the UI (run from inside the target repo)
#   cortex tui --status           # the queue and the daemon, printed; no UI
#   cortex tui --stop             # stop this repo's daemon and its runs
#   cortex tui --backend echo     # anything else goes to start-task, via the daemon
#
# Dependencies: Python 3 stdlib (curses), git, gh, and start-task / run-milestone
# (sibling directories).

import argparse
import curses
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daemon as dm  # noqa: E402
from cache import Cache, Loader, age_label, is_stale, spinner  # noqa: E402
from engine import ASANA, Stop, describe, task_url  # noqa: E402
from daemon import st  # noqa: E402

TABS = ("Runs", "Boards", "Sprint", "Daemons")
# How old a cached copy may be before the view showing it re-reads Asana behind it.
BOARDS_MAX_AGE = 300
BOARD_OPEN_MAX_AGE = 30
BOARD_SHOWN_MAX_AGE = 60

PHASE_STYLE = {
    "running": "ok", "revising": "ok", "pr_open": "ok", "merged": "dim",
    "awaiting": "warn", "conflict": "warn", "failed": "bad", "stopped": "dim",
}


# --- pure helpers (unit-tested) ---------------------------------------------

def matches(text, query):
    """Every word of the query appears in the text, ignoring case."""
    text = (text or "").lower()
    return all(word in text for word in (query or "").lower().split())


def wait_summary(wait):
    """One line for what a task is waiting on you for."""
    if wait.get("kind") == "conflict":
        return "PR conflicts with its base — a to have it resolved, m to merge"
    if wait.get("kind") == "merge":
        return wait["headline"] + " — m tries again"
    questions = wait.get("questions") or []
    if questions:
        more = len(questions) - 1
        return questions[0].get("q", "") + (" (+%d more)" % more if more else "")
    return wait.get("headline") or "waiting on a reply"


def wait_lines(wait, width):
    """The whole of a wait, wrapped to the screen, as [(text, style)]."""
    width = max(20, width - 4)
    out = []

    def para(text, style, indent=""):
        for line in (text or "").splitlines() or [""]:
            for piece in textwrap.wrap(line, width - len(indent)) or [""]:
                out.append((indent + piece, style))

    if wait.get("kind") == "conflict":
        para("The PR conflicts with its base, most likely because a sibling task merged "
             "first and touched the same files. The task is parked until you ask for "
             "a resolve: the base is then merged in and the conflicts resolved — never "
             "a rebase or force-push. Or press m to resolve and merge it in one go.",
             "normal")
        return out
    if wait.get("kind") == "merge":
        para(wait.get("headline") or "", "bold")
        out.append(("", "normal"))
        para("The merge stopped short of main. Fix what stands in the way on GitHub, "
             "then press m to try again — it picks up from wherever the PR is.", "normal")
        return out
    for n, q in enumerate(wait.get("questions") or [], 1):
        para("%d. %s" % (n, q.get("q", "")), "bold")
        if q.get("why"):
            para(q["why"], "dim", "   ")
        out.append(("", "normal"))
    if wait.get("headline"):
        para(wait["headline"], "bold")
    if wait.get("detail"):
        out.append(("", "normal"))
        for line in wait["detail"].splitlines()[-200:]:
            out.append(("  " + line[:width], "dim"))
    return out


def answer_template(title, wait):
    """What the editor opens with: the wait as comments, room for the answer."""
    lines = ["", "", "# Answer for %s" % title, "#"]
    lines += ["# " + text if text else "#" for text, _ in wait_lines(wait, 78)]
    lines += ["#", "# Lines starting with # are dropped. An empty answer sends nothing."]
    return "\n".join(lines) + "\n"


def parse_answer(text):
    """The answer in an edited template, or None for an empty one."""
    kept = [line for line in (text or "").splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(kept).strip() or None


def read_waits(main_root, control, data):
    """What each queued task is waiting on you for: an outstanding question or
    problem from its run (its `awaiting.json`), or a parked conflict."""
    tasks, records = data.get("tasks") or {}, data.get("records") or {}
    waits = {}
    for item in control.get("queue") or []:
        gid = item["gid"]
        key = (tasks.get(gid) or {}).get("key")
        awaiting = st.State(main_root, key).read("awaiting.json") if key else None
        if awaiting and awaiting.get("asked_at"):
            waits[gid] = dict(awaiting, key=key)
        elif ((records.get(gid) or {}).get("merge") or {}).get("blocked"):
            waits[gid] = {"kind": "merge", "key": key,
                          "headline": "Merge blocked: %s" % records[gid]["merge"]["blocked"]}
        elif (records.get(gid) or {}).get("phase") == "conflict":
            waits[gid] = {"kind": "conflict", "key": key}
    return waits


def run_rows(control, data, live, me_gid=None, agents=(), waits=None):
    """The Runs tab: every task waiting on you first, then the rest of the queue
    in its order, then every live start-task run nothing here owns, then every
    agent left working with no run at all."""
    tasks, records = data.get("tasks") or {}, data.get("records") or {}
    me_gid = me_gid or (data.get("me") or {}).get("gid")
    waits = waits or {}
    rows = []
    for item in control.get("queue") or []:
        gid = item["gid"]
        task = tasks.get(gid)
        record = records.get(gid) or {}
        if task is None:
            key, name, status = "…", item.get("name") or gid, "queued — not read yet"
        else:
            key, name = task.get("key"), task.get("name")
            status = describe(gid, tasks, records, me_gid)
            if status == "ready" and not control.get("sprint"):
                status = "ready — starts once a sprint is picked"
        style = PHASE_STYLE.get(record.get("phase"))
        if not style:
            style = "dim" if task and task.get("completed") else "normal"
        wait = waits.get(gid)
        if wait:
            status, style = "⚑ " + wait_summary(wait), "warn"
        rows.append({"kind": "task", "id": gid, "cols": [key or "", name or "", status],
                     "style": style, "log": record.get("log"), "wait": wait,
                     "pr_url": record.get("pr_url"), "phase": record.get("phase"),
                     "merge": record.get("merge"),
                     "links": [u for u in (record.get("pr_url"),
                                           task_url(item.get("board"), gid)) if u]})
    rows.sort(key=lambda r: not r.get("wait"))
    managed = [r.get("pid") for r in records.values() if r.get("pid")]
    for tid, pid in dm.unmanaged(live, managed):
        rows.append({"kind": "orphan", "id": pid, "style": "warn", "links": [],
                     "cols": [tid, "start-task pid %d" % pid,
                              "not run by this repo's daemon — x stops it"]})
    for tree, pid in agents:
        rows.append({"kind": "orphan", "id": pid, "style": "bad", "links": [],
                     "cols": [tree.split("+")[0], "agent pid %d, no run owns it" % pid,
                              "still working in %s — x stops it" % tree]})
    return rows


def board_list_rows(boards, query, sprint=None):
    sprint_gid = (sprint or {}).get("gid")
    return [{"kind": "board", "id": b["gid"], "name": b["name"], "style":
             "bold" if b["gid"] == sprint_gid else "normal",
             "cols": [b["name"], "← sprint" if b["gid"] == sprint_gid else ""]}
            for b in boards or [] if matches(b["name"], query)]


def board_rows(board_gid, sections, queued, records, query, live=None):
    """A board as sections and their tasks. A section stays when its name or any of
    its tasks match the query; a task when it matches or its section does. `live`
    is what the daemon last read of a task, laid over the cached board — it is
    newer for anything the daemon is working."""
    live = live or {}
    sections = [dict(sec, tasks=[dict(t, completed=t.get("completed")
                                      or bool((live.get(t["gid"]) or {}).get("completed")))
                                 for t in sec.get("tasks") or []])
                for sec in sections or []]
    rows = []
    for section in sections or []:
        hit = matches(section["name"], query)
        tasks = [t for t in section.get("tasks") or []
                 if t.get("kind") != "milestone" and (hit or matches(t["name"], query))]
        if not tasks and not hit:
            continue
        open_count = sum(1 for t in tasks if not t.get("completed"))
        rows.append({"kind": "section", "id": section["gid"], "board": board_gid,
                     "cols": [section["name"], "%d open" % open_count], "style": "bold",
                     "tasks": tasks})
        for t in tasks:
            phase = (records.get(t["gid"]) or {}).get("phase")
            mark = "●" if t["gid"] in queued else " "
            state = "done" if t.get("completed") else (phase or ("queued" if t["gid"] in queued else ""))
            rows.append({"kind": "task", "id": t["gid"], "board": board_gid, "name": t["name"],
                         "completed": t.get("completed"),
                         "cols": ["  %s %s" % (mark, t["name"]), state],
                         "style": "dim" if t.get("completed") else
                                  PHASE_STYLE.get(phase, "normal")})
    return rows


def daemon_rows(entries, now):
    rows = []
    for path, info, alive in entries:
        root = info.get("main_root") or "?"
        beat, _ = dm.daemon_info(root) if os.path.isdir(root) else (None, False)
        health = dm.daemon_health(beat or info, alive, now) if alive else "crashed"
        runs = len(dm.live_runs(root)) if os.path.isdir(root) else 0
        rows.append({"kind": "daemon", "id": path, "info": info, "alive": alive,
                     "style": {"running": "ok", "stale": "warn"}.get(health, "bad"),
                     "cols": [root, health, "pid %s" % info.get("pid"),
                              "%d live run(s)" % runs]})
    return rows


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\x1b[=>]")


def log_line(line):
    """A log line as (text, style): terminal escape codes removed, and a line the
    run had set in bold — a step heading — kept bold."""
    bold = "\x1b[1m" in line
    return _ANSI.sub("", line).replace("\t", "    "), "bold" if bold else "normal"


def fit(cols, width):
    """One line from columns: the last column takes what is left."""
    if len(cols) == 3:
        widths = [10, 46, 0]
    else:
        widths = [max(20, width // 2)] + [14] * (len(cols) - 2) + [0]
    parts = []
    for col, w in zip(cols, widths):
        col = str(col)
        parts.append(col if not w else (col[:w - 1] + "…" if len(col) > w else col.ljust(w)))
    return "  ".join(parts)[:max(0, width - 1)]


# --- keys -------------------------------------------------------------------
#
# Keys are read raw and decoded here rather than left to curses: a terminal that
# ignores keypad mode sends arrows as `ESC [ B`, which curses hands over as three
# separate keys — an escape (back), a `[` and a `B`. Decoding the sequence
# ourselves makes every terminal behave the same.

_CSI_FINAL = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home",
              "F": "end", "Z": "btab"}
_CSI_TILDE = {"1": "home", "7": "home", "4": "end", "8": "end", "5": "pgup",
              "6": "pgdn", "3": "delete", "2": "insert"}
_CONTROL = {9: "tab", 10: "enter", 13: "enter", 8: "backspace", 127: "backspace",
            3: "ctrl-c", 14: "ctrl-n", 16: "ctrl-p", 6: "ctrl-f", 2: "ctrl-b",
            4: "ctrl-d", 21: "ctrl-u"}
_CURSES = {"KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
           "KEY_NPAGE": "pgdn", "KEY_PPAGE": "pgup", "KEY_HOME": "home", "KEY_END": "end",
           "KEY_ENTER": "enter", "KEY_BACKSPACE": "backspace", "KEY_BTAB": "btab",
           "KEY_DC": "delete"}

# What each key does wherever lists are shown. Vi, emacs and the arrow keys all
# work; a number goes straight to its tab.
NAV = {
    "down": "down", "j": "down", "ctrl-n": "down",
    "up": "up", "k": "up", "ctrl-p": "up",
    "pgdn": "pgdn", "ctrl-f": "pgdn",
    "pgup": "pgup", "ctrl-b": "pgup",
    "ctrl-d": "halfdown", "ctrl-u": "halfup",
    "home": "home", "g": "home",
    "end": "end", "G": "end",
    "right": "open", "l": "open", "enter": "open",
    "left": "back", "h": "back", "esc": "back", "backspace": "back",
    "tab": "next", "btab": "next",
}
for _n in range(1, len(TABS) + 1):
    NAV[str(_n)] = NAV["alt-%d" % _n] = "tab"
MOVES = ("down", "up", "pgdn", "pgup", "halfdown", "halfup", "home", "end")

HELP = [
    "move        ↑ ↓   j k   ^N ^P",
    "page        PgDn PgUp   ^F ^B      half page   ^D ^U",
    "top / end   Home End   g G",
    "in          ⏎   →   l           (open a board, a run's log, pick a sprint)",
    "out         ←   h   esc   ⌫      (clear the filter, then leave the board)",
    "tabs        1-4 (or alt-1..4)   tab / shift-tab to cycle — the current tab's",
    "            number again takes it back to its top",
    "filter      /   then type; ⏎ keeps it, esc clears it",
    "",
    "Runs        m merge: get it onto main — conflicts resolved, failing checks fixed,",
    "            then merged; m again calls it off · on a blocked merge, m tries again",
    "            ⏎ on a ⚑ task reads what it is waiting on · a answer it in one line ·",
    "            A answer in $EDITOR · on a parked conflict, a asks for a resolve",
    "            x stop and unqueue · r retry · o open the PR or task",
    "Boards      space queue or unqueue a task; on a section, queue all of it · R reload",
    "Sprint      ⏎ use the board as the sprint",
    "Daemons     s start this repo's daemon · x stop one · d clear a crashed one",
    "",
    "q quits the UI; the daemon keeps working.                      any key closes this",
]


def decode_escape(seq):
    """A key from what followed an ESC: nothing (a bare escape), one character
    (alt+key), or a CSI / SS3 sequence like `[B`, `OB`, `[5~` or `[1;5A`."""
    if not seq:
        return "esc"
    if seq[0] not in "[O" or len(seq) == 1:
        return "alt-%s" % seq
    final, params = seq[-1], seq[1:-1]
    if final == "~":
        return _CSI_TILDE.get(params.split(";")[0])
    return _CSI_FINAL.get(final)


def decode_key(code):
    """A key from one curses getch() value, or None for one that means nothing."""
    if code in _CONTROL:
        return _CONTROL[code]
    for name, token in _CURSES.items():
        if code == getattr(curses, name, None):
            return token
    if 32 <= code < 127:
        return chr(code)
    return None


def read_key(scr, idle=1000):
    """One keypress as a token, or None when nothing was pressed."""
    code = scr.getch()
    if code == -1:
        return None
    if code != 27:
        return decode_key(code)
    scr.timeout(40)
    seq = ""
    while True:
        nxt = scr.getch()
        if nxt == -1 or nxt >= 256:
            break
        seq += chr(nxt)
        if seq[0] not in "[O":
            break
        if len(seq) > 1 and 0x40 <= ord(seq[-1]) <= 0x7e:
            break
    scr.timeout(idle)
    return decode_escape(seq)


# --- the app ----------------------------------------------------------------

class App(object):
    def __init__(self, main_root, forward):
        self.main_root = main_root
        self.forward = forward
        self.tab = 0
        self.cursor = {}
        self.query = {}
        self.typing = False
        self.board = None
        self.cache = Cache()
        self.loader = Loader()
        self.boards, self.boards_at = self.cache.get("boards")
        self.sections = {}
        self.sections_at = {}
        self.message = ""
        self.confirm = None
        self.log_path = None
        self.log_scroll = 0
        self.help = False
        self.page = 10
        self.question = None
        self.compose = None
        self.edit_request = None
        self.posting = {}
        self.sent = []
        self.snapshot()

    # data

    def asana(self, args):
        proc = subprocess.run([sys.executable, ASANA] + args, cwd=self.main_root,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise Stop("asana.py %s: %s" % (" ".join(args[:2]),
                                            proc.stderr.decode("utf-8", "replace").strip()))
        return json.loads(proc.stdout.decode("utf-8", "replace") or "null")

    def snapshot(self):
        self.control = dm.read_control(self.main_root)
        self.data = dm.read_json(os.path.join(dm.queue_dir(self.main_root), "state.json")) or {}
        self.daemon, self.alive = dm.daemon_info(self.main_root)
        self.live = dm.live_runs(self.main_root)
        self.waits = read_waits(self.main_root, self.control, self.data)
        self.agents = dm.live_agents(self.main_root, [pid for _, pid in self.live])

    def fetch_boards(self):
        me, _ = self.cache.get("me")
        if not me:
            me = self.asana(["user", "me"])
            self.cache.put("me", me)
        workspace = ((me.get("workspaces") or [{}])[0]).get("gid")
        boards = sorted(self.asana(["project", "list", workspace]),
                        key=lambda b: b["name"].lower())
        self.cache.put("boards", boards)
        return boards

    def fetch_sections(self, gid):
        sections = self.asana(["project", "sections", gid])
        self.cache.put("sections-%s" % gid, sections)
        return sections

    def refresh_boards(self, max_age=BOARDS_MAX_AGE):
        if is_stale(self.boards_at, time.time(), max_age):
            self.loader.start("boards", "boards", self.fetch_boards)

    def refresh_board(self, gid, max_age):
        if gid not in self.sections:
            self.sections[gid], self.sections_at[gid] = self.cache.get("sections-%s" % gid)
        if is_stale(self.sections_at.get(gid), time.time(), max_age):
            self.loader.start("sections-%s" % gid, gid, lambda: self.fetch_sections(gid))

    def sync(self):
        """Take finished loads, and start the ones the screen now needs."""
        now = time.time()
        done = self.loader.take("boards")
        if done:
            if done[1]:
                self.message = "could not refresh the boards: %s" % done[1]
            else:
                self.boards, self.boards_at = done[0], now
        for gid in list(self.sections):
            done = self.loader.take("sections-%s" % gid)
            if done:
                if done[1]:
                    self.message = "could not refresh the board: %s" % done[1]
                else:
                    self.sections[gid], self.sections_at[gid] = done[0], now
        if self.sent:
            self.follow_commands()
        for gid in list(self.posting):
            done = self.loader.take("answer-%s" % gid)
            if done:
                kind = self.posting.pop(gid)
                if done[1] and kind == "answer":
                    self.message = ("could not copy the answer to Asana (%s) — the run "
                                    "has it all the same" % done[1])
                elif done[1]:
                    self.message = "could not ask for the resolve: %s" % done[1]
        if TABS[self.tab] in ("Boards", "Sprint"):
            if self.board and TABS[self.tab] == "Boards":
                self.refresh_board(self.board[0], BOARD_SHOWN_MAX_AGE)
            else:
                self.refresh_boards()

    def loading(self):
        """(busy, age) of what is on screen: whether a load is running for it, and
        how old the copy shown is."""
        if TABS[self.tab] == "Boards" and self.board:
            gid = self.board[0]
            return self.loader.busy("sections-%s" % gid), self.sections_at.get(gid)
        if TABS[self.tab] in ("Boards", "Sprint"):
            return self.loader.busy("boards"), self.boards_at
        return False, None

    def view(self):
        """(view name, rows) for what is on screen."""
        name = TABS[self.tab]
        query = self.query.get(self.view_key(), "")
        if name == "Runs":
            return run_rows(self.control, self.data, self.live, agents=self.agents,
                            waits=self.waits)
        if name == "Boards" and self.board:
            queued = {q["gid"] for q in self.control["queue"]}
            return board_rows(self.board[0], self.sections.get(self.board[0]), queued,
                              self.data.get("records") or {}, query, self.data.get("tasks"))
        if name in ("Boards", "Sprint"):
            return board_list_rows(self.boards, query, self.control.get("sprint"))
        return daemon_rows(dm.registered(), time.time())

    def view_key(self):
        return "board:%s" % self.board[0] if TABS[self.tab] == "Boards" and self.board else TABS[self.tab]

    def selected(self, rows):
        if not rows:
            return None
        i = min(self.cursor.get(self.view_key(), 0), len(rows) - 1)
        return rows[i]

    # actions

    def change_control(self, fn):
        with dm.control_file(self.main_root) as control:
            result = fn(control)
        self.snapshot()
        return result

    def ensure_daemon(self):
        if not self.alive:
            pid = dm.start_daemon(self.main_root, self.forward)
            self.message = "started the daemon (pid %d)" % pid

    def queue(self, items):
        items = [i for i in items if not i.get("completed")]
        if not items:
            self.message = "already complete — nothing to queue"
            return
        added = self.change_control(lambda c: dm.queue_add(c, items))
        started = ""
        if added and not self.alive:
            self.ensure_daemon()
            started = " · " + self.message
        self.message = ("queued %d task(s)" % len(added) if added else "already queued") + (
            "" if self.control.get("sprint") else " — pick a sprint (tab 3) before they start"
        ) + started

    def answer(self, gid, text):
        """Hand an answer to the task's waiting run. It goes in the run's state,
        which the run looks at every second, and onto the task in Asana as your
        comment, so the conversation stays where the question was asked."""
        wait = self.waits.get(gid) or {}
        if not wait.get("asked_at") or not wait.get("key"):
            self.message = "nothing is waiting on an answer there any more"
            return
        st.State(self.main_root, wait["key"]).write(
            st.ANSWER_FILE, {"asked_at": wait["asked_at"], "text": text, "at": time.time()})
        self.posting[gid] = "answer"
        self.loader.start("answer-%s" % gid, "answer",
                          lambda: self.asana(["comment", "add", gid, text]))
        self.question = None
        self.message = "answered %s — the run picks it up now" % wait["key"]
        self.snapshot()

    def resolve(self, gid, pr_url):
        """Ask for a parked conflict to be resolved, the way a person would: a
        `please resolve` comment on the PR, which the loop looks for each minute."""
        def post():
            code = subprocess.run(["gh", "pr", "comment", pr_url, "--body", "please resolve"],
                                  cwd=self.main_root, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if code.returncode != 0:
                raise Stop(code.stderr.decode("utf-8", "replace").strip() or "gh failed")
        self.posting[gid] = "resolve"
        self.loader.start("answer-%s" % gid, "resolve", post)
        self.question = None
        self.message = "asked for a resolve on %s — picked up within a minute" % pr_url

    def start_answer(self, row, editor=False):
        wait = (row or {}).get("wait")
        if not wait:
            self.message = "nothing is waiting on you there"
        elif wait.get("kind") == "merge":
            self.message = "fix what blocks it, then m tries the merge again"
        elif wait.get("kind") == "conflict":
            if not row.get("pr_url"):
                self.message = "no PR recorded for that task"
                return
            self.ask("post `please resolve` on %s? (y/n)" % row["pr_url"],
                     lambda: self.resolve(row["id"], row["pr_url"]))
        elif editor:
            self.edit_request = row["id"]
        else:
            self.compose = {"gid": row["id"], "text": ""}

    def merge(self, row):
        """Ask for a task to be got onto main: conflicts resolved, failing checks
        fixed, merged. Asked again on a merge in progress, it is called off; on a
        blocked one, it is tried again from where the PR stands."""
        merge = row.get("merge")
        name = row["cols"][0]
        if row.get("phase") in ("merged", "stopped", "failed"):
            self.message = "nothing to merge there"
        elif merge and not merge.get("blocked"):
            self.ask("stop trying to merge %s? (y/n)" % name,
                     lambda: self.command("merge-cancel", row["id"]))
        else:
            when = "" if row.get("pr_url") else " once its PR is up"
            self.ask("merge %s%s — resolving conflicts and fixing failing checks as needed? "
                     "(y/n)" % (name, when), lambda: self.command("merge", row["id"]))

    def command(self, op, gid):
        applied = self.data.get("applied", 0)
        cid = self.change_control(lambda c: dm.add_command(c, op, gid, applied))
        key = ((self.data.get("tasks") or {}).get(gid) or {}).get("key") or gid
        self.sent.append({"id": cid, "op": op, "key": key, "at": time.time()})
        self.follow_commands()

    def follow_commands(self):
        """Say what became of each command sent: done, ignored, or still waiting."""
        for sent in list(self.sent):
            message, settled = dm.command_feedback(
                sent, self.data.get("applied", 0), self.data.get("results"),
                self.alive, time.time())
            self.message = message
            if settled:
                self.sent.remove(sent)

    def act(self, key, row):
        name = TABS[self.tab]
        if name == "Runs" and row:
            if key in ("a", "A") and row["kind"] == "task":
                self.start_answer(row, editor=key == "A")
            elif key == "m" and row["kind"] == "task":
                self.merge(row)
            elif key == "x" and row["kind"] == "task":
                self.ask("stop and unqueue %s? (y/n)" % row["cols"][0], lambda: (
                    self.command("stop", row["id"]),
                    self.change_control(lambda c: dm.queue_remove(c, [row["id"]]))))
            elif key == "x" and row["kind"] == "orphan":
                self.ask("stop pid %d and what it started? (y/n)" % row["id"],
                         lambda: dm.kill_pid(row["id"]))
            elif key == "r" and row["kind"] == "task":
                self.command("retry", row["id"])
                self.message = "retry asked — a failed or stopped task starts again when ready"
            elif key == "o" and row.get("links"):
                webbrowser.open(row["links"][0])
        elif name == "Boards" and self.board:
            if key == "R":
                self.refresh_board(self.board[0], max_age=-1)
            elif key == " " and row and row["kind"] == "section":
                self.queue([{"gid": t["gid"], "board": row["board"], "name": t["name"],
                             "completed": t.get("completed")} for t in row["tasks"]])
            elif key == " " and row:
                if row["id"] in {q["gid"] for q in self.control["queue"]}:
                    self.change_control(lambda c: dm.queue_remove(c, [row["id"]]))
                    self.message = ("unqueued — a run already going is left to finish; "
                                    "x on the Runs tab stops it")
                else:
                    self.queue([{"gid": row["id"], "board": row["board"],
                                 "name": row["name"], "completed": row.get("completed")}])
        elif name in ("Boards", "Sprint") and key == "R":
            self.refresh_boards(max_age=-1)
        elif name == "Daemons":
            if key == "s":
                if self.alive:
                    self.message = "this repo's daemon is already running"
                else:
                    self.ensure_daemon()
            elif key == "x" and row and row["alive"]:
                self.ask("stop the daemon for %s and its runs? (y/n)" % row["cols"][0],
                         lambda: dm.stop_daemon(row["info"]))
            elif key == "d" and row and not row["alive"]:
                os.remove(row["id"])
                self.message = "cleared the crashed daemon's entry"

    def open(self, row, key):
        """Go into the selected row: a board's tasks, a run's log — or, with enter
        only, pick the sprint."""
        name = TABS[self.tab]
        if not row:
            return
        if name == "Boards" and not self.board:
            self.board = (row["id"], row["name"])
            self.refresh_board(row["id"], BOARD_OPEN_MAX_AGE)
        elif name == "Runs":
            if row.get("wait"):
                self.question = row["id"]
            elif row.get("log"):
                self.log_path, self.log_scroll = row["log"], 0
            else:
                self.message = "no log yet — the run has not started"
        elif name == "Sprint" and key == "enter":
            sprint = {"gid": row["id"], "name": row["name"]}
            self.change_control(lambda c: c.update(sprint=sprint))
            self.message = "sprint: %s" % row["name"]

    def back(self):
        """Out one level: a filter first, then the board you are in."""
        vk = self.view_key()
        if self.query.get(vk):
            self.query[vk] = ""
            self.cursor[vk] = 0
        elif TABS[self.tab] == "Boards" and self.board:
            self.board = None

    def goto(self, tab):
        if tab == self.tab:
            self.board = None if TABS[tab] == "Boards" else self.board
            self.query[self.view_key()] = ""
        self.tab = tab

    def ask(self, prompt, fn):
        self.confirm = (prompt, fn)
        self.message = prompt

    def move(self, key, count):
        vk = self.view_key()
        step = {"down": 1, "up": -1, "pgdn": self.page, "pgup": -self.page,
                "halfdown": max(1, self.page // 2), "halfup": -max(1, self.page // 2),
                "home": -count, "end": count}[key]
        self.cursor[vk] = max(0, min(self.cursor.get(vk, 0) + step, max(0, count - 1)))

    def key(self, key, rows):
        """One keypress, as a token from `decode_key`. Returns False to quit."""
        vk = self.view_key()
        if self.confirm:
            _, fn = self.confirm
            self.confirm = None
            self.message = ""
            if key == "y":
                fn()
                self.snapshot()
            return True
        if self.help:
            self.help = False
            return True
        if self.compose is not None:
            if key == "enter":
                text = self.compose["text"].strip()
                gid, self.compose = self.compose["gid"], None
                if text:
                    self.answer(gid, text)
                else:
                    self.message = "nothing sent"
            elif key == "esc":
                self.compose = None
                self.message = "nothing sent"
            elif key == "backspace":
                self.compose["text"] = self.compose["text"][:-1]
            elif key == "ctrl-u":
                self.compose["text"] = ""
            elif len(key) == 1:
                self.compose["text"] += key
            return True
        if self.question and not self.log_path:
            row = next((r for r in rows if r["id"] == self.question), None)
            if row is None or not row.get("wait"):
                self.question = None
                self.message = "answered — nothing waiting there now"
            elif key in ("a", "A"):
                self.start_answer(row, editor=key == "A")
            elif key == "m":
                self.merge(row)
            elif key == "l" and row.get("log"):
                self.log_path, self.log_scroll = row["log"], 0
            elif key == "o" and row.get("links"):
                webbrowser.open(row["links"][-1])
            elif NAV.get(key) == "back" or key == "q":
                self.question = None
            return True
        if self.log_path:
            action = NAV.get(key)
            if action in MOVES:
                lines = len(_tail(self.log_path, 2000))
                step = {"down": -1, "up": 1, "pgdn": -self.page, "pgup": self.page,
                        "halfdown": -(self.page // 2), "halfup": self.page // 2,
                        "home": lines, "end": -lines}[action]
                self.log_scroll = max(0, min(lines, self.log_scroll + step))
            elif action == "back" or key == "q":
                self.log_path = None
            return True
        if self.typing:
            if key == "enter":
                self.typing = False
            elif key == "esc":
                self.typing = False
                self.query[vk] = ""
            elif key == "backspace":
                self.query[vk] = self.query.get(vk, "")[:-1]
            elif key in ("up", "down"):
                self.move(key, len(rows))
            elif len(key) == 1:
                self.query[vk] = self.query.get(vk, "") + key
                self.cursor[vk] = 0
            return True
        action = NAV.get(key)
        if key in ("q", "ctrl-c"):
            return False
        if key == "?":
            self.help = True
        elif action == "tab":
            self.goto(int(key[-1]) - 1)
        elif action == "next":
            self.goto((self.tab + (1 if key == "tab" else -1)) % len(TABS))
        elif action in MOVES:
            self.move(action, len(rows))
        elif action == "open":
            self.open(self.selected(rows), key)
        elif action == "back":
            self.back()
        elif key == "/":
            self.typing = True
        else:
            self.act(key, self.selected(rows))
        return True

    # drawing

    def help_line(self):
        name = TABS[self.tab]
        if self.log_path:
            return "↑↓ ^F ^B scroll · g/G top/end · ←/esc/q back"
        if self.typing:
            return "type to filter · enter keep · esc clear"
        if self.compose is not None:
            return "enter send · esc cancel · ^U clear"
        if self.question:
            return "a answer · A answer in $EDITOR · m merge · l log · o open the task · ←/esc back"
        return {
            "Runs": "⏎/→ question or log · a answer · A in $EDITOR · m merge · x stop · r retry · o PR",
            "Boards": ("space queue (on a section: all) · ←/esc back · / filter · R reload"
                       if self.board else "⏎/→ open · / filter · R reload"),
            "Sprint": "⏎ use as sprint · / filter",
            "Daemons": "s start this repo's · x stop · d clear crashed",
        }[name] + " · 1-4 tabs · ? keys · q quit"

    def draw(self, scr, styles):
        scr.erase()
        h, w = scr.getmaxyx()
        put = lambda y, text, style="normal": _put(scr, y, text, w, styles[style])  # noqa: E731
        health = dm.daemon_health(self.daemon, self.alive, time.time())
        sprint = (self.control.get("sprint") or {}).get("name") or "none — pick one in tab 3"
        put(0, "cortex · %s · daemon %s%s · sprint: %s" % (
            os.path.basename(self.main_root), health,
            " (pid %s%s)" % (self.daemon.get("pid"), " " + " ".join(self.daemon.get("forward") or [])
                             if self.daemon.get("forward") else "") if self.alive else "",
            sprint), "bold")
        if self.alive and self.daemon.get("code") != dm.code_version():
            note = ("  daemon runs older code — x then s on the Daemons tab restarts it "
                    if not self.daemon.get("code") else "  daemon updates once its runs finish ")
            _put_at(scr, 1, max(0, w - len(note) - 1), note, w, styles["warn"])
        if self.waits:
            flag = "  ⚑ %d waiting on you " % len(self.waits)
            _put_at(scr, 0, max(0, w - len(flag) - 1), flag, w, styles["warn"])
        x = 0
        for i, t in enumerate(TABS):
            label = " %d %s " % (i + 1, t)
            _put_at(scr, 1, x, label, w, styles["sel"] if i == self.tab else styles["dim"])
            x += len(label) + 1
        self.page = max(1, h - 8)
        rows_now = self.view() if TABS[self.tab] == "Runs" else []
        asked = next((r for r in rows_now if r["id"] == self.question and r.get("wait")), None)
        if self.help:
            for i, line in enumerate(HELP[:h - 4]):
                put(3 + i, line)
        elif asked and not self.log_path:
            wait = asked["wait"]
            put(2, "Runs › %s %s — waiting on you" % (asked["cols"][0], asked["cols"][1]), "dim")
            if wait.get("asked_at"):
                put(3, "asked %s · %s" % (wait["asked_at"][:16].replace("T", " "),
                                          wait.get("kind") or "questions"), "dim")
            for i, (line, style) in enumerate(wait_lines(wait, w)[:h - 8]):
                put(5 + i, "  " + line, style)
        elif self.log_path:
            lines = _tail(self.log_path, 2000)
            body = h - 4
            end = max(0, len(lines) - self.log_scroll)
            for i, line in enumerate(lines[max(0, end - body):end]):
                put(3 + i, *log_line(line))
        else:
            rows = self.view()
            busy, age = self.loading()
            crumb = TABS[self.tab] + (" › %s" % self.board[1]
                                      if TABS[self.tab] == "Boards" and self.board else "")
            query = self.query.get(self.view_key(), "")
            put(2, "%s%s" % (crumb, ("   / %s%s" % (query, "▏" if self.typing else ""))
                             if query or self.typing else ""), "dim")
            if busy or age:
                status = ("%s refreshing…" % spinner(time.time()) if busy and age
                          else "%s loading…" % spinner(time.time()) if busy
                          else age_label(age, time.time()))
                _put_at(scr, 2, max(0, w - len(status) - 2), status, w,
                        styles["warn"] if busy else styles["dim"])
            body = h - 8
            cur = min(self.cursor.get(self.view_key(), 0), max(0, len(rows) - 1))
            top = max(0, cur - body + 1)
            if not rows:
                put(3, "%s loading from Asana…" % spinner(time.time()) if busy else
                    {"Runs": "nothing queued — browse a board (tab 2) and press space on a task",
                     "Daemons": "no daemon is running on this machine"}.get(TABS[self.tab], "nothing here"),
                    "warn" if busy else "dim")
            for i, row in enumerate(rows[top:top + body]):
                style = "sel" if top + i == cur else row.get("style", "normal")
                put(3 + i, fit(row["cols"], w), style)
            row = rows[cur] if rows else None
            detail = []
            if row and TABS[self.tab] == "Runs" and row["kind"] == "task":
                detail = [row["cols"][2]] + row.get("links", [])
                if row.get("wait"):
                    detail = ["⚑ waiting on you — ⏎ to read it all, a to answer"] + detail[1:]
            for i, line in enumerate(detail[:4]):
                put(h - 6 + i, "  " + line, "dim")
        if self.compose is not None:
            prompt = "answer › "
            text = self.compose["text"]
            room = max(1, w - len(prompt) - 3)
            put(h - 2, prompt + (text[-room:] if len(text) > room else text) + "▏", "warn")
        else:
            put(h - 2, self.message, "warn")
        put(h - 1, self.help_line(), "dim")
        scr.refresh()


def _put(scr, y, text, width, attr):
    _put_at(scr, y, 0, text, width, attr)


def _put_at(scr, y, x, text, width, attr):
    try:
        scr.addnstr(y, x, text, max(0, width - 1 - x), attr)
    except curses.error:
        pass


def _tail(path, n):
    try:
        with open(path, "r", errors="replace") as f:
            return [line.rstrip("\n") for line in f.readlines()[-n:]]
    except (IOError, OSError):
        return ["(no log yet at %s)" % path]


def run_ui(main_root, forward):
    os.environ.setdefault("ESCDELAY", "25")

    def loop(scr):
        curses.curs_set(0)
        scr.timeout(1000)
        styles = {"normal": curses.A_NORMAL, "bold": curses.A_BOLD, "dim": curses.A_DIM,
                  "sel": curses.A_REVERSE, "ok": curses.A_NORMAL, "warn": curses.A_BOLD,
                  "bad": curses.A_BOLD}
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for n, color in ((1, curses.COLOR_GREEN), (2, curses.COLOR_YELLOW),
                             (3, curses.COLOR_RED)):
                curses.init_pair(n, color, -1)
            styles.update(ok=curses.color_pair(1), warn=curses.color_pair(2),
                          bad=curses.color_pair(3) | curses.A_BOLD)
        app = App(main_root, forward)
        while True:
            app.snapshot()
            app.sync()
            app.draw(scr, styles)
            idle = 100 if app.loader.busy() else 1000
            scr.timeout(idle)
            key = read_key(scr, idle)
            if key is None:
                continue
            try:
                if not app.key(key, app.view() if not app.log_path else []):
                    return
            except Stop as e:
                app.message = str(e)
            if app.edit_request:
                gid, app.edit_request = app.edit_request, None
                wait = app.waits.get(gid) or {}
                text = edit_answer(scr, answer_template(wait.get("key") or gid, wait))
                if text:
                    app.answer(gid, text)
                else:
                    app.message = "nothing sent"
    curses.wrapper(loop)


def edit_answer(scr, template):
    """Open $VISUAL / $EDITOR on the template and return the answer written, the
    way `git commit` does."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    fd, path = tempfile.mkstemp(prefix="cortex-answer-", suffix=".md")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(template)
        curses.def_prog_mode()
        curses.endwin()
        subprocess.call(shlex.split(editor) + [path])
        curses.reset_prog_mode()
        scr.clear()
        with open(path) as f:
            return parse_answer(f.read())
    finally:
        os.remove(path)


def print_status(main_root):
    control = dm.read_control(main_root)
    data = dm.read_json(os.path.join(dm.queue_dir(main_root), "state.json")) or {}
    info, alive = dm.daemon_info(main_root)
    sys.stdout.write("daemon:  %s%s\n" % (dm.daemon_health(info, alive, time.time()),
                                         " (pid %s)" % info.get("pid") if alive else ""))
    sys.stdout.write("sprint:  %s\n" % ((control.get("sprint") or {}).get("name") or "none"))
    live = dm.live_runs(main_root)
    waits = read_waits(main_root, control, data)
    rows = run_rows(control, data, live, agents=dm.live_agents(main_root, [p for _, p in live]),
                    waits=waits)
    if not rows:
        sys.stdout.write("\nnothing queued\n")
    if waits:
        sys.stdout.write("\n⚑ %d waiting on you — answer in `cortex tui`, or on the task\n"
                         % len(waits))
    for row in rows:
        sys.stdout.write("\n  %-8s %s\n           %s\n" % tuple(row["cols"]))
        for text, _ in wait_lines(row.get("wait") or {}, 100) if row.get("wait") else []:
            sys.stdout.write("           %s\n" % text)
        for link in row.get("links") or []:
            sys.stdout.write("           %s\n" % link)
    others = [(p, i, a) for p, i, a in dm.registered() if i.get("main_root") != main_root]
    if others:
        sys.stdout.write("\nother daemons:\n")
        for row in daemon_rows(others, time.time()):
            sys.stdout.write("  %s — %s, %s, %s\n" % tuple(row["cols"]))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cortex tui",
        description="Browse boards, queue tasks, and watch the runs that work them. "
                    "Arguments not listed here are passed to every start-task run.")
    parser.add_argument("--repo", default=os.getcwd(), help="target repository (default: cwd)")
    parser.add_argument("--status", action="store_true",
                        help="print the queue and the daemon; no UI")
    parser.add_argument("--stop", action="store_true",
                        help="stop this repo's daemon, and the runs it launched")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv):
    args, forward = build_parser().parse_known_args(argv)
    if "--no-wait" in forward:
        sys.stderr.write("tui: --no-wait does not apply — every run waits on its own "
                         "questions\n")
        return 2
    try:
        main_root = st.main_repo_root(os.path.abspath(args.repo))
    except st.Failure as e:
        sys.stderr.write("tui: %s\n" % e)
        return 1
    try:
        if args.serve:
            dm.QueueRun(main_root, forward).serve()
            return 0
        if args.status:
            print_status(main_root)
            return 0
        if args.stop:
            info, alive = dm.daemon_info(main_root)
            if not alive:
                sys.stdout.write("no daemon running for %s\n" % main_root)
                return 0
            dm.stop_daemon(info)
            sys.stdout.write("stopping the daemon (pid %s)\n" % info["pid"])
            return 0
        run_ui(main_root, forward)
        return 0
    except Stop as e:
        sys.stderr.write("\ntui: %s\n" % e)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
