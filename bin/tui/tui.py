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
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daemon as dm  # noqa: E402
from engine import ASANA, Stop, describe, task_url  # noqa: E402
from daemon import st  # noqa: E402

TABS = ("Runs", "Boards", "Sprint", "Daemons")
PHASE_STYLE = {
    "running": "ok", "revising": "ok", "pr_open": "ok", "merged": "dim",
    "awaiting": "warn", "conflict": "warn", "failed": "bad", "stopped": "dim",
}


# --- pure helpers (unit-tested) ---------------------------------------------

def matches(text, query):
    """Every word of the query appears in the text, ignoring case."""
    text = (text or "").lower()
    return all(word in text for word in (query or "").lower().split())


def run_rows(control, data, live, me_gid=None):
    """The Runs tab: every queued task in queue order, then every live start-task
    run nothing here owns."""
    tasks, records = data.get("tasks") or {}, data.get("records") or {}
    me_gid = me_gid or (data.get("me") or {}).get("gid")
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
        rows.append({"kind": "task", "id": gid, "cols": [key or "", name or "", status],
                     "style": style, "log": record.get("log"),
                     "links": [u for u in (record.get("pr_url"),
                                           task_url(item.get("board"), gid)) if u]})
    managed = [r.get("pid") for r in records.values() if r.get("pid")]
    for tid, pid in dm.unmanaged(live, managed):
        rows.append({"kind": "orphan", "id": pid, "style": "warn", "links": [],
                     "cols": [tid, "start-task pid %d" % pid,
                              "not run by this repo's daemon — x stops it"]})
    return rows


def board_list_rows(boards, query, sprint=None):
    sprint_gid = (sprint or {}).get("gid")
    return [{"kind": "board", "id": b["gid"], "name": b["name"], "style":
             "bold" if b["gid"] == sprint_gid else "normal",
             "cols": [b["name"], "← sprint" if b["gid"] == sprint_gid else ""]}
            for b in boards or [] if matches(b["name"], query)]


