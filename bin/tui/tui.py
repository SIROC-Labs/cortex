#!/usr/bin/env python3
#
# tui — browse boards, start goals on tickets and watch them work.
#
# A terminal UI over this repo's goals. Browse any board and run a ticket or a
# milestone as a goal: it works by itself, on its own branch, into one PR, and
# asks you only what it cannot decide. The Runs tab shows every goal and its
# parts, what each is doing, and what waits on you; the Setup tab picks the
# branch goals go into, their models and who approves their plans. Goals run in
# processes of their own: closing the TUI leaves them working.
#
#   cond tui                    # the UI (run from inside the target repo)
#   cond tui --status           # the goals, printed; no UI
#
# Dependencies: Python 3 stdlib (curses), git, gh, and goal (a sibling directory).

import argparse
import curses
import json
import os
import re
import shlex
import signal
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
from engine import ASANA, Stop, task_url  # noqa: E402
from daemon import st  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "goal"))
import goal as gl  # noqa: E402
import goal_view as gv  # noqa: E402

TABS = ("Runs", "Boards", "Setup")
# Who approves a goal's plan before it is built.
GATE_LABELS = {
    "wait": "you, for the goal and each of its parts (recommended)",
    "top": "you for the goal; the reviewer agent for its parts",
    "auto": "the reviewer agent only — goals never wait for you to approve",
}
# The models the Setup tab offers, strongest last but one, and the effort levels.
MODELS = [("claude-haiku-4-5-20251001", "haiku"), ("claude-sonnet-5-5", "sonnet"),
          ("claude-opus-5-5", "opus"), ("claude-fable-5-1", "fable")]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
# The Setup tab's model rows: (id, label, key in control["models"], default, what it is).
MODEL_SETTINGS = [
    ("model-lead", "Goal lead", "lead", gl.DEFAULT_MODEL, "plans a goal and judges its sub-agents"),
    ("model-subagent", "Goal sub-agents", "subagent", gl.DEFAULT_SUBAGENT_MODEL,
     "the lead's narrow, well-briefed parts — it can ask for more"),
    ("model-check", "Goal checker", "check", gl.DEFAULT_CHECK_MODEL,
     "only verifies the branch against the ask, and reports"),
    ("effort-check", "Checker effort", "check_effort", gl.DEFAULT_CHECK_EFFORT,
     "how hard the checker thinks"),
]
BRANCHES_MAX_AGE = 60
MODEL_NOTES = {"haiku": "fastest and cheapest — simple, mechanical work",
               "sonnet": "fast and capable — narrow, well-briefed work",
               "opus": "deep reasoning — planning, design and hard problems",
               "fable": "the strongest and priciest — judging and verifying"}
EFFORT_NOTES = {"low": "quick", "medium": "balanced", "high": "careful",
                "xhigh": "very thorough", "max": "as hard as it can"}
