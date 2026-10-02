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

TABS = ("Runs", "Boards", "Setup", "Daemons")
MERGE_LABELS = {
    "branches": "automatically, unless it targets the default branch (recommended)",
    "always": "always automatically, the default branch included",
    "asked": "only when asked — m on a task",
}
BRANCHES_MAX_AGE = 60
# git run from the UI must never ask for anything: a prompt would take over the
# terminal the UI is drawing on, and look like a hang. It fails instead, saying why.
NO_PROMPT = dict(os.environ, GIT_TERMINAL_PROMPT="0",
                 GIT_SSH_COMMAND=os.environ.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes")
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


# What each kind of wait asks of you, for when the run recorded no headline.
WAIT_ASKS = {
    "questions": "has questions for you",
    "qa": "QA is still failing after its repairs — tell it how to proceed",
    "push": "could not push — fix it or say how, then reply",
    "pr": "something is wrong with its PR — fix it or say how, then reply",
    "stall": "the agent stopped making progress — tell it how to go on",
    "agent": "the agent call failed — reply to retry",
    "failure": "the run stopped on an error — reply to retry",
}


def wait_summary(wait):
    """One line for what a task is waiting on you for — and what that asks of you."""
    kind = wait.get("kind")
    if kind == "conflict":
        return "PR conflicts with its base — a to have it resolved, m to merge"
    if kind == "merge":
        return wait["headline"] + " — m tries again"
    questions = wait.get("questions") or []
    if questions:
        more = len(questions) - 1
        return "has questions for you: %s%s" % (questions[0].get("q", ""),
                                                " (+%d more)" % more if more else "")
    if wait.get("headline"):
        return "%s — ⏎ to read, a to reply" % wait["headline"]
    return WAIT_ASKS.get(kind, "waiting on a reply from you") + " · ⏎ to read"


_STEP = re.compile(r"^(\d\d):(\d\d):(\d\d)  (.+)$")
_CALLING = re.compile(r"^  ([\w-]+): calling ")
_DONE_CALL = re.compile(r"^  ([\w-]+): \S+ · ")
_GATE = re.compile(r"^  ([\w./-]+): (.+?)(?: \(in .+\))?$")
_GATE_OK = re.compile(r"^  ([\w./-]+) ok$")
_GATE_FAILED = re.compile(r"^  ! ([\w./-]+) failed \(exit")


def last_step(lines, now):
    """What a run is doing, from the end of its task's log: (step, detail,
    seconds at it), or None. The detail is an agent call still out, or a QA gate
    still running."""
    lines = [_ANSI.sub("", line) for line in lines]
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not line.strip() or line[0].isspace() or line.startswith(("━━", "====")):
            continue
        m = _STEP.match(line)
        started = None
        step = m.group(4) if m else line.strip()
        if m:
            local = time.localtime(now)
            started = time.mktime(local[:3] + tuple(int(m.group(n)) for n in (1, 2, 3))
                                  + local[6:9])
            if started > now:
                started -= 86400
        detail, calls, gates = None, {}, {}
        for line in lines[i + 1:]:
            called, answered = _CALLING.match(line), _DONE_CALL.match(line)
            finished = _GATE_OK.match(line) or _GATE_FAILED.match(line)
            gate = _GATE.match(line) if step == "QA" else None
            if called:
                calls[called.group(1)] = True
            elif answered:
                calls.pop(answered.group(1), None)
            elif finished:
                gates.pop(finished.group(1), None)
            elif gate:
                gates[gate.group(1)] = gate.group(2)
        if calls:
            detail = "agent at work"
        elif gates:
            detail = list(gates.values())[-1]
        return step, detail, None if started is None else max(0, now - started)
    return None


def _ago(seconds):
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm" % (seconds // 60)
    return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


PENDING_SAYS = {
    "merge": "merge asked",
    "merge-cancel": "calling the merge off",
    "retarget": "base branch change to %(base)s asked",
    "stop": "stop asked",
    "retry": "retry asked",
}


def row_activity(record, pending, busy, log_lines, now):
    """What is happening to one task right now, in a few words, or None to fall
    back on its phase: a command of yours the daemon has not acted on yet, then
    something the daemon is in the middle of for it, then where its run is."""
    if pending:
        cmd = pending[-1]
        return "%s — waiting for the daemon" % (PENDING_SAYS.get(cmd["op"], cmd["op"]) % cmd)
    if busy:
        return "%s…" % busy
    if (record or {}).get("phase") in ("running", "revising"):
        step = last_step(log_lines or [], now)
        if step:
            name, detail, seconds = step
            what = "revising" if record["phase"] == "revising" else "running"
            return "%s — %s%s%s" % (what, name, " · %s" % detail if detail else "",
                                    " · %s" % _ago(seconds) if seconds is not None else "")
    return None


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


def run_rows(control, data, live, me_gid=None, agents=(), waits=None, activity=None):
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
        now_doing = (activity or {}).get(gid)
        if now_doing:
            status = now_doing
        elif record.get("phase") == "pr_open" and not record.get("merge"):
            status = "PR open — waiting for review; m merges"
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


def setup_rows(control, default_branch=None):
    """The Setup tab: what new work goes into, and whether it is merged."""
    sprint = (control.get("sprint") or {}).get("name")
    base = control.get("base")
    mode = control.get("merge_mode") if control.get("merge_mode") in MERGE_LABELS else "branches"
    return [
        {"kind": "setting", "id": "sprint", "style": "normal" if sprint else "warn",
         "cols": ["Sprint", sprint or "none — pick one; nothing starts until you do"]},
        {"kind": "setting", "id": "base", "style": "normal",
         "cols": ["Target branch", base or "the default branch%s"
                  % (" (%s)" % default_branch if default_branch else "")]},
        {"kind": "setting", "id": "merge", "style": "normal",
         "cols": ["Merging", MERGE_LABELS[mode]]},
    ]


def parse_ls_remote(text):
    """(default branch, [branches]) from `git ls-remote --symref origin HEAD
    'refs/heads/*'`."""
    default, branches = None, []
    for line in (text or "").splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            default = line[len("ref: refs/heads/"):-len("\tHEAD")]
        elif "\trefs/heads/" in line:
            branches.append(line.split("\trefs/heads/", 1)[1])
    return default, sorted(branches, key=lambda b: (b != default, b.lower()))


def branch_rows(branches, default, query, current):
    """Branches to pick the target from, filtered, after a row for starting a new
    one from the default branch."""
    rows = [{"kind": "new", "id": "+new", "style": "warn",
             "cols": ["+ New branch…", "from origin/%s, as it is on GitHub now"
                      % (default or "the default branch")]}]
    for b in branches or []:
        if not matches(b, query):
            continue
        picked = b == current or (current is None and b == default)
        rows.append({"kind": "branch", "id": b, "style": "bold" if picked else "normal",
                     "cols": [b, ("default" if b == default else "")
                              + (" ← target" if picked else "")]})
    return rows


def valid_branch_name(name):
    """Whether git would take this as a branch name."""
    return bool(re.fullmatch(r"[A-Za-z0-9._/-]+", name or "")) and not (
        name.startswith(("/", "-", ".")) or name.endswith(("/", ".", ".lock"))
        or ".." in name or "//" in name or "@{" in name)


def palette_matches(commands, query):
    """The palette's commands for a query: every word must appear in the title
    or the words it is also known by, in the order given."""
    return [c for c in commands if matches("%s %s" % (c["title"], c.get("words", "")), query)]


def extra_commits(main_root, branch, old, new):
    """How many commits a PR on `branch` would gain by moving from base `old` to
    `new`: those it carries from `old` that `new` does not have. Fetches first."""
    def git(*args):
        done = subprocess.run(["git"] + list(args), cwd=main_root, stdin=subprocess.DEVNULL,
                              env=NO_PROMPT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            raise Stop(done.stderr.decode("utf-8", "replace").strip().splitlines()[-1])
        return done.stdout.decode().strip()
    git("fetch", "origin", old, new, branch)
    fork = git("merge-base", "origin/%s" % branch, "origin/%s" % old)
    return int(git("rev-list", "--count", "origin/%s..%s" % (new, fork)))


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
    """A log line as (text, style): terminal escape codes removed. A step heading
    — any line not indented, or one a run set in bold — shows bold; a run's
    opening header stands out."""
    text = _ANSI.sub("", line).replace("\t", "    ")
    if text.startswith("━━"):
        return text, "warn"
    heading = "\x1b[1m" in line or (text.strip() and not text[0].isspace())
    return text, "bold" if heading else "normal"


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
            4: "ctrl-d", 21: "ctrl-u", 1: "ctrl-a", 5: "ctrl-e", 11: "ctrl-k", 23: "ctrl-w"}
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
    "commands    :   the command palette — the commands with no key in the line below",
    "            (changing a PR's base branch, the daemon from any tab…)",
    "typing      ^A ^E start/end · ^B ^F ←→ a character · alt-B alt-F a word ·",
    "            ^K ^U delete to end/start · ^W the word before · ^D delete forward",
    "",
    "Runs        m merge: get it onto main — conflicts resolved, failing checks fixed,",
    "            then merged; m again calls it off · on a blocked merge, m tries again",
    "            ⏎ on a ⚑ task reads what it is waiting on · a answer it in one line ·",
    "            A answer in $EDITOR · on a parked conflict, a asks for a resolve",
    "            x stop and unqueue · r retry · o open the PR or task",
    "Boards      space queue or unqueue a task; on a section, queue all of it · R reload",
    "Setup       ⏎ on Sprint picks the sprint board · on Target branch picks the branch",
    "            new runs PR into — + New branch… (or n) creates one on origin ·",
    "            on Merging cycles: unless the default branch / always / only when asked",
    "Daemons     s start this repo's daemon · x stop one · d clear a crashed one",
    "",
    "q quits the UI; the daemon keeps working.                      any key closes this",
]