def board_rows(board_gid, sections, queued, records, query):
    """A board as sections and their tasks. A section stays when its name or any of
    its tasks match the query; a task when it matches or its section does."""
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
        self.boards = None
        self.sections = {}
        self.workspace = None
        self.message = ""
        self.confirm = None
        self.log_path = None
        self.log_scroll = 0
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

    def load_boards(self):
        if self.boards is None:
            if self.workspace is None:
                me = self.asana(["user", "me"])
                self.workspace = ((me.get("workspaces") or [{}])[0]).get("gid")
            self.boards = sorted(self.asana(["project", "list", self.workspace]),
                                 key=lambda b: b["name"].lower())
        return self.boards

    def load_sections(self, gid, force=False):
        if force or gid not in self.sections:
            self.sections[gid] = self.asana(["project", "sections", gid])
        return self.sections[gid]

    def view(self):
        """(view name, rows) for what is on screen."""
        name = TABS[self.tab]
        query = self.query.get(self.view_key(), "")
        if name == "Runs":
            return run_rows(self.control, self.data, self.live)
        if name == "Boards" and self.board:
            queued = {q["gid"] for q in self.control["queue"]}
            return board_rows(self.board[0], self.sections.get(self.board[0]), queued,
                              self.data.get("records") or {}, query)
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
        added = self.change_control(lambda c: dm.queue_add(c, items))
        started = ""
        if added and not self.alive:
            self.ensure_daemon()
            started = " · " + self.message
        self.message = ("queued %d task(s)" % len(added) if added else "already queued") + (
            "" if self.control.get("sprint") else " — pick a sprint (tab 3) before they start"
        ) + started

    def command(self, op, gid):
        applied = self.data.get("applied", 0)
        self.change_control(lambda c: dm.add_command(c, op, gid, applied))

    def act(self, key, rows):
        row = self.selected(rows)
        name = TABS[self.tab]
        if name == "Runs" and row:
            if key == ord("x") and row["kind"] == "task":
                self.ask("stop and unqueue %s? (y/n)" % row["cols"][0], lambda: (
                    self.command("stop", row["id"]),
                    self.change_control(lambda c: dm.queue_remove(c, [row["id"]]))))
            elif key == ord("x") and row["kind"] == "orphan":
                self.ask("stop start-task pid %d? (y/n)" % row["id"],
                         lambda: dm.kill_pid(row["id"]))
            elif key == ord("r") and row["kind"] == "task":
                self.command("retry", row["id"])
                self.message = "retry asked — a failed or stopped task starts again when ready"
            elif key == ord("l") and row.get("log"):
                self.log_path, self.log_scroll = row["log"], 0
            elif key == ord("o") and row.get("links"):
                webbrowser.open(row["links"][0])
        elif name == "Boards":
            if self.board is None and row and key in (10, 13, curses.KEY_ENTER):
                self.board = (row["id"], row["name"])
                self.message = "loading %s…" % row["name"]
                self.load_sections(row["id"])
                self.message = ""
            elif self.board and key in (27, curses.KEY_BACKSPACE, 127, curses.KEY_LEFT):
                self.board = None
            elif self.board and key == ord("R"):
                self.load_sections(self.board[0], force=True)
            elif self.board and row and key == ord(" "):
                if row["kind"] == "section":
                    self.queue([{"gid": t["gid"], "board": row["board"], "name": t["name"],
                                 "completed": t.get("completed")} for t in row["tasks"]])
                else:
                    queued = {q["gid"] for q in self.control["queue"]}
                    if row["id"] in queued:
                        self.change_control(lambda c: dm.queue_remove(c, [row["id"]]))
                        self.message = "unqueued — a run already going is left to finish; " \
                                       "x on the Runs tab stops it"
                    else:
                        self.queue([{"gid": row["id"], "board": row["board"],
                                     "name": row["name"], "completed": row.get("completed")}])
        elif name == "Sprint" and row and key in (10, 13, curses.KEY_ENTER):
            sprint = {"gid": row["id"], "name": row["name"]}
            self.change_control(lambda c: c.update(sprint=sprint))
            self.message = "sprint: %s" % row["name"]
        elif name == "Daemons":
            if key == ord("s"):
                if self.alive:
                    self.message = "this repo's daemon is already running"
                else:
                    self.ensure_daemon()
            elif key == ord("x") and row and row["alive"]:
                self.ask("stop the daemon for %s and its runs? (y/n)" % row["cols"][0],
                         lambda: dm.stop_daemon(row["info"]))
            elif key == ord("d") and row and not row["alive"]:
                os.remove(row["id"])
                self.message = "cleared the crashed daemon's entry"

    def ask(self, prompt, fn):
        self.confirm = (prompt, fn)
        self.message = prompt

    def key(self, key, rows):
        """One keypress. Returns False to quit."""
        vk = self.view_key()
        if self.confirm:
            prompt, fn = self.confirm
            self.confirm = None
            self.message = ""
            if key == ord("y"):
                fn()
                self.snapshot()
            return True
        if self.log_path:
            if key in (ord("q"), 27):
                self.log_path = None
            elif key in (curses.KEY_UP, ord("k")):
                self.log_scroll += 1
            elif key in (curses.KEY_DOWN, ord("j")):
                self.log_scroll = max(0, self.log_scroll - 1)
            return True
        if self.typing:
            if key in (10, 13, 27, curses.KEY_ENTER):
                self.typing = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.query[vk] = self.query.get(vk, "")[:-1]
            elif 32 <= key < 127:
                self.query[vk] = self.query.get(vk, "") + chr(key)
            self.cursor[vk] = 0
            return True
        if key == ord("q"):
            return False
        if key in (9, curses.KEY_RIGHT) and not self.board:
            self.tab = (self.tab + 1) % len(TABS)
        elif ord("1") <= key <= ord(str(len(TABS))):
            self.tab = key - ord("1")
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor[vk] = min(self.cursor.get(vk, 0) + 1, max(0, len(rows) - 1))
        elif key in (curses.KEY_UP, ord("k")):
            self.cursor[vk] = max(0, self.cursor.get(vk, 0) - 1)
        elif key == curses.KEY_NPAGE:
            self.cursor[vk] = min(self.cursor.get(vk, 0) + 10, max(0, len(rows) - 1))
        elif key == curses.KEY_PPAGE:
            self.cursor[vk] = max(0, self.cursor.get(vk, 0) - 10)
        elif key == ord("/") and TABS[self.tab] in ("Boards", "Sprint"):
            self.typing = True
        else:
            self.act(key, rows)
        return True

    # drawing

    def help_line(self):
        name = TABS[self.tab]
        if self.log_path:
            return "↑/↓ scroll · q back"
        if self.typing:
            return "type to filter · enter done"
        return {
            "Runs": "x stop · r retry · l log · o open PR/task",
            "Boards": ("space queue/unqueue (on a section: all of it) · / filter · R reload · esc back"
                       if self.board else "enter open · / filter"),
            "Sprint": "enter use as sprint · / filter",
            "Daemons": "s start this repo's · x stop · d clear crashed",
        }[name] + " · 1-4 tabs · q quit (the daemon keeps running)"

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
        put(1, "  ".join(("[%d %s]" if i == self.tab else " %d %s ") % (i + 1, t)
                         for i, t in enumerate(TABS)), "normal")
        if self.log_path:
            lines = _tail(self.log_path, 2000)
            body = h - 4
            end = max(0, len(lines) - self.log_scroll)
            for i, line in enumerate(lines[max(0, end - body):end]):
                put(3 + i, line)
        else:
            if TABS[self.tab] in ("Boards", "Sprint") and self.boards is None:
                try:
                    self.load_boards()
                except Stop as e:
                    self.message = str(e)
            rows = self.view()
            title = self.board[1] if TABS[self.tab] == "Boards" and self.board else ""
            query = self.query.get(self.view_key(), "")
            put(2, "%s%s" % (title, ("  filter: %s%s" % (query, "▏" if self.typing else ""))
                             if query or self.typing else ""), "dim")
            body = h - 8
            cur = min(self.cursor.get(self.view_key(), 0), max(0, len(rows) - 1))
            top = max(0, cur - body + 1)
            if not rows:
                put(3, {"Runs": "nothing queued — browse a board (tab 2) and press space on a task",
                        "Daemons": "no daemon is running on this machine"}.get(TABS[self.tab], "nothing here"),
                    "dim")
            for i, row in enumerate(rows[top:top + body]):
                style = "sel" if top + i == cur else row.get("style", "normal")
                put(3 + i, fit(row["cols"], w), style)
            row = rows[cur] if rows else None
            detail = []
            if row and TABS[self.tab] == "Runs" and row["kind"] == "task":
                detail = [row["cols"][2]] + row.get("links", [])
                awaiting = st.State(self.main_root, row["cols"][0]).read("awaiting.json") \
                    if row["cols"][0] != "…" else None
                for q in (awaiting or {}).get("questions") or []:
                    detail.append("Q: %s" % q.get("q"))
                if (awaiting or {}).get("headline"):
                    detail.append(awaiting["headline"])
            for i, line in enumerate(detail[:4]):
                put(h - 6 + i, "  " + line, "dim")
        put(h - 2, self.message, "warn")
        put(h - 1, self.help_line(), "dim")
        scr.refresh()


def _put(scr, y, text, width, attr):
    try:
        scr.addnstr(y, 0, text, max(0, width - 1), attr)
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
            app.draw(scr, styles)
            key = scr.getch()
            if key == -1 or key == curses.KEY_RESIZE:
                continue
            try:
                if not app.key(key, app.view() if not app.log_path else []):
                    return
            except Stop as e:
                app.message = str(e)
    curses.wrapper(loop)


def print_status(main_root):
    control = dm.read_control(main_root)
    data = dm.read_json(os.path.join(dm.queue_dir(main_root), "state.json")) or {}
    info, alive = dm.daemon_info(main_root)
    sys.stdout.write("daemon:  %s%s\n" % (dm.daemon_health(info, alive, time.time()),
                                         " (pid %s)" % info.get("pid") if alive else ""))
    sys.stdout.write("sprint:  %s\n" % ((control.get("sprint") or {}).get("name") or "none"))
    rows = run_rows(control, data, dm.live_runs(main_root))
    if not rows:
        sys.stdout.write("\nnothing queued\n")
    for row in rows:
        sys.stdout.write("\n  %-8s %s\n           %s\n" % tuple(row["cols"]))
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