# How often the live goal view re-reads its transcripts.
GOAL_VIEW_EVERY = 2
# How often the UI re-reads the goals.
STATE_EVERY = 1.0
# git run from the UI must never ask for anything: a prompt would take over the
# terminal the UI is drawing on, and look like a hang. It fails instead, saying why.
NO_PROMPT = dict(os.environ, GIT_TERMINAL_PROMPT="0",
                 GIT_SSH_COMMAND=os.environ.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes")
# How old a cached copy may be before the view showing it re-reads Asana behind it.
BOARDS_MAX_AGE = 300
BOARD_OPEN_MAX_AGE = 30
BOARD_SHOWN_MAX_AGE = 60

# --- pure helpers (unit-tested) ---------------------------------------------

def matches(text, query):
    """Every word of the query appears in the text, ignoring case."""
    text = (text or "").lower()
    return all(word in text for word in (query or "").lower().split())


# What each kind of wait asks of you, for when the run recorded no headline.
WAIT_ASKS = {
    "questions": "has questions for you",
}


def wait_summary(wait):
    """One line for what a goal is waiting on you for — and what that asks of you."""
    kind = wait.get("kind")
    if kind == "plan" and wait.get("split"):
        return ("split into parts ready for your review — c approves it, a says what to "
                "change; or complete “Review the split” in Asana")
    if kind == "plan":
        return ("plan ready for your review — c approves it, a says what to change; or "
                "complete “Review the plan” in Asana")
    questions = wait.get("questions") or []
    if questions:
        more = len(questions) - 1
        return "has questions for you: %s%s" % (questions[0].get("q", ""),
                                                " (+%d more)" % more if more else "")
    if wait.get("headline"):
        return "%s — ⏎ to read, a to reply" % wait["headline"]
    return WAIT_ASKS.get(kind, "waiting on a reply from you") + " · ⏎ to read"


def wait_lines(wait, width):
    """The whole of a wait, wrapped to the screen, as [(text, style)]."""
    width = max(20, width - 4)
    out = []

    def para(text, style, indent=""):
        for line in (text or "").splitlines() or [""]:
            for piece in textwrap.wrap(line, width - len(indent)) or [""]:
                out.append((indent + piece, style))

    if wait.get("kind") == "plan" and wait.get("split"):
        para("The split into parts is ready for your review", "bold")
        out.append(("", "normal"))
        para("You approve the split here, not how the work is built: the parts, their order, "
             "and, at a skim, each part's acceptance criteria. They are on the ticket in Asana, "
             "under Execution. After you approve, each part plans itself, and its plan comes to "
             "you on its own. To change the split, edit, add or delete those subtasks, or say "
             "what to change in a comment on “Review the split” or with a here. Then approve "
             "it: complete “Review the split”, or press c.", "normal")
        if wait.get("detail"):
            out.append(("", "normal"))
            para("The parts:", "normal")
            for line in wait["detail"].splitlines():
                para(line, "dim", "  ")
        return out
    if wait.get("kind") == "plan":
        para("The plan is ready for your review", "bold")
        out.append(("", "normal"))
        para("Nothing is built until you approve it. The plan is on the ticket in Asana, "
             "under Execution, with its technical plan attached to “Review the plan”. To change "
             "it, edit, add or delete those subtasks, or say what to change in a comment on "
             "“Review the plan” or with a here. Then approve it: complete “Review the plan”, "
             "or press c.", "normal")
        if wait.get("detail"):
            out.append(("", "normal"))
            para("The %s:" % ("parts" if wait.get("split") else "steps"), "normal")
            for line in wait["detail"].splitlines():
                para(line, "dim", "  ")
        return out
    for n, q in enumerate(wait.get("questions") or [], 1):
        para("%d. %s" % (n, q.get("q", "")), "bold")
        for line in st.options_lines(q, "   "):
            if line:
                para(line.strip(), "normal", line[:len(line) - len(line.lstrip())])
            else:
                out.append(("", "normal"))
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


def scroll_top(top, cur, body, count):
    """The first row shown: it stays put while the cursor is in view and moves
    only as far as needed to bring it back."""
    top = min(top, cur)
    if cur >= top + body:
        top = cur - body + 1
    return max(0, min(top, count - body))


_PR_LOOKED = {}
PR_LOOK_EVERY = 300


def settle_finished_prs(main_root, goals, now=None):
    """A finished goal whose runner no longer watches its PR, such as one that
    finished before goals watched them, learns in the background when its PR was
    merged or closed, so it leaves the list as a watched one does."""
    import threading
    now = now or time.time()
    for g in goals:
        if (g.get("status") != "done" or g.get("parent") or not g.get("pr_url") or g.get("alive")
                or g.get("phase") in ("merged", "closed", gl.MARKED)
                or now - _PR_LOOKED.get(g["id"], 0) < PR_LOOK_EVERY):
            continue
        _PR_LOOKED[g["id"]] = now

        def look(gid=g["id"], url=g["pr_url"]):
            try:
                out = subprocess.run(["gh", "pr", "view", url, "--json", "state", "--jq", ".state"],
                                     capture_output=True, text=True, timeout=30, cwd=main_root).stdout
            except (OSError, subprocess.SubprocessError):
                return
            phase = {"MERGED": "merged", "CLOSED": "closed"}.get(out.strip())
            if phase:
                gl.Goal(main_root, gid).update(phase=phase)
        threading.Thread(target=look, daemon=True).start()


def goal_status(g, wait=None):
    """(what a goal is doing, style) for its row on the Runs tab."""
    status = g.get("status")
    if wait and status in ("stopped", "failed") and not g.get("alive"):
        # Stopped while it waited on you: it says so first, or it looks like it still runs.
        return "%s — r carries it on · it still waits on you" % status, (
            "bad" if status == "failed" else "normal")
    if wait:
        return "⚑ " + wait_summary(wait), "warn"
    if status in gl.LIVE and not g.get("alive"):
        return "stopped unexpectedly — r carries on", "bad"
    limits = g.get("limits") or []
    use = (" · usage %d%%" % max(l["used"] for l in limits)) if limits else ""
    use += " · ≈ $%.2f" % g["cost"] if g.get("cost") else ""
    agents = g.get("agents_running")
    use = (" · %d sub-agent%s running" % (agents, "" if agents == 1 else "s") if agents else "") + use
    steps, met = g.get("plan"), g.get("criteria")
    use = (" · plan %d/%d" % (steps["done"], steps["total"]) if steps else "") + (
        " · criteria %d/%d" % (met["done"], met["total"]) if met else "") + use
    if status == "working" and g.get("phase") == "planning":
        return "analysing the ask · round %s%s" % (g.get("round") or 1, use), "ok"
    if status == "working":
        return "working · round %s%s" % (g.get("round") or 1, use), "ok"
    if status == "checking":
        return "%s · round %s%s" % (g.get("doing") or "checking the branch against the ask",
                                     g.get("round") or 1, use), "ok"
    if status == "parts":
        return "%s%s" % (g.get("doing") or "building its parts", use), "ok"
    if status == "queued":
        return "%s%s" % (g.get("doing") or "plan approved — waits to build", use), "normal"
    if status == "setting-up":
        return "setting up its branch%s" % ("" if g.get("parent") else " and PR"), "ok"
    if status == "paused":
        return g.get("doing") or "paused for the usage limit", "normal"
    if status == "done" and g.get("phase") == gl.MARKED:
        return "marked done by you", "dim"
    if status == "done" and g.get("parent"):
        return "done — merged into the goal's branch", "dim"
    if status == "review" and g.get("pr_error"):
        return "cannot read its PR on GitHub, so it sees no comments: %s · x then r restarts it" % (
            g["pr_error"][:100]), "bad"
    if status == "review":
        return "%s%s" % (gl.REVIEW_DOING, use), "ok"
    if status == "done" and g.get("phase") == "merged":
        return "merged", "dim"
    if status == "done" and g.get("phase") == "closed":
        return "its PR was closed without a merge", "dim"
    if status == "done":
        return "done — its PR is ready · r watches it for review comments and the merge", "normal"
    if status == "failed":
        return "failed — %s · r tries again" % (g.get("reason") or "?").splitlines()[0][:120], "bad"
    if status == "stopped":
        return "stopped — r carries on", "dim"
    return status or "new", "normal"


def goal_rows(goals, waits=None, hide_done=False):
    """The Runs tab's goals, waiting on you first: an ask that runs by itself,
    on its own branch, into one PR. A goal's parts follow it, indented."""
    waits = waits or {}
    rows = []
    for g in goals or []:
        if hide_done and g.get("parent") and g.get("status") == "done":
            continue
        gid = "goal:%s" % g["id"]
        wait = waits.get(gid)
        done = g.get("status") == "done" and (bool(g.get("parent")) or not g.get("pr_url")
                                              or g.get("phase") in ("merged", "closed", gl.MARKED))
        if hide_done and done and not wait:
            continue
        status, style = goal_status(g, wait)
        rows.append({"kind": "goal", "id": gid, "goal": g["id"], "style": style,
                     "group": g.get("parent") or g["id"],
                     "cols": ["part" if g.get("parent") else "goal",
                              "  └ %s" % g.get("part") if g.get("parent") else gl.title_of(g),
                              status],
                     "log": g.get("log"), "wait": wait, "pr_url": g.get("pr_url"),
                     "links": [u for u in (g.get("pr_url"),) if u],
                     "alive": g.get("alive"), "status": g.get("status"),
                     "finished": done or (g.get("status") in ("failed", "stopped")
                                          and not g.get("alive")),
                     "done": done})
    waiting = {r["group"] for r in rows if r.get("wait")}
    rows.sort(key=lambda r: r["group"] not in waiting)
    return rows


def goal_waits(goals):
    """What each goal is waiting on you for: its outstanding question or problem."""
    out = {}
    for g in goals or []:
        awaiting = g.get("awaiting")
        if awaiting and awaiting.get("asked_at"):
            out["goal:%s" % g["id"]] = dict(awaiting, key=g["id"])
    return out


def setup_rows(control, default_branch=None):
    """The Setup tab: the branch goals go into, and how they run."""
    base = control.get("base")
    return [
        {"kind": "setting", "id": "base", "style": "normal",
         "cols": ["Queue into", base or "the default branch%s"
                  % (" (%s)" % default_branch if default_branch else "")]},
        {"kind": "setting", "id": "done", "style": "normal",
         "cols": ["Done tasks", "hidden — boards and Runs leave them out"
                  if control.get("hide_done") else "shown"]},
        {"kind": "setting", "id": "threshold", "style": "normal",
         "cols": ["Usage limit", "%d%% — goals wind down and pause at this share of any Claude "
                  "limit, then carry on when it resets" % (control.get("usage_threshold")
                                                           or gl.DEFAULT_THRESHOLD)]},
    ] + [{"kind": "setting", "id": sid, "style": "normal",
          "cols": [label, "%s — %s" % (model_label(models_of(control).get(key) or default), what)]}
         for sid, label, key, default, what in MODEL_SETTINGS] + [
        {"kind": "setting", "id": "gate", "style": "normal",
         "cols": ["Plan approval", "%s — who approves a goal's plan before it is built"
                  % GATE_LABELS[gate_of(control)]]}]


def gate_of(control):
    gate = (control or {}).get("goal_gate")
    return gate if gate in GATE_LABELS else gl.DEFAULT_GATE


def models_of(control):
    return (control or {}).get("models") or {}


def model_label(value):
    return dict(MODELS).get(value, value)


def setting_choices(sid):
    """[(value, label, what it means)] for a Setup row picked from a list."""
    if sid == "gate":
        return [(g, label, "") for g, label in GATE_LABELS.items()]
    if sid.startswith("effort-"):
        return [(e, e, EFFORT_NOTES[e]) for e in EFFORTS]
    return [(m, label, MODEL_NOTES[label]) for m, label in MODELS]


def setting_value(sid, control):
    """What a Setup row picked from a list is set to now."""
    if sid == "gate":
        return gate_of(control)
    _, _, key, default, _ = next(m for m in MODEL_SETTINGS if m[0] == sid)
    return models_of(control).get(key) or default


def choice_rows(sid, control):
    """The choices for a Setup row, the current one marked."""
    current = setting_value(sid, control)
    return [{"kind": "choice", "id": value, "style": "bold" if value == current else "normal",
             "cols": [label, " · ".join(x for x in (note, "← now" if value == current else "") if x)]}
            for value, label, note in setting_choices(sid)]


PICKED = ("gate",) + tuple(m[0] for m in MODEL_SETTINGS)


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
    """Branches to queue into, filtered, after a row for starting a new one from
    the default branch."""
    rows = [{"kind": "new", "id": "+new", "style": "warn",
             "cols": ["+ New branch…", "from origin/%s, as it is on GitHub now"
                      % (default or "the default branch")]}]
    for b in branches or []:
        if not matches(b, query):
            continue
        picked = b == current or (current is None and b == default)
        rows.append({"kind": "branch", "id": b, "style": "bold" if picked else "normal",
                     "cols": [b, " · ".join(x for x in (
                         "default" if b == default else "",
                         "← queueing here" if picked else "") if x)]})
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


def board_list_rows(boards, query):
    return [{"kind": "board", "id": b["gid"], "name": b["name"], "style": "normal",
             "cols": [b["name"], ""]}
            for b in boards or [] if matches(b["name"], query)]


def board_rows(board_gid, sections, query, subtasks=None, hide_done=False):
    """A board as sections and their tasks. A section stays when its name or any of
    its tasks match the query; a task when it matches or its section does.
    `subtasks` holds the expanded tasks' subtasks (None while they load), shown
    indented under them. A milestone shows (◈). `hide_done` leaves out completed
    tasks, and sections with nothing else."""
    subtasks = subtasks or {}
    rows = []
    for section in sections or []:
        hit = matches(section["name"], query)
        tasks = [t for t in section.get("tasks") or []
                 if (hit or matches("%s %s" % (t.get("key") or "", t["name"]), query))
                 and not (hide_done and t.get("completed"))]
        if not tasks and (not hit or hide_done):
            continue
        open_count = sum(1 for t in tasks if t.get("kind") != "milestone" and not t.get("completed"))
        rows.append({"kind": "section", "id": section["gid"], "board": board_gid,
                     "cols": [section["name"], "%d open" % open_count], "style": "bold"})
        for t in tasks:
            count = t.get("subtasks") or 0
            open_ = t["gid"] in subtasks
            fold = ("%s %d subtask%s" % ("▾" if open_ else "▸", count, "" if count == 1 else "s")
                    if count else "")
            rows.append(task_row(board_gid, t, "  ", fold, subtasks=count))
            if not open_:
                continue
            if subtasks[t["gid"]] is None:
                rows.append({"kind": "loading", "id": "loading:%s" % t["gid"], "parent": t["gid"],
                             "cols": ["        loading subtasks…", ""], "style": "dim"})
                continue
            for sub in [x for x in subtasks[t["gid"]] if not (hide_done and x.get("completed"))]:
                rows.append(task_row(board_gid, sub, "      ", "", parent=t["gid"]))
    return rows


def task_row(board_gid, t, indent, fold, **extra):
    milestone = t.get("kind") == "milestone"
    mark = "◈" if milestone else " "
    state = "done" if t.get("completed") else ""
    key = t.get("key") or ""
    lead = "%s%s " % (indent, mark)
    return dict({"kind": "task", "id": t["gid"], "board": board_gid, "name": t["name"], "key": key,
                 "completed": t.get("completed"), "milestone": milestone,
                 "faint": (len(lead), len(key)) if key else None,
                 "cols": ["%s%s%s" % (lead, key + " " if key else "", t["name"]),
                          "  ·  ".join(x for x in (state, fold) if x)],
                 "style": "dim" if t.get("completed") else "normal"},
                **extra)


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
            4: "ctrl-d", 21: "ctrl-u", 1: "ctrl-a", 5: "ctrl-e", 11: "ctrl-k", 12: "ctrl-l",
            23: "ctrl-w"}