class LineEdit(object):
    """One line of text being typed, with the cursor somewhere in it, and the
    keys every Unix line takes: readline's emacs bindings and the arrows. Used by
    every text input, so typing never sets off a hotkey."""

    def __init__(self, text=""):
        self.text, self.pos = text, len(text)

    def word_left(self):
        i = self.pos
        while i > 0 and not self.text[i - 1].isalnum():
            i -= 1
        while i > 0 and self.text[i - 1].isalnum():
            i -= 1
        return i

    def word_right(self):
        i, n = self.pos, len(self.text)
        while i < n and not self.text[i].isalnum():
            i += 1
        while i < n and self.text[i].isalnum():
            i += 1
        return i

    def key(self, key):
        """Apply a key. False when it is not an editing key, for the caller."""
        t, p = self.text, self.pos
        if key in ("ctrl-a", "home"):
            self.pos = 0
        elif key in ("ctrl-e", "end"):
            self.pos = len(t)
        elif key in ("ctrl-b", "left"):
            self.pos = max(0, p - 1)
        elif key in ("ctrl-f", "right"):
            self.pos = min(len(t), p + 1)
        elif key == "alt-b":
            self.pos = self.word_left()
        elif key == "alt-f":
            self.pos = self.word_right()
        elif key == "ctrl-k":
            self.text = t[:p]
        elif key == "ctrl-u":
            self.text, self.pos = t[p:], 0
        elif key == "ctrl-w":
            start = self.word_left()
            self.text, self.pos = t[:start] + t[p:], start
        elif key == "backspace":
            if p:
                self.text, self.pos = t[:p - 1] + t[p:], p - 1
        elif key in ("ctrl-d", "delete"):
            self.text = t[:p] + t[p + 1:]
        elif len(key) == 1:
            self.text, self.pos = t[:p] + key + t[p:], p + 1
        else:
            return False
        return True

    def show(self, room=None):
        """The text with the cursor drawn in it, scrolled to keep it in view."""
        text = self.text[:self.pos] + "▏" + self.text[self.pos:]
        if room and len(text) > room:
            start = max(0, min(self.pos - room + 2, len(text) - room))
            text = text[start:start + room]
        return text


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
        self.setup = None
        self.branches, self.default_branch, self.branches_at = None, None, None
        cached, at = self.cache.get("branches-%s" % os.path.basename(main_root))
        if cached:
            self.default_branch, self.branches = cached
            self.branches_at = at
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
        self.creating = None
        self.retargeting = None
        self.palette = None
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
        self.activity = self.read_activity()
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

    def read_activity(self):
        """What is happening to each queued task right now: commands of yours not
        yet acted on, the daemon's work on it, its run's current step."""
        applied = self.data.get("applied", 0)
        busy = (self.daemon or {}).get("busy_tasks") or {}
        records = self.data.get("records") or {}
        out = {}
        for item in self.control.get("queue") or []:
            gid = item["gid"]
            record = records.get(gid) or {}
            pending = [c for c in self.control.get("commands") or []
                       if c.get("gid") == gid and c["id"] > applied]
            lines = _tail(record["log"], 400) if record.get("phase") in ("running", "revising") \
                and record.get("log") else None
            doing = row_activity(record, pending, busy.get(gid) if self.alive else None,
                                 lines, time.time())
            if doing:
                out[gid] = doing
        return out

    def fetch_branches(self):
        code = subprocess.run(["git", "ls-remote", "--symref", "origin", "HEAD", "refs/heads/*"],
                              cwd=self.main_root, stdin=subprocess.DEVNULL, env=NO_PROMPT,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if code.returncode != 0:
            raise Stop(code.stderr.decode("utf-8", "replace").strip() or "git ls-remote failed")
        default, branches = parse_ls_remote(code.stdout.decode("utf-8", "replace"))
        self.cache.put("branches-%s" % os.path.basename(self.main_root), [default, branches])
        return default, branches

    def refresh_branches(self, max_age=BRANCHES_MAX_AGE):
        if is_stale(self.branches_at, time.time(), max_age):
            self.loader.start("branches", "branches", self.fetch_branches)

    def new_branch(self, name):
        """A name typed for a new target branch: checked, then confirmed — it is a
        push to origin."""
        if not name:
            self.message = "no branch created"
        elif not valid_branch_name(name):
            self.message = "%r is not a name git takes for a branch" % name
        elif name in (self.branches or []):
            self.set_base(name)
        else:
            self.ask("create %s on origin from origin/%s (fetched first)? (y/n)"
                     % (name, self.default_branch or "the default branch"),
                     lambda: self.create_branch(name))

    def create_branch(self, name):
        """Create the target branch on origin from the default branch, then use it."""
        default = self.default_branch or "main"

        def work():
            for cmd in (["git", "fetch", "origin", default],
                        ["git", "push", "origin", "refs/remotes/origin/%s:refs/heads/%s"
                         % (default, name)]):
                done = subprocess.run(cmd, cwd=self.main_root, stdin=subprocess.DEVNULL,
                                      env=NO_PROMPT, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                if done.returncode != 0:
                    raise Stop(done.stderr.decode("utf-8", "replace").strip().splitlines()[-1])
            return self.fetch_branches()

        self.loader.start("create-branch", name, work)
        self.creating = name
        self.message = "fetching origin/%s and creating %s from it…" % (default, name)

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
        done = self.loader.take("retarget")
        if done and self.retargeting:
            row, old, target = self.retargeting
            self.retargeting = None
            extra = done[0]
            dragged = ("" if extra == 0 else " — it would bring %d commit(s) from %s that %s does "
                       "not have" % (extra, old, target) if extra else
                       " — could not tell what it brings (%s)" % (done[1] or "?"))
            self.ask("move %s's PR from %s onto %s%s? (y/n)" % (row["cols"][0], old, target, dragged),
                     lambda: self.command("retarget", row["id"], base=target))
        done = self.loader.take("branches")
        if done:
            if done[1]:
                self.message = "could not list the branches: %s" % done[1]
            else:
                (self.default_branch, self.branches), self.branches_at = done[0], now
        done = self.loader.take("create-branch")
        if done:
            name, self.creating = self.creating, None
            if done[1]:
                self.message = "could not create %s: %s" % (name, done[1])
            else:
                (self.default_branch, self.branches), self.branches_at = done[0], now
                self.set_base(name)
        if TABS[self.tab] == "Boards" and self.board:
            self.refresh_board(self.board[0], BOARD_SHOWN_MAX_AGE)
        elif TABS[self.tab] == "Boards" or self.setup == "sprint":
            self.refresh_boards()
        elif TABS[self.tab] == "Setup":
            self.refresh_branches()

    def loading(self):
        """(busy, age) of what is on screen: whether a load is running for it, and
        how old the copy shown is."""
        if TABS[self.tab] == "Boards" and self.board:
            gid = self.board[0]
            return self.loader.busy("sections-%s" % gid), self.sections_at.get(gid)
        if TABS[self.tab] == "Boards" or self.setup == "sprint":
            return self.loader.busy("boards"), self.boards_at
        if self.setup == "base":
            return (self.loader.busy("branches") or self.loader.busy("create-branch"),
                    self.branches_at)
        return False, None

    def view(self):
        """(view name, rows) for what is on screen."""
        name = TABS[self.tab]
        query = self.query.get(self.view_key(), "")
        if name == "Runs":
            return run_rows(self.control, self.data, self.live, agents=self.agents,
                            waits=self.waits, activity=self.activity)
        if name == "Boards" and self.board:
            queued = {q["gid"] for q in self.control["queue"]}
            return board_rows(self.board[0], self.sections.get(self.board[0]), queued,
                              self.data.get("records") or {}, query, self.data.get("tasks"))
        if name == "Boards" or (name == "Setup" and self.setup == "sprint"):
            return board_list_rows(self.boards, query, self.control.get("sprint"))
        if name == "Setup" and self.setup == "base":
            return branch_rows(self.branches, self.default_branch, query, self.control.get("base"))
        if name == "Setup":
            return setup_rows(self.control, self.default_branch)
        return daemon_rows(dm.registered(), time.time())

    def view_key(self):
        if TABS[self.tab] == "Boards" and self.board:
            return "board:%s" % self.board[0]
        if TABS[self.tab] == "Setup" and self.setup:
            return "Setup:%s" % self.setup
        return TABS[self.tab]

    def set_base(self, name):
        base = None if name == self.default_branch else name
        self.change_control(lambda c: c.update(base=base))
        self.setup = None
        self.message = ("target branch: %s — new runs branch off it and open their PR "
                        "against it; open PRs keep theirs" % (name if base else "the default (%s)" % name))

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
            "" if self.control.get("sprint") else " — pick a sprint (Setup, tab 3) before they start"
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
            self.compose = {"kind": "answer", "gid": row["id"], "text": "", "line": LineEdit()}

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

    def palette_commands(self, row):
        """What the palette offers: only commands that are not already in plain
        sight — none with a key shown in the line at the bottom — and only ones
        that can run right now."""
        out = []
        if TABS[self.tab] == "Runs" and row and row["kind"] == "task":
            target = self.control.get("base") or self.default_branch
            git_info = (st.State(self.main_root, row["cols"][0]).read("context.json") or {}).get("git") or {}
            old = (git_info.get("base") or "").replace("origin/", "", 1)
            if (row.get("pr_url") and row.get("phase") in ("pr_open", "conflict")
                    and target and old != target):
                out.append({"title": "Change %s's PR base branch to %s" % (row["cols"][0], target),
                            "words": "retarget move update base branch pr from %s" % old,
                            "run": lambda: self.retarget(row)})
        if TABS[self.tab] != "Daemons":
            if not self.alive:
                out.append({"title": "Start this repo's daemon", "words": "run begin",
                            "run": self.ensure_daemon})
            else:
                out.append({"title": "Stop this repo's daemon and its runs", "words": "kill end",
                            "run": lambda: self.ask("stop the daemon and its runs? (y/n)",
                                                    lambda: dm.stop_daemon(self.daemon))})
        return out

    def palette_key(self, key):
        """A key while the palette is open: the line takes every editing key,
        ↑↓ (or ^P ^N) choose, enter runs."""
        shown = palette_matches(self.palette["commands"], self.palette["query"])
        if key == "esc":
            self.palette = None
        elif key == "enter":
            pick = shown[min(self.palette["cursor"], len(shown) - 1)] if shown else None
            self.palette = None
            if pick:
                pick["run"]()
        elif key in ("up", "down", "ctrl-n", "ctrl-p"):
            step = 1 if key in ("down", "ctrl-n") else -1
            self.palette["cursor"] = max(0, min(len(shown) - 1, self.palette["cursor"] + step))
        elif self.palette["line"].key(key):
            self.palette["query"] = self.palette["line"].text
            self.palette["cursor"] = 0

    def retarget(self, row):
        """Offer to move a task's open PR onto the current target branch — after
        counting what the move would drag in with it."""
        target = self.control.get("base") or self.default_branch
        state = st.State(self.main_root, row["cols"][0])
        git_info = (state.read("context.json") or {}).get("git") or {}
        old = (git_info.get("base") or "").replace("origin/", "", 1)
        if row.get("phase") not in ("pr_open", "conflict") or not row.get("pr_url"):
            self.message = "b moves an open PR — %s has none" % row["cols"][0]
        elif not target:
            self.message = "no target branch known yet — open Setup once to read the branches"
        elif old == target:
            self.message = "%s's PR already targets %s" % (row["cols"][0], target)
        else:
            self.message = "checking what moving %s onto %s brings with it…" % (row["cols"][0], target)
            self.loader.start("retarget", "retarget", lambda: extra_commits(
                self.main_root, git_info.get("branch"), old, target))
            self.retargeting = (row, old, target)

    def command(self, op, gid, **extra):
        applied = self.data.get("applied", 0)
        cid = self.change_control(lambda c: dm.add_command(c, op, gid, applied, **extra))
        key = ((self.data.get("tasks") or {}).get(gid) or {}).get("key") or gid
        self.sent.append({"id": cid, "op": op, "key": key, "at": time.time()})
        self.follow_commands()

    def follow_commands(self):
        """Say what became of each command sent: done, ignored, or still waiting."""
        for sent in list(self.sent):
            message, settled = dm.command_feedback(
                sent, self.data.get("applied", 0), self.data.get("results"),
                self.alive, time.time(), (self.daemon or {}).get("busy") or ())
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
        elif name == "Boards" and key == "R":
            self.refresh_boards(max_age=-1)
        elif name == "Setup" and self.setup == "base" and key == "n":
            self.compose = {"kind": "branch", "text": "", "line": LineEdit()}
        elif name == "Setup" and self.setup == "base" and key == "R":
            self.refresh_branches(max_age=-1)
        elif name == "Setup" and self.setup == "sprint" and key == "R":
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
        elif name == "Setup" and self.setup == "sprint" and key == "enter":
            sprint = {"gid": row["id"], "name": row["name"]}
            self.change_control(lambda c: c.update(sprint=sprint))
            self.setup = None
            self.message = "sprint: %s" % row["name"]
        elif name == "Setup" and self.setup == "base" and key == "enter":
            if row["kind"] == "new":
                self.compose = {"kind": "branch", "text": "", "line": LineEdit()}
            else:
                self.set_base(row["id"])
        elif name == "Setup" and not self.setup:
            if row["id"] == "merge":
                order = list(MERGE_LABELS)
                mode = self.control.get("merge_mode")
                mode = mode if mode in MERGE_LABELS else "branches"
                nxt = order[(order.index(mode) + 1) % len(order)]
                self.change_control(lambda c: c.update(merge_mode=nxt))
                self.message = "merging: %s" % MERGE_LABELS[nxt]
            else:
                self.setup = row["id"]
                self.query[self.view_key()] = ""
                rows = self.view()
                current = (self.control.get("base") or self.default_branch) if self.setup == "base" \
                    else (self.control.get("sprint") or {}).get("gid")
                ids = [r["id"] for r in rows]
                self.cursor[self.view_key()] = ids.index(current) if current in ids else 0

    def back(self):
        """Out one level: a filter first, then the board you are in."""
        vk = self.view_key()
        if self.query.get(vk):
            self.query[vk] = ""
            self.cursor[vk] = 0
        elif TABS[self.tab] == "Boards" and self.board:
            self.board = None
        elif TABS[self.tab] == "Setup" and self.setup:
            self.setup = None

    def goto(self, tab):
        if tab == self.tab:
            self.board = None if TABS[tab] == "Boards" else self.board
            self.setup = None if TABS[tab] == "Setup" else self.setup
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
        if self.palette is not None:
            self.palette_key(key)
            return True
        if self.compose is not None:
            if key == "enter":
                text = self.compose["text"].strip()
                compose, self.compose = self.compose, None
                if compose.get("kind") == "branch":
                    self.new_branch(text)
                elif text:
                    self.answer(compose["gid"], text)
                else:
                    self.message = "nothing sent"
            elif key == "esc":
                self.compose = None
                self.message = "nothing sent"
            elif self.compose["line"].key(key):
                self.compose["text"] = self.compose["line"].text
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
            elif key in ("up", "down"):
                self.move(key, len(rows))
            elif self.line.key(key):
                self.query[vk] = self.line.text
                self.cursor[vk] = 0
            return True
        action = NAV.get(key)
        if key in ("q", "ctrl-c"):
            return False
        if key == "?":
            self.help = True
        elif key == ":":
            self.palette = {"query": "", "cursor": 0, "line": LineEdit(),
                            "commands": self.palette_commands(self.selected(rows))}
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
            self.line = LineEdit(self.query.get(vk, ""))
        else:
            self.act(key, self.selected(rows))
        return True

    # drawing

    def help_line(self):
        name = TABS[self.tab]
        if self.palette is not None:
            return "type to narrow · ↑↓ choose · ⏎ run · esc close"
        if self.log_path:
            return "↑↓ ^F ^B scroll · g/G top/end · ←/esc/q back"
        if self.typing:
            return "type to filter · enter keep · esc clear"
        if self.compose is not None:
            return ("enter create · esc cancel · ^U clear — any characters, / included"
                    if self.compose.get("kind") == "branch" else "enter send · esc cancel · ^U clear")
        if self.question:
            return "a answer · A answer in $EDITOR · m merge · l log · o open the task · ←/esc back"
        return {
            "Runs": "⏎/→ question or log · a answer · A $EDITOR · m merge · x stop · r retry · o PR",
            "Boards": ("space queue (on a section: all) · ←/esc back · / filter · R reload"
                       if self.board else "⏎/→ open · / filter · R reload"),
            "Setup": ("⏎ use it · n new branch · / search · ←/esc back" if self.setup == "base"
                      else "⏎ use it · / search · ←/esc back" if self.setup else "⏎ change it (on Merging: cycles through the three)"),
            "Daemons": "s start this repo's · x stop · d clear crashed",
        }[name] + " · : commands · 1-4 tabs · ? keys · q quit"

    def draw(self, scr, styles):
        scr.erase()
        h, w = scr.getmaxyx()
        put = lambda y, text, style="normal": _put(scr, y, text, w, styles[style])  # noqa: E731
        health = dm.daemon_health(self.daemon, self.alive, time.time())
        sprint = (self.control.get("sprint") or {}).get("name") or "none — pick one in Setup"
        sprint += " · → %s" % (self.control.get("base") or self.default_branch or "default branch")
        sprint += {"always": " · auto-merge: always", "asked": " · merge: when asked"}.get(
            self.control.get("merge_mode"), " · auto-merge: off the default branch")
        if health == "busy":
            health = "busy: %s" % "; ".join(self.daemon.get("busy") or [])
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
            put(2, "%s%s" % (crumb, ("   / %s" % (self.line.show() if self.typing else query))
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
                picked = top + i == cur
                style = "sel" if picked else row.get("style", "normal")
                put(3 + i, ("▸ " if picked else "  ") + fit(row["cols"], w - 2), style)
            row = rows[cur] if rows else None
            detail = []
            if row and TABS[self.tab] == "Runs" and row["kind"] == "task":
                detail = [row["cols"][2]] + row.get("links", [])
                if row.get("wait"):
                    detail = ["⚑ waiting on you — ⏎ to read it all, a to answer"] + detail[1:]
            for i, line in enumerate(detail[:4]):
                put(h - 6 + i, "  " + line, "dim")
        if self.compose is not None:
            prompt = ("new branch from origin/%s › " % (self.default_branch or "the default branch")
                      if self.compose.get("kind") == "branch" else "answer › ")
            put(h - 2, prompt + self.compose["line"].show(max(1, w - len(prompt) - 3)), "warn")
        else:
            put(h - 2, self.message, "warn")
        put(h - 1, self.help_line(), "dim")
        if self.palette is not None:
            self.draw_palette(scr, styles, h, w)
        scr.refresh()

    def draw_palette(self, scr, styles, h, w):
        """A framed box: the line being typed on top, then the commands, the chosen
        one marked as well as highlighted — so one or two are never ambiguous."""
        shown = palette_matches(self.palette["commands"], self.palette["query"])
        width = max(30, min(w - 4, 86))
        left = max(0, (w - width) // 2)
        rows = max(1, min(len(shown), h - 10))
        cur = min(self.palette["cursor"], max(0, len(shown) - 1))
        top = max(0, cur - rows + 1)
        inner = width - 4

        def row(y, text, attr, edge="│"):
            body = text[:inner].ljust(inner)
            _put_at(scr, y, left, edge, left + 2, styles["dim"])
            _put_at(scr, y, left + 1, " " + body + " ", left + width, attr)
            _put_at(scr, y, left + width - 1, edge, left + width + 1, styles["dim"])

        def rule(y, a, b):
            _put_at(scr, y, left, a + "─" * (width - 2) + b, left + width + 1, styles["dim"])

        for y in range(3, 3 + 4 + max(1, min(len(shown), rows))):
            _put_at(scr, y, 0, " " * w, w, styles["normal"])
        _put_at(scr, 3, left, "╭─ commands " + "─" * (width - 13) + "╮", left + width + 1,
                styles["dim"])
        row(4, ": " + self.palette["line"].show(inner - 2), styles["bold"])
        rule(5, "├", "┤")
        y = 6
        if not shown:
            row(y, "nothing here beyond the keys below" if not self.palette["commands"]
                else "nothing matches", styles["dim"])
            y += 1
        for i, cmd in enumerate(shown[top:top + rows]):
            picked = top + i == cur
            row(y, ("▸ " if picked else "  ") + cmd["title"], styles["sel"] if picked
                else styles["normal"])
            y += 1
        rule(y, "╰", "╯")


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