_CURSES = {"KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
           "KEY_NPAGE": "pgdn", "KEY_PPAGE": "pgup", "KEY_HOME": "home", "KEY_END": "end",
           "KEY_ENTER": "enter", "KEY_BACKSPACE": "backspace", "KEY_BTAB": "btab",
           "KEY_DC": "delete"}

# What each key does wherever lists are shown. Vi, emacs and the arrow keys all
# work; a number goes straight to its tab.
NAV = {
    "down": "down", "j": "down", "ctrl-n": "down",
    "up": "up", "k": "up", "ctrl-p": "up", "ctrl-k": "up",
    "pgdn": "pgdn", "alt-n": "pgdn",
    "pgup": "pgup", "alt-b": "pgup",
    "ctrl-d": "halfdown", "ctrl-u": "halfup",
    "home": "home", "g": "home",
    "end": "end", "G": "end",
    "right": "open", "l": "open", "ctrl-l": "open", "enter": "open",
    "left": "back", "h": "back", "esc": "back", "backspace": "back",
    "tab": "next", "btab": "next",
}
for _n in range(1, len(TABS) + 1):
    NAV[str(_n)] = NAV["alt-%d" % _n] = "tab"
MOVES = ("down", "up", "pgdn", "pgup", "halfdown", "halfup", "home", "end")
# What still moves through the list while typing a filter: the keys the line
# itself has no use for.
TYPING_MOVES = ("up", "down", "ctrl-n", "ctrl-p", "pgdn", "pgup", "alt-n")

# The help page: sections of (keys, what they do). Kept short — one key or key
# group a line — so it reads as a table.
HELP = [
    ("Moving around", [
        ("↑ ↓   j k   ^N ^P ^K", "move"),
        ("PgDn PgUp   alt-N alt-B", "a page"),
        ("^D ^U", "half a page"),
        ("Home End   g G", "top / end"),
        ("⏎   →   l ^L", "in: open a board, a goal's question or live view, a setting"),
        ("←   h   esc   ⌫", "out: clear the filter first, then leave the board"),
        ("1–3   alt-1–3", "go to a tab; its number again takes it back to its top"),
        ("tab   shift-tab", "cycle the tabs"),
        ("/", "filter the list (⏎ keeps it, esc clears it) · ↑↓ ^N ^P PgDn PgUp alt-N still move"),
        (":", "commands that have no key of their own"),
        ("?", "this page"),
        ("q", "quit — the goals keep working"),
    ]),
    ("Runs", [
        ("⏎", "on a ⚑ goal, read what it is waiting on · otherwise what it is doing now, live"),
        ("a", "answer a ⚑ goal in one line"),
        ("A", "answer it in $EDITOR"),
        ("c", "approve the plan (or the split) of a goal waiting on your review"),
        ("x", "stop a goal · on a finished one, remove it from the list"),
        ("r", "carry a stopped or failed goal on from where it left off"),
        ("o", "open its PR"),
        ("u", "what each agent took: time, tokens, cost"),
        ("d", "mark it done by hand — it stops, and stops watching its PR"),
    ]),
    ("Boards", [
        ("→ l ⏎", "on a task or milestone (◈) with subtasks (▸ 3 subtasks): show them"),
        ("← h", "hide them again (on a subtask or its task) · then: leave the board"),
        ("o", "open the task (or the board) in Asana"),
        ("R", "reload from Asana"),
        (": Run as a goal", "on a task or milestone: it runs by itself, on its own branch, "
                            "into one PR — it asks you only what it cannot decide"),
    ]),
    ("Setup", [
        ("⏎", "change the setting: pick from its list, type the usage limit, or show or "
              "hide done tasks"),
        ("n", "new branch (in the branch list), created on origin"),
    ]),
    ("Commands — : opens them, on the Runs tab for the selected goal", [
        ("goal", "Run HCI-8 as a goal on the branch Setup → Queue into names (Boards)"),
        ("discuss", "Discuss the goal X — talk it through with Claude, which reads its "
                    "journal and code, and writes only scratch files in a temp folder; a new tab in Ghostty"),
        ("undo", "Undo the goal X — close its PR, delete its branch; says what it will do and asks first"),
        ("clear", "Clear the done goals from the list, shown or not"),
        ("done", "Hide done tasks / Show done tasks — also Setup → Done tasks"),
    ]),
    ("Typing — filter, answers, branch names, commands", [
        ("^A ^E", "start / end of the line"),
        ("^B ^F   ← →", "back / forward a character"),
        ("alt-B alt-F", "back / forward a word"),
        ("^K ^U", "delete to the end / to the start"),
        ("^W", "delete the word before"),
        ("^D   ⌫", "delete forward / back"),
    ]),
]
HELP_KEYS_WIDTH = 25


def help_lines(width, tab):
    """The help page as [(keys, text, style)]: moving around, the tab you are on,
    the other tabs, typing. Long descriptions wrap under themselves."""
    sections = dict(HELP)
    order = ["Moving around", tab] + [n for n, _ in HELP if n not in ("Moving around", tab)]
    room = max(20, width - HELP_KEYS_WIDTH - 6)
    out = []
    for name in order:
        if name not in sections:
            continue
        if out:
            out.append(("", "", "normal"))
        out.append(("", name + ("   · this tab" if name == tab else ""), "bold"))
        for keys, text in sections[name]:
            pieces = textwrap.wrap(text, room) or [""]
            out.append((keys, pieces[0], "normal"))
            out += [("", piece, "normal") for piece in pieces[1:]]
    return out



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
    def __init__(self, main_root):
        self.main_root = main_root
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
        self.subtasks = {}
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
        self.goal_view, self.goal_lines = None, (0, [])
        self.tops = {}
        self.help = False
        self.help_scroll = 0
        self.page = 10
        self.question = None
        self.compose = None
        self.edit_request = None
        self.discuss_request = None
        self.creating = None
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
        """Re-read the settings and what the goals left on disk."""
        self.control = dm.read_control(self.main_root)
        self.goals = gl.list_goals(self.main_root)
        rates = gl.repo_rates(self.main_root) if self.goals else {}
        processes = gv.claude_processes() if any(g.get("alive") for g in self.goals) else {}
        settle_finished_prs(self.main_root, self.goals)
        for g in self.goals:
            g["agents_running"] = gv.running_count(g, processes=processes) if g.get("alive") else 0
            g["cost"] = gl.write_report(gl.Goal(self.main_root, g["id"]), rates, write=False)[1] \
                or g.get("cost")
            journal = gv.read_journal(gl.Goal(self.main_root, g["id"]).journal)
            g["plan"] = gv.plan(journal)
            g["criteria"] = gv.plan(journal, "acceptance criteria", anywhere=False)
        for g in self.goals:
            parts = [p for p in self.goals if p.get("parent") == g["id"]]
            if parts:
                g["cost"] = (g.get("cost") or 0) + sum(p.get("cost") or 0 for p in parts)
                g["agents_running"] = (g.get("agents_running") or 0) + sum(
                    p.get("agents_running") or 0 for p in parts)
        self.waits = goal_waits(self.goals)
        self.snapped_at = time.time()

    def refresh_state(self, now):
        """Keep what is shown current on a clock, never on a keypress: a held-down
        key must not wait on disk reads each time."""
        if now - getattr(self, "snapped_at", 0) >= STATE_EVERY:
            self.snapshot()

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
        for gid in [g for g, subs in self.subtasks.items() if subs is None]:
            done = self.loader.take("subtasks-%s" % gid)
            if done:
                if done[1]:
                    self.subtasks.pop(gid)
                    self.message = "could not read the subtasks: %s" % done[1]
                else:
                    self.subtasks[gid] = [{"gid": t["ref"], "name": t["name"], "key": t.get("key"),
                                           "completed": t.get("completed")} for t in done[0] or []
                                          if not st.made_by_goal(t)]
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
        elif TABS[self.tab] == "Boards":
            self.refresh_boards()
        elif TABS[self.tab] == "Setup":
            self.refresh_branches()

    def loading(self):
        """(busy, age) of what is on screen: whether a load is running for it, and
        how old the copy shown is."""
        if TABS[self.tab] == "Boards" and self.board:
            gid = self.board[0]
            return self.loader.busy("sections-%s" % gid), self.sections_at.get(gid)
        if TABS[self.tab] == "Boards":
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
            return goal_rows(self.goals, self.waits, bool(self.control.get("hide_done")))
        if name == "Boards" and self.board:
            return board_rows(self.board[0], self.sections.get(self.board[0]), query,
                              self.subtasks, bool(self.control.get("hide_done")))
        if name == "Boards":
            return board_list_rows(self.boards, query)
        if self.setup in PICKED:
            return choice_rows(self.setup, self.control)
        if self.setup == "base":
            return branch_rows(self.branches, self.default_branch, query, self.control.get("base"))
        return setup_rows(self.control, self.default_branch)

    def view_key(self):
        if TABS[self.tab] == "Boards" and self.board:
            return "board:%s" % self.board[0]
        if TABS[self.tab] == "Setup" and self.setup:
            return "Setup:%s" % self.setup
        return TABS[self.tab]

    def set_threshold(self, text):
        """The usage limit typed on the Setup tab: a whole percentage, 1 to 100."""
        try:
            value = int(text.strip().rstrip("%"))
        except ValueError:
            value = None
        if value is None or not 1 <= value <= 100:
            self.message = "the usage limit is a percentage from 1 to 100 — %r is not" % text
            return
        self.change_control(lambda c: c.update(usage_threshold=value))
        self.message = "usage limit: %d%% — goals use it from their next usage read" % value

    def set_base(self, name):
        base = None if name == self.default_branch else name
        self.change_control(lambda c: c.update(base=base))
        self.setup = None
        self.message = ("queueing into %s — goals started now branch off it and open their PR "
                        "into it; goals already started keep theirs"
                        % (name if base else "the default (%s)" % name))

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

    def answer(self, gid, text):
        """Hand an answer to the goal waiting on it. It goes in the goal's state,
        which the goal looks at every second."""
        wait = self.waits.get(gid) or {}
        if not wait.get("asked_at") or not wait.get("key"):
            self.message = "nothing is waiting on an answer there any more"
            return
        st.State(self.main_root, wait["key"]).write(
            st.ANSWER_FILE, {"asked_at": wait["asked_at"], "text": text, "at": time.time()})
        self.question = None
        self.message = "answered — the goal carries on"
        self.snapshot()

    def start_answer(self, row, editor=False):
        wait = (row or {}).get("wait")
        if not wait:
            self.message = "nothing is waiting on you there"
        elif editor:
            self.edit_request = row["id"]
        else:
            self.compose = {"kind": "answer", "gid": row["id"], "text": "", "line": LineEdit()}

    def new_goal(self, row):
        """Start a goal for a board's ticket, on the branch new work goes into."""
        existing = gl.find_goal(self.main_root, row["id"])
        if existing:
            self.message = "%s is already a goal — it is on the Runs tab" % gl.title_of(existing)
            return
        base = self.control.get("base")
        gid = gl.create(self.main_root, row["id"], row.get("key") or row["id"], row["name"],
                        url=gl.task_url(row["id"], row["board"]), base=base,
                        **gl.settings_from(self.control))
        gl.launch(self.main_root, gid)
        self.message = "goal started on %s — it is at the top of the Runs tab" % (
            base or self.default_branch or "the default branch")
        self.snapshot()

    def goal_key(self, key, row):
        """x stops a running goal, or takes a finished one off the list; r starts a
        stopped one again where it left off; o opens its PR; d marks it done by hand."""
        goal = gl.Goal(self.main_root, row["goal"])
        pid = goal.read().get("pid")
        if key == "x" and row.get("alive") and pid:
            def stop():
                try:
                    os.killpg(pid, signal.SIGTERM)
                except OSError:
                    dm.kill_pid(pid)
                self.message = "stopping the goal — its row says stopped when it has"
            self.ask("stop the goal \"%s\"? r carries it on later (y/n)" % row["cols"][1], stop)
        elif key == "x":
            self.ask("take the goal \"%s\" off the list? Its branch and PR stay (y/n)"
                     % row["cols"][1], lambda: (goal.update(cleared=True), self.snapshot()))
        elif key == "r" and row.get("alive"):
            self.message = "the goal is still running"
        elif key == "r" and row.get("done"):
            self.message = "the goal is done"
        elif key == "r":
            gl.launch(self.main_root, row["goal"])
            self.message = "the goal carries on from where it stopped"
            self.snapshot()
        elif key == "o" and row.get("pr_url"):
            webbrowser.open(row["pr_url"])
        elif key == "o":
            self.message = "no PR yet"
        elif key == "d" and row.get("done"):
            self.message = "the goal is done"
        elif key == "d" and goal.read().get("parent"):
            self.message = "a part is done when it is merged — mark its goal done instead"
        elif key == "d":
            def mark():
                gl.mark_done(self.main_root, row["goal"])
                self.message = "marked done — x takes it off the list"
                self.snapshot()
            self.ask("mark the goal \"%s\" done?%s Its branch, PR and ticket stay as they are (y/n)"
                     % (row["cols"][1], " It and its parts stop." if row.get("alive") else ""), mark)
        elif key == "u" and gl.write_report(goal, gl.repo_rates(self.main_root))[0]:
            self.log_path, self.log_scroll = goal.state.path(gl.REPORT_FILE), 0
        elif key == "u":
            self.message = "no call has finished yet"

    def clear_goals(self, goals):
        """Take done goals and their parts off the list. Their branches and PRs stay."""
        for g in goals:
            for one in gl.goal_and_parts(self.main_root, g["id"]):
                if one.read():
                    one.update(cleared=True)
        self.snapshot()
        self.message = "removed %d done goal%s from the list" % (len(goals), "" if len(goals) == 1 else "s")

    def palette_commands(self, row):
        """What the palette offers: only commands that are not already in plain
        sight — none with a key shown in the line at the bottom — and only ones
        that can run right now."""
        out = []
        if TABS[self.tab] == "Runs":
            done = [g for g in self.goals if not g.get("parent") and g.get("status") == "done"
                    and not g.get("awaiting")]
            if done:
                out.append({"title": "Clear %d done goal%s from the list"
                                     % (len(done), "" if len(done) == 1 else "s"),
                            "words": "remove merged finished acknowledge tidy clean goals",
                            "run": lambda: self.clear_goals(done)})
        if TABS[self.tab] == "Runs" and row and row["kind"] == "goal" and row["cols"][0] == "goal":
            out.append({"title": "Discuss the goal %s" % row["cols"][1],
                        "words": "talk chat brainstorm ask claude think through read only",
                        "run": lambda: setattr(self, "discuss_request", row["goal"])})
            out.append({"title": "Undo the goal %s" % row["cols"][1],
                        "words": "revert discard throw away back out cancel reset goal",
                        "run": lambda: self.undo_goal(row)})
        if (TABS[self.tab] == "Boards" and self.board and row and row["kind"] == "task"
                and not row.get("completed")):
            into = self.control.get("base") or self.default_branch or "the default branch"
            name = row.get("key") or (row["name"] if len(row["name"]) <= 40 else row["name"][:39] + "…")
            out.append({"title": "Run %s as a goal on %s" % (name, into),
                        "words": "goal autonomous run by itself agent swarm implement",
                        "run": lambda: self.new_goal(row)})
        hidden = bool(self.control.get("hide_done"))
        out.append({"title": "Show done tasks" if hidden else "Hide done tasks",
                    "words": "filter completed merged finished hide show toggle",
                    "run": self.toggle_done})
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

    def continue_key(self):
        """c: approve the plan (or the split) of the selected goal."""
        row = self.selected(self.view()) if TABS[self.tab] == "Runs" else None
        if row and row["kind"] == "goal" and (row.get("wait") or {}).get("kind") == "plan":
            split = (row.get("wait") or {}).get("split")
            self.ask(("approve the split of \"%s\", so its parts start to plan? (y/n)" if split else
                      "approve the plan of \"%s\", so it starts building? (y/n)") % row["cols"][1].strip(" └"),
                     lambda: self.answer(row["id"], "continue"))
        else:
            self.message = "no plan waits on your approval there"
    def toggle_done(self):
        hide = not self.control.get("hide_done")
        self.change_control(lambda c: c.update(hide_done=hide))
        self.message = "done tasks hidden" if hide else "done tasks shown"

    def undo_goal(self, row):
        """Ask before undoing a goal, saying all it will do; then undo it in a
        process of its own, so the TUI does not wait on GitHub and Asana."""
        steps = gl.undo_plan(self.main_root, row["goal"])

        def go():
            goal = gl.Goal(self.main_root, row["goal"])
            log = open(os.path.join(os.path.dirname(goal.state.dir), "%s-undo.log" % row["goal"]), "a")
            subprocess.Popen([sys.executable, os.path.join(os.path.dirname(HERE), "goal", "goal.py"), "undo", row["goal"],
                              "--repo", self.main_root], cwd=self.main_root, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            log.close()
            self.message = "undoing the goal — it leaves the list when it is done"
        self.ask("undo the goal \"%s\": %s? This cannot be undone (y/n)"
                 % (row["cols"][1], ", ".join(steps)), go)

    def act(self, key, row):
        name = TABS[self.tab]
        if name == "Runs" and row:
            if key in ("a", "A"):
                self.start_answer(row, editor=key == "A")
            elif key in ("x", "r", "o", "u", "d"):
                self.goal_key(key, row)
        elif name == "Boards" and key == "o" and row:
            if row["kind"] == "task":
                webbrowser.open(task_url(row["board"], row["id"]))
            elif row["kind"] == "board":
                webbrowser.open("https://app.asana.com/0/%s/list" % row["id"])
            elif self.board:
                webbrowser.open("https://app.asana.com/0/%s/list" % self.board[0])
        elif name == "Boards" and self.board and key == "R":
            self.refresh_board(self.board[0], max_age=-1)
        elif name == "Boards" and key == "R":
            self.refresh_boards(max_age=-1)
        elif name == "Setup" and self.setup == "base" and key == "n":
            self.compose = {"kind": "branch", "text": "", "line": LineEdit()}
        elif name == "Setup" and self.setup == "base" and key == "R":
            self.refresh_branches(max_age=-1)

    def open(self, row, key):
        """Go into the selected row: a board's tasks, a goal's question or live
        view — or, with enter only, pick a setting."""
        name = TABS[self.tab]
        if not row:
            return
        if name == "Boards" and not self.board:
            self.board = (row["id"], row["name"])
            self.subtasks = {}
            self.refresh_board(row["id"], BOARD_OPEN_MAX_AGE)
        elif name == "Boards" and row["kind"] == "task" and row.get("subtasks"):
            if row["id"] not in self.subtasks:
                self.subtasks[row["id"]] = None
                self.loader.start("subtasks-%s" % row["id"], row["id"],
                                  lambda: self.asana(["task", "subtasks", row["id"]]))
        elif name == "Runs":
            if row.get("wait"):
                self.question = row["id"]
            else:
                self.goal_view, self.goal_lines, self.log_scroll = row["goal"], (0, []), 0
        elif name == "Setup" and self.setup in PICKED and key == "enter":
            sid, value = self.setup, row["id"]
            self.setup = None
            if sid == "gate":
                self.change_control(lambda c: c.update(goal_gate=value))
                self.message = "plan approval: %s — for goals started from now on" % GATE_LABELS[value]
            else:
                _, label, mkey, _, _ = next(m for m in MODEL_SETTINGS if m[0] == sid)
                self.change_control(lambda c: c.setdefault("models", {}).update({mkey: value}))
                self.message = "%s: %s%s" % (label.lower(), model_label(value),
                                             " — from each goal's next check on"
                                             if mkey == "check_effort"
                                             else " — for goals started from now on")
        elif name == "Setup" and self.setup == "base" and key == "enter":
            if row["kind"] == "new":
                self.compose = {"kind": "branch", "text": "", "line": LineEdit()}
            else:
                self.set_base(row["id"])
        elif name == "Setup" and not self.setup:
            if row["id"] == "threshold":
                current = str(self.control.get("usage_threshold") or gl.DEFAULT_THRESHOLD)
                self.compose = {"kind": "threshold", "text": current, "line": LineEdit(current)}
            elif row["id"] == "done":
                self.toggle_done()
            elif row["id"] in PICKED:
                self.setup = row["id"]
                ids = [r["id"] for r in self.view()]
                current = setting_value(self.setup, self.control)
                self.cursor[self.view_key()] = ids.index(current) if current in ids else 0
            else:
                self.setup = row["id"]
                self.query[self.view_key()] = ""
                rows = self.view()
                current = self.control.get("base") or self.default_branch
                ids = [r["id"] for r in rows]
                self.cursor[self.view_key()] = ids.index(current) if current in ids else 0

    def back(self):
        """Out one level: a filter first, then the board you are in."""
        vk = self.view_key()
        if self.query.get(vk):
            self.query[vk] = ""
            self.cursor[vk] = 0
        elif TABS[self.tab] == "Boards" and self.board and self.fold_back():
            pass
        elif TABS[self.tab] == "Boards" and self.board:
            self.board = None
        elif TABS[self.tab] == "Setup" and self.setup:
            self.setup = None

    def fold_back(self):
        """Hide the subtasks the cursor is on or under, landing on their task.
        False when there is nothing to hide."""
        rows = self.view()
        row = self.selected(rows)
        gid = row and (row.get("parent") or (row["id"] if row["id"] in self.subtasks else None))
        if not gid:
            return False
        self.subtasks.pop(gid, None)
        vk = self.view_key()
        self.cursor[vk] = next((i for i, r in enumerate(self.view()) if r["id"] == gid), 0)
        return True

    def goto(self, tab):
        if tab == self.tab:
            self.board = None if TABS[tab] == "Boards" else self.board
            self.setup = None if TABS[tab] == "Setup" else self.setup
            self.query[self.view_key()] = ""
        self.tab = tab

    def ask(self, prompt, fn):
        self.confirm = (prompt, fn)

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
            action = NAV.get(key)
            if action in MOVES:
                step = {"down": 1, "up": -1, "pgdn": self.page, "pgup": -self.page,
                        "halfdown": self.page // 2, "halfup": -(self.page // 2),
                        "home": -10 ** 6, "end": 10 ** 6}[action]
                self.help_scroll = max(0, self.help_scroll + step)
            else:
                self.help = False
            return True
        if self.palette is not None:
            self.palette_key(key)
            return True
        if self.compose is not None:
            if key == "enter":
                text = self.compose["text"].strip()
                compose, self.compose = self.compose, None
                if compose.get("kind") == "threshold":
                    self.set_threshold(text)
                elif compose.get("kind") == "branch":
                    self.new_branch(text)
                elif text:
                    self.answer(compose["gid"], text)
                else:
                    self.message = "nothing sent"
            elif key == "esc":
                kind, self.compose = self.compose.get("kind"), None
                self.message = {"threshold": "usage limit unchanged",
                                "branch": "no branch created"}.get(kind, "nothing sent")
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
            elif key == "l" and row.get("log"):
                self.log_path, self.log_scroll = row["log"], 0
            elif key == "o" and row.get("links"):
                webbrowser.open(row["links"][-1])
            elif NAV.get(key) == "back" or key == "q":
                self.question = None
            return True
        if self.goal_view and not self.log_path:
            action = NAV.get(key)
            goal = gl.Goal(self.main_root, self.goal_view)
            if action in MOVES:
                lines = len(self.goal_lines[1])
                step = {"down": 1, "up": -1, "pgdn": self.page, "pgup": -self.page,
                        "halfdown": self.page // 2, "halfup": -(self.page // 2),
                        "home": -lines, "end": lines}[action]
                self.log_scroll = max(0, min(lines, self.log_scroll + step))
            elif key == "l":
                self.log_path, self.log_scroll = goal.log, 0
            elif key == "u" and gl.write_report(goal, gl.repo_rates(self.main_root))[0]:
                self.log_path, self.log_scroll = goal.state.path(gl.REPORT_FILE), 0
            elif key == "u":
                self.message = "no call has finished yet"
            elif action == "back" or key == "q":
                self.goal_view, self.log_scroll = None, 0
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
                self.log_path, self.log_scroll = None, 0
            return True
        if self.typing:
            if key == "enter":
                self.typing = False
            elif key == "esc":
                self.typing = False
                self.query[vk] = ""
            elif key in TYPING_MOVES:
                self.move(NAV[key], len(rows))
            elif self.line.key(key):
                self.query[vk] = self.line.text
                self.cursor[vk] = 0
            return True
        action = NAV.get(key)
        if key in ("q", "ctrl-c"):
            return False
        if key == "?":
            self.help = True
            self.help_scroll = 0
        elif key == "c":
            self.continue_key()
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
        if self.help:
            return "↑↓ alt-N alt-B scroll · any other key closes"
        if self.log_path:
            return "↑↓ alt-N alt-B scroll · g/G top/end · ←/esc/q back"
        if self.goal_view:
            return "live · ↑↓ scroll · l its log · u what each agent cost · ←/esc/q back"
        if self.typing:
            return "type to filter · enter keep · esc clear"
        if self.compose is not None:
            return {"branch": "enter create · esc cancel · ^U clear — any characters, / included",
                    "threshold": "type a percentage, 1 to 100 · enter set it · esc cancel"}.get(
                        self.compose.get("kind"), "enter send · esc cancel · ^U clear")
        if self.question:
            return "a answer · A answer in $EDITOR · l log · o open the PR · ←/esc back"
        return {
            "Runs": "⏎/→ question or live view · a answer · A $EDITOR · c approve the plan · "
                    "x stop (finished: remove) · r carry on · o PR · u cost · d done",
            "Boards": (": run as a goal · o open in Asana · ←/esc back · / filter · R reload"
                       if self.board else "⏎/→ open · o open in Asana · / filter · R reload"),
            "Setup": ("⏎ use it · n new branch · / search · ←/esc back" if self.setup == "base"
                      else "⏎ use it · / search · ←/esc back" if self.setup else "⏎ change it"),
        }[name] + " · : commands · 1-3 tabs · ? keys · q quit"

    def draw(self, scr, styles):
        scr.erase()
        h, w = scr.getmaxyx()
        put = lambda y, text, style="normal": _put(scr, y, text, w, styles[style])  # noqa: E731
        put(0, "conductor · %s · queueing into %s" % (
            os.path.basename(self.main_root),
            self.control.get("base") or self.default_branch or "the default branch"), "bold")
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
            lines = help_lines(w, TABS[self.tab])
            body = max(1, h - 5)
            self.help_scroll = min(self.help_scroll, max(0, len(lines) - body))
            for i, (keys, text, style) in enumerate(lines[self.help_scroll:self.help_scroll + body]):
                y = 3 + i
                if style == "bold":
                    _put_at(scr, y, 2, text, w, styles["bold"])
                    continue
                _put_at(scr, y, 4, keys, w, styles["ok"])
                _put_at(scr, y, 4 + HELP_KEYS_WIDTH, text, w, styles["normal"])
        elif asked and not self.log_path:
            wait = asked["wait"]
            put(2, "Runs › %s %s — waiting on you" % (asked["cols"][0], asked["cols"][1]), "dim")
            if wait.get("asked_at"):
                put(3, "asked %s · %s" % (wait["asked_at"][:16].replace("T", " "),
                                          wait.get("kind") or "questions"), "dim")
            for i, (line, style) in enumerate(wait_lines(wait, w)[:h - 8]):
                put(5 + i, "  " + line, style)
        elif self.goal_view and not self.log_path:
            at, lines = self.goal_lines
            if time.time() - at > GOAL_VIEW_EVERY:
                g = next((g for g in self.goals if g["id"] == self.goal_view), None) or {}
                goal = gl.Goal(self.main_root, self.goal_view)
                lines = gv.lines_for(g, gv.snapshot(g), gv.read_journal(goal.journal), w - 4)
                self.goal_lines = (time.time(), lines)
            title = next((gl.title_of(g) for g in self.goals if g["id"] == self.goal_view),
                         self.goal_view)
            put(2, "Runs › goal %s" % title, "dim")
            body = h - 6
            top = min(self.log_scroll, max(0, len(lines) - body))
            for i, (line, style) in enumerate(lines[top:top + body]):
                put(4 + i, "  " + line, style)
        elif self.log_path:
            lines = _tail(self.log_path, 2000)
            body = h - 4
            end = max(0, len(lines) - self.log_scroll)
            for i, line in enumerate(lines[max(0, end - body):end]):
                put(3 + i, *log_line(line))
        else:
            rows = (setup_rows(self.control, self.default_branch)
                    if TABS[self.tab] == "Setup" and self.setup in PICKED else self.view())
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
            top = scroll_top(self.tops.get(self.view_key(), 0), cur, body, len(rows))
            self.tops[self.view_key()] = top
            if not rows:
                put(3, "%s loading from Asana…" % spinner(time.time()) if busy else
                    {"Runs": "no goals — browse a board (tab 2), then : on a ticket runs it as a goal"}
                    .get(TABS[self.tab], "nothing here"),
                    "warn" if busy else "dim")
            for i, row in enumerate(rows[top:top + body]):
                picked = top + i == cur and not self.palette and not self.dialog_open()
                style = "sel" if picked else row.get("style", "normal")
                line = ("▸ " if picked else "  ") + fit(row["cols"], w - 2)
                put(3 + i, line, style)
                if row.get("faint"):
                    start, length = row["faint"]
                    _put_at(scr, 3 + i, 2 + start, line[2 + start:2 + start + length], w,
                            styles[style] | curses.A_DIM)
        put(h - 2, self.message, "warn")
        put(h - 1, self.help_line(), "dim")
        if self.palette is not None:
            self.draw_palette(scr, styles, h, w)
        else:
            self.draw_dialog(scr, styles, h, w)
        scr.refresh()

    def draw_palette(self, scr, styles, h, w):
        """A framed box: the line being typed on top, then the commands, the chosen
        one marked as well as highlighted — so one or two are never ambiguous."""
        shown = palette_matches(self.palette["commands"], self.palette["query"])
        rows = max(1, min(len(shown), h - 10))
        cur = min(self.palette["cursor"], max(0, len(shown) - 1))
        top = scroll_top(self.palette.get("top", 0), cur, rows, len(shown))
        self.palette["top"] = top
        items = [cmd["title"] for cmd in shown[top:top + rows]]
        if not shown:
            items = ["nothing here beyond the keys below" if not self.palette["commands"]
                     else "nothing matches"]
        draw_box(scr, styles, h, w, "commands", [": " + self.palette["line"].show(80)], items,
                 cur - top if shown else None)

    def dialog_open(self):
        return bool(self.confirm or self.compose is not None
                    or (TABS[self.tab] == "Setup" and self.setup in PICKED))

    def draw_dialog(self, scr, styles, h, w):
        """What waits on you right now, in the palette's box, so it is never missed
        on the bottom line: a yes/no question, a line to type, or a list to pick from.
        Returns whether one was drawn."""
        inner = max(26, min(w - 4, 86)) - 4
        if self.confirm:
            question = re.sub(r"\s*\(y/n\)\s*$", "", self.confirm[0])
            draw_box(scr, styles, h, w, "confirm", textwrap.wrap(question, inner) or [""], [],
                     footer="y yes · any other key no")
            return True
        if self.compose is not None:
            kind = self.compose.get("kind")
            title = {"branch": "new branch", "threshold": "usage limit"}.get(kind, "answer")
            note = {"branch": "created on origin from origin/%s" % (self.default_branch
                                                                    or "the default branch"),
                    "threshold": "a percentage of any Claude usage limit, 1 to 100"}.get(kind)
            header = ["› " + self.compose["line"].show(inner - 2)]
            draw_box(scr, styles, h, w, title, header, [note] if note else [],
                     footer=self.help_line().split(" · : commands")[0])
            return True
        if TABS[self.tab] == "Setup" and self.setup in PICKED:
            label = next((m[1] for m in MODEL_SETTINGS if m[0] == self.setup), "Plan approval")
            rows = choice_rows(self.setup, self.control)
            cur = min(self.cursor.get(self.view_key(), 0), max(0, len(rows) - 1))
            items = ["%-7s %s" % (r["cols"][0], r["cols"][1]) for r in rows]
            draw_box(scr, styles, h, w, label.lower(), [], items,
                     cur, footer="↑↓ choose · ⏎ use it · esc back")
            return True
        return False


def draw_box(scr, styles, h, w, title, header, items, picked=None, footer=None, top=3):
    """The overlay box the palette and every dialog share: a titled frame, header
    lines (what is typed, or the question), a rule, the items — `picked` marked as
    well as highlighted — and a footer of keys."""
    width = max(30, min(w - 4, 86))
    left = max(0, (w - width) // 2)
    inner = width - 4
    tint = styles.get("palette", styles["normal"])

    def row(y, text, attr, edge="│"):
        body = text[:inner].ljust(inner)
        _put_at(scr, y, left, edge, left + 2, tint)
        _put_at(scr, y, left + 1, " " + body + " ", left + width, attr)
        _put_at(scr, y, left + width - 1, edge, left + width + 1, tint)

    def rule(y, a, b, label=""):
        # The run of ─ goes through curses' own line character: the ncurses
        # macOS ships drops a long run of a multibyte one, leaving a hole the
        # screen behind shows through.
        _put_at(scr, y, left, a + label, left + width + 1, tint)
        try:
            scr.hline(y, left + 1 + len(label), getattr(curses, "ACS_HLINE", ord("-")) | tint,
                      max(0, width - 2 - len(label)))
        except curses.error:
            pass
        _put_at(scr, y, left + width - 1, b, left + width + 1, tint)

    rule(top, "╭", "╮", "─ %s " % title)
    y = top + 1
    for line in header:
        row(y, line, tint | curses.A_BOLD)
        y += 1
    if items:
        if header:
            rule(y, "├", "┤")
            y += 1
        for i, text in enumerate(items[:max(1, h - top - 6)]):
            row(y, ("▸ " if i == picked else "  ") + text if picked is not None else text,
                styles["sel"] if i == picked else tint)
            y += 1
    if footer:
        rule(y, "├", "┤")
        row(y + 1, footer, tint | curses.A_DIM)
        y += 2
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


def run_ui(main_root):
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
            curses.init_pair(4, curses.COLOR_CYAN, -1)
            styles["palette"] = curses.color_pair(4)
        app = App(main_root)
        while True:
            app.refresh_state(time.time())
            app.sync()
            app.draw(scr, styles)
            idle = 100 if app.loader.busy() else 1000
            scr.timeout(idle)
            key = read_key(scr, idle)
            if key is None:
                continue
            # Everything already typed is handled before the next draw, so keys
            # never queue up behind the screen.
            keys = [key]
            scr.timeout(0)
            while len(keys) < 256:
                more = read_key(scr, 0)
                if more is None:
                    break
                keys.append(more)
            try:
                for key in keys:
                    if not app.key(key, app.view() if not app.log_path else []):
                        return
                    if app.edit_request or app.discuss_request:
                        break
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
            if app.discuss_request:
                gid, app.discuss_request = app.discuss_request, None
                if discuss_in_tab(main_root, gid):
                    app.message = "the discussion is in a new tab — it writes only in a temp folder"
                else:
                    discuss(scr, main_root, gid)
                    app.message = "back from the discussion"
    curses.wrapper(loop)


GHOSTTY_TAB = """tell application "Ghostty"
  set cfg to new surface configuration
  set initial working directory of cfg to "%s"
  set initial input of cfg to "%s" & linefeed
  if (count of windows) > 0 then
    new tab in front window with configuration cfg
  else
    new window with configuration cfg
  end if
  activate
end tell"""


def applescript_text(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def discuss_command_line(main_root, gid):
    """The shell line that opens the discussion, for a tab of its own."""
    return " ".join(shlex.quote(a) for a in (os.path.join(os.path.dirname(HERE), "cond"), "goal",
                                             "discuss", gid, "--repo", main_root))


def discuss_in_tab(main_root, gid):
    """Open the discussion in a new tab of the terminal the TUI runs in, when that
    terminal can be told to: Ghostty, on macOS. False when it cannot."""
    if sys.platform != "darwin" or os.environ.get("TERM_PROGRAM") != "ghostty":
        return False
    script = GHOSTTY_TAB % (applescript_text(main_root),
                            applescript_text(discuss_command_line(main_root, gid)))
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def discuss(scr, main_root, gid):
    """Leave the screen to a Claude session about the goal, the way
    $EDITOR is opened, and come back when it ends."""
    argv, cwd = gl.discuss_command(main_root, gid)
    curses.def_prog_mode()
    curses.endwin()
    try:
        subprocess.call(argv, cwd=cwd)
    except OSError as e:
        sys.stderr.write("could not start claude: %s\n" % e)
        time.sleep(2)
    curses.reset_prog_mode()
    scr.clear()


def edit_answer(scr, template):
    """Open $VISUAL / $EDITOR on the template and return the answer written, the
    way `git commit` does."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    fd, path = tempfile.mkstemp(prefix="conductor-answer-", suffix=".md")
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
    goals = gl.list_goals(main_root)
    waits = goal_waits(goals)
    rows = goal_rows(goals, waits)
    if not rows:
        sys.stdout.write("no goals\n")
    if waits:
        sys.stdout.write("⚑ %d waiting on you — answer in `cond tui`, or on the ticket\n"
                         % len(waits))
    for row in rows:
        sys.stdout.write("\n  %-8s %s\n           %s\n" % tuple(row["cols"]))
        for text, _ in wait_lines(row.get("wait") or {}, 100) if row.get("wait") else []:
            sys.stdout.write("           %s\n" % text)
        for link in row.get("links") or []:
            sys.stdout.write("           %s\n" % link)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cond tui",
        description="Browse boards, start goals on tickets, and watch them work.")
    parser.add_argument("--repo", default=os.getcwd(), help="target repository (default: cwd)")
    parser.add_argument("--status", action="store_true", help="print the goals; no UI")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    try:
        main_root = st.main_repo_root(os.path.abspath(args.repo))
    except st.Failure as e:
        sys.stderr.write("tui: %s\n" % e)
        return 1
    try:
        if args.status:
            print_status(main_root)
            return 0
        run_ui(main_root)
        return 0
    except Stop as e:
        sys.stderr.write("\ntui: %s\n" % e)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
