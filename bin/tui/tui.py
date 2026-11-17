#!/usr/bin/env python3
#
# tui.py — the goals in the terminal, through the conductor service.
#
#   cond tui            # the goals, waiting ones first; ⏎ opens one
#   cond tui --status   # the goals, printed
#
# A client of `cond serve`, like the web page: it reads and changes nothing on disk
# itself. COND_URL (or COND_PORT) points it at another service.

import argparse
import curses
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import webbrowser

DEFAULT_URL = "http://127.0.0.1:%s" % (os.environ.get("COND_PORT") or 4747)
REFRESH = 2.0
LOG_TAIL = 200000
TONES = ("ok", "warn", "bad", "info")
LIST_KEYS = "⏎ open · a answer · c approve · x stop · r carry on · o PR · w web · f finished · q quit"
GOAL_KEYS = ("↑↓ step · ⏎ details · a answer · A in $EDITOR · c approve · x stop · r carry on · "
             "d done · L log · o PR · w web · ← back")
LOG_KEYS = "↑↓ PgUp PgDn scroll · G end, follows · ← back"


class Unreachable(Exception):
    pass


class Refused(Exception):
    pass


class Client(object):
    def __init__(self, url=None):
        self.url = (url or os.environ.get("COND_URL") or DEFAULT_URL).rstrip("/")

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read()).get("error")
            except (ValueError, AttributeError):
                message = None
            raise Refused(message or "HTTP %d" % e.code)
        except (urllib.error.URLError, OSError) as e:
            raise Unreachable("the service does not answer at %s (%s): start it with "
                              "`cond serve install`, or `cond serve`" % (self.url, getattr(e, "reason", e)))

    def goals(self):
        return self.call("GET", "/api/goals")

    def goal(self, repo, gid):
        return self.call("GET", "/api/repos/%s/goals/%s" % (q(repo), q(gid)))

    def log(self, repo, gid, start):
        return self.call("GET", "/api/repos/%s/goals/%s/log?from=%d" % (q(repo), q(gid), start))

    def act(self, repo, gid, action, body=None):
        return self.call("POST", "/api/repos/%s/goals/%s/%s" % (q(repo), q(gid), action), body or {})


def q(text):
    return urllib.request.quote(str(text), safe="")


# --- pure helpers (unit-tested) ----------------------------------------------

def money(cost):
    return "$%.2f" % cost if cost else ""


def span(seconds):
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm" % round(seconds / 60.0)
    return "%dh %dm" % (seconds // 3600, round((seconds % 3600) / 60.0))


def ago(t, now=None):
    if not t:
        return ""
    s = (now or time.time()) - t
    if s < 60:
        return "now"
    if s < 3600:
        return "%dm ago" % (s // 60)
    if s < 86400:
        return "%dh ago" % (s // 3600)
    return "%dd ago" % (s // 86400)


def state_of(g):
    st = g.get("state") or {}
    return st.get("text") or g.get("status") or "", st.get("tone") or "", st.get("label") or g.get("status") or ""


def ordered(goals, show_finished=True):
    """[(goal, is_part)]: waiting goals first, then running ones, then finished
    ones, newest first in each, each with all its parts after it. A finished goal
    shows while one of its parts is not finished."""
    tops = [g for g in goals if not g.get("parent")]
    rank = lambda g: 0 if g.get("waiting") else 1 if not g.get("finished") else 2  # noqa: E731
    tops.sort(key=lambda g: (rank(g), -(g.get("created") or 0)))
    out = []
    for g in tops:
        parts = [p for p in goals if p.get("parent") == g["id"]]
        if show_finished or not g.get("finished") or any(not p.get("finished") for p in parts):
            out += [(g, False)] + [(p, True) for p in parts]
    return out


def row_text(g, part, width, many_repos=False, now=None):
    """(left, right) of a goal's row: its label and title, then its facts."""
    text, _, label = state_of(g)
    title = ("  └ " + (g.get("part") or g.get("name") or "")) if part else (g.get("title") or g.get("name") or g["id"])
    if many_repos and not part:
        title += "  [%s]" % g.get("repo")
    facts = [x for x in ("%d agents" % g["agents_running"] if g.get("agents_running") else "",
                         "plan %d/%d" % (g["plan"]["done"], g["plan"]["total"]) if g.get("plan") else "",
                         "round %s" % g["round"] if g.get("round") else "", money(g.get("cost")),
                         ago(g.get("updated") or g.get("created"), now)) if x]
    left = "%-15s %s — %s" % (label[:15], title, text)
    return left, "  ".join(facts)


def status_lines(goals, now=None):
    """The goals, printed: one line each, waiting ones first, with its PR."""
    if not goals:
        return ["no goals"]
    many = len({g.get("repo") for g in goals}) > 1
    out = []
    for g, part in ordered(goals):
        left, right = row_text(g, part, 0, many, now)
        out.append(("⚑ " if g.get("waiting") else "  ") + left + ("  ·  " + right if right else "")
                   + ("  " + g["pr_url"] if g.get("pr_url") and not part else ""))
    return out


def wrap(text, width, indent=""):
    out = []
    for line in (text or "").splitlines() or [""]:
        out += [indent + piece for piece in textwrap.wrap(line, max(10, width - len(indent))) or [""]]
    return out


def wait_lines(awaiting, width):
    """What a goal waits on you for, as [(text, style)]."""
    out = []
    if not awaiting or not awaiting.get("asked_at"):
        return out
    kind = awaiting.get("kind")
    if kind == "plan":
        out.append(("The %s waits on your review" % ("split" if awaiting.get("split") else "plan"), "warn"))
        out += [(line, "normal") for line in wrap(awaiting.get("detail") or "", width, "  ")]
        out.append(("c approves · a or A asks for changes: the lead revises it and it comes back", "dim"))
        return out
    if kind == "problem":
        out.append(("Stopped: %s" % (awaiting.get("headline") or "a problem"), "warn"))
        out += [(line, "dim") for line in wrap((awaiting.get("detail") or "")[-1500:], width, "  ")]
        out.append(("a or A tells it what to do", "dim"))
        return out
    questions = awaiting.get("questions") or []
    out.append(("%d question%s for you" % (len(questions), "" if len(questions) == 1 else "s"), "warn"))
    for n, question in enumerate(questions, 1):
        out += [(line, "bold") for line in wrap("%d. %s" % (n, question.get("q", "")), width, "  ")]
        if question.get("why"):
            out += [(line, "dim") for line in wrap(question["why"], width, "     ")]
        for option in question.get("options") or []:
            label = option.get("label", "") + (" → " + option["means"] if option.get("means") else "")
            out += [(line, "normal") for line in wrap(label, width, "     ")]
            out += [(line, "dim") for line in wrap("\n".join(option.get("flow") or []), width, "        ")
                    if line.strip()]
        if question.get("recommend"):
            out += [(line, "ok") for line in wrap("Suggested: " + question["recommend"], width, "     ")]
    out.append(("a answers in a line · A in $EDITOR", "dim"))
    return out


def answer_template(title, awaiting):
    """What the editor opens with: what it waits on, as comments, above room for the answer."""
    lines = ["", "", "# Answer for %s" % title, "#"]
    lines += ["# " + text if text.strip() else "#" for text, _ in wait_lines(awaiting, 78)]
    lines += ["#", "# Lines starting with # are dropped. An empty answer sends nothing."]
    return "\n".join(lines) + "\n"


def parse_answer(text):
    kept = [line for line in (text or "").splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(kept).strip() or None


def clock(t):
    return time.strftime("%a %H:%M", time.localtime(t)) if t else ""


def goal_lines(g, width, opened=(), selected=None, now=None):
    """The goal's screen as [(text, style)], and the line each timeline card starts on."""
    out, starts = [], {}
    text, tone, label = state_of(g)
    out.append(("%s  [%s]" % (("Part: " + (g.get("part") or "")) if g.get("parent") else g.get("title") or g.get("name"),
                              label), "bold"))
    facts = [text] + [x for x in ("round %s" % g["round"] if g.get("round") else "", money(g.get("cost")),
                                  "plan %d/%d" % (g["plan"]["done"], g["plan"]["total"]) if g.get("plan") else "",
                                  "criteria %d/%d" % (g["criteria"]["done"], g["criteria"]["total"])
                                  if g.get("criteria") else "") if x]
    out += [(line, tone or "dim") for line in wrap(" · ".join(facts), width)]
    where = " · ".join(x for x in ("%s → %s" % (g["branch"], g.get("base") or "main") if g.get("branch") else "",
                                   g.get("pr_url") or "") if x)
    if where:
        out.append((where, "dim"))
    waiting = wait_lines(g.get("awaiting"), width - 2)
    if waiting:
        out.append(("", "normal"))
        out += [("  " + t, s) for t, s in waiting]
    live = g.get("live") or []
    if live:
        out.append(("", "normal"))
        out.append(("Running now", "bold"))
        for a in live:
            out.append(("%s%s  %s · %s%s" % ("    " if a.get("depth") else "  ", a.get("role"),
                                             (a.get("model") or "").replace("claude-", ""), span(a.get("seconds")),
                                             "  " + a["action"] if a.get("action") else ""), "dim" if a.get("depth") else "normal"))
    out.append(("", "normal"))
    phase = None
    for c in g.get("timeline") or []:
        if c["phase"] != phase:
            phase = c["phase"]
            out.append((phase.upper(), "dim"))
        starts[c["i"]] = len(out)
        until = c.get("until")
        dur = span(until - c["at"]) if until else ("now" if g.get("alive") else "")
        right = " · ".join(x for x in (money(c.get("cost")), dur, clock(c["at"])) if x)
        mark = "▾" if c["i"] in opened else "▸"
        head = "%s %s  %s" % (mark, c["title"], c.get("summary") or "")
        room = max(10, width - len(right) - 2)
        head = head if len(head) <= room else head[:room - 1] + "…"
        style = "sel" if c["i"] == selected else {"you": "warn", "alert": "bad", "ship": "ok"}.get(c["kind"], "normal")
        out.append(("%-*s  %s" % (room, head, right), style))
        if c["i"] in opened:
            said = [l for l in c.get("lines") or [] if not l.startswith(("lead: ", "review: calling", "check: calling"))]
            out += [(line, "normal") for line in wrap("\n".join(said), width, "    ") if line.strip()]
            for t in c.get("tasks") or []:
                out.append(("    %-8s %s  —  %s" % (t["kind"], t["name"], t["result"]),
                            "bad" if any(w in t["result"] for w in ("failed", "stopped", "cut off", "kept"))
                            else "dim"))
    if not g.get("timeline"):
        out.append(("Nothing has happened yet.", "dim"))
    return out, starts


# --- the app ------------------------------------------------------------------

class App(object):
    """The screens and what each key does, apart from curses: `lines()` says what to
    draw, `key()` handles one key, `ask` holds a question to confirm."""

    def __init__(self, client):
        self.client = client
        self.screen = "list"
        self.goals, self.cursor, self.show_finished = [], 0, False
        self.goal, self.where = None, None
        self.card, self.opened, self.follow = None, set(), True
        self.log_text, self.log_next, self.log_top, self.log_follow = "", -LOG_TAIL, 0, True
        self.message, self.error, self.ask = "", None, None
        self.loaded = 0
        self.want = None

    # data

    def load(self, force=False):
        if not force and time.time() - self.loaded < REFRESH:
            return
        self.loaded = time.time()
        try:
            self.goals = self.client.goals()
            if self.screen in ("goal", "log") and self.where:
                self.goal = self.client.goal(*self.where)
                cards = self.goal.get("timeline") or []
                if cards and (self.card is None or self.follow):
                    self.card = cards[-1]["i"]
            if self.screen == "log" and self.where:
                chunk = self.client.log(self.where[0], self.where[1], self.log_next)
                self.log_text += chunk.get("text") or ""
                self.log_next = chunk.get("next") or self.log_next
            self.error = None
        except Unreachable as e:
            self.error = str(e)
        except Refused as e:
            self.message = str(e)

    def rows(self):
        return ordered(self.goals, self.show_finished)

    def selected(self):
        rows = self.rows()
        if self.screen == "list":
            return rows[min(self.cursor, len(rows) - 1)][0] if rows else None
        return self.goal

    def open(self, g):
        self.screen, self.where = "goal", (g["repo"], g["id"])
        self.goal, self.card, self.opened, self.follow = None, None, set(), True
        self.load(force=True)

    # actions

    def act(self, action, body=None, done=""):
        g = self.selected()
        if not g:
            return
        try:
            self.client.act(g.get("repo") or (self.where or [None])[0], g["id"], action, body)
            self.message = done
        except (Refused, Unreachable) as e:
            self.message = str(e)
        self.load(force=True)

    def answer(self, text):
        if text:
            self.act("answer", {"text": text}, "sent — the goal carries on")

    def key(self, k):
        """Handle one key. Returns False to quit, or ("line", label) / ("editor", template)
        when the caller must read an answer."""
        self.message = ""
        if self.ask:
            confirm, self.ask = self.ask, None
            if k in ("y", "Y"):
                confirm[1]()
            return True
        g = self.selected()
        if k == "q":
            return False
        if self.screen == "log":
            return self.log_key(k)
        if k in ("KEY_LEFT", "h", "\x1b") and self.screen == "goal":
            self.screen, self.where, self.goal = "list", None, None
            return True
        if self.screen == "list" and self.list_key(k):
            return True
        if self.screen == "goal" and self.goal_key(k):
            return True
        waiting = (g or {}).get("awaiting") or {}
        if k == "a" and waiting.get("asked_at"):
            return ("line", "answer: ")
        if k == "A" and waiting.get("asked_at"):
            return ("editor", answer_template(g.get("title") or g["id"], waiting))
        if k in ("a", "A"):
            self.message = "nothing waits on you there"
        elif k == "c":
            if waiting.get("kind") == "plan":
                self.act("approve", done="approved — it builds now")
            else:
                self.message = "no plan waits on your approval there"
        elif k == "x" and g and g.get("alive"):
            self.ask = ("stop \"%s\"? r carries it on later (y/n)" % (g.get("title") or g["id"]),
                        lambda: self.act("stop", done="stopping"))
        elif k == "x":
            self.message = "it is not running"
        elif k == "r" and g:
            self.act("resume", done="it carries on")
        elif k == "d" and g:
            self.ask = ("mark \"%s\" done? It and its parts stop; its branch and PR stay (y/n)"
                        % (g.get("title") or g["id"]), lambda: self.act("done", done="marked done"))
        elif k == "o" and g:
            if g.get("pr_url"):
                webbrowser.open(g["pr_url"])
            else:
                self.message = "no PR yet"
        elif k == "w":
            url = self.client.url + "/" + ("#/g/%s/%s" % (q(g.get("repo") or self.where[0]), q(g["id"]))
                                           if g and self.screen != "list" else "")
            webbrowser.open(url)
        return True

    def list_key(self, k):
        rows = self.rows()
        if k in ("KEY_DOWN", "j"):
            self.cursor = min(self.cursor + 1, max(0, len(rows) - 1))
        elif k in ("KEY_UP", "k"):
            self.cursor = max(0, self.cursor - 1)
        elif k in ("KEY_HOME", "g"):
            self.cursor = 0
        elif k in ("KEY_END", "G"):
            self.cursor = max(0, len(rows) - 1)
        elif k in ("\n", "KEY_ENTER", "KEY_RIGHT", "l") and rows:
            self.open(rows[min(self.cursor, len(rows) - 1)][0])
        elif k == "f":
            self.show_finished = not self.show_finished
            self.message = "finished goals shown" if self.show_finished else "finished goals hidden"
        else:
            return False
        return True

    def goal_key(self, k):
        cards = [c["i"] for c in (self.goal or {}).get("timeline") or []]
        if k in ("KEY_DOWN", "j", "KEY_UP", "k") and cards:
            at = cards.index(self.card) if self.card in cards else len(cards) - 1
            at = min(at + 1, len(cards) - 1) if k in ("KEY_DOWN", "j") else max(at - 1, 0)
            self.card, self.follow = cards[at], at == len(cards) - 1
        elif k in ("KEY_HOME", "g") and cards:
            self.card, self.follow = cards[0], False
        elif k in ("KEY_END", "G") and cards:
            self.card, self.follow = cards[-1], True
        elif k in ("\n", "KEY_ENTER", " ", "KEY_RIGHT", "l") and self.card is not None:
            self.opened ^= {self.card}
        elif k == "L":
            self.screen, self.log_text, self.log_next, self.log_follow = "log", "", -LOG_TAIL, True
            self.load(force=True)
        else:
            return False
        return True

    def log_key(self, k):
        if k in ("KEY_LEFT", "h", "\x1b"):
            self.screen = "goal"
        elif k in ("KEY_DOWN", "j"):
            self.log_top += 1
        elif k in ("KEY_UP", "k"):
            self.log_top, self.log_follow = max(0, self.log_top - 1), False
        elif k == "KEY_NPAGE":
            self.log_top += 20
        elif k == "KEY_PPAGE":
            self.log_top, self.log_follow = max(0, self.log_top - 20), False
        elif k == "G":
            self.log_follow = True
        elif k == "g":
            self.log_top, self.log_follow = 0, False
        return True

    # drawing

    def lines(self, width, height):
        """(title, [(text, style)], the line to keep in view, keys)."""
        waiting = len([g for g in self.goals if g.get("waiting")])
        title = "conductor · %d goal%s%s" % (len([g for g in self.goals if not g.get("parent")]),
                                             "" if len(self.goals) == 1 else "s",
                                             " · ⚑ %d waiting on you" % waiting if waiting else "")
        if self.error:
            return title, [(line, "bad") for line in wrap(self.error, width)], 0, "q quit"
        if self.screen == "list":
            rows = self.rows()
            many = len({g.get("repo") for g in self.goals}) > 1
            out = []
            for n, (g, part) in enumerate(rows):
                left, right = row_text(g, part, width, many)
                room = max(10, width - len(right) - 2)
                left = left if len(left) <= room else left[:room - 1] + "…"
                tone = state_of(g)[1]
                out.append(("%-*s  %s" % (room, left, right), "sel" if n == self.cursor else tone or "normal"))
            if not out:
                out = [("No goals%s. Start one: the web page (w), `cond queue add`, or MCP."
                        % ("" if self.show_finished else " running; f shows the finished ones"), "dim")]
            return title, out, self.cursor, LIST_KEYS
        if not self.goal:
            return title, [("loading…", "dim")], 0, GOAL_KEYS
        if self.screen == "log":
            text = self.log_text.splitlines()
            if self.log_follow:
                self.log_top = max(0, len(text) - (height - 3))
            self.log_top = min(self.log_top, max(0, len(text) - 1))
            return title + " · log", [(line[:width], "normal") for line in text], -1, LOG_KEYS
        out, starts = goal_lines(self.goal, width, self.opened, self.card)
        return title, out, starts.get(self.card, 0), GOAL_KEYS


def draw(scr, app, styles):
    height, width = scr.getmaxyx()
    scr.erase()
    title, lines, keep, keys = app.lines(width - 1, height)
    body = height - 3
    if app.screen == "log" and not app.error:
        top = app.log_top
    else:
        top = getattr(app, "_top", 0)
        if keep < top:
            top = keep
        elif keep >= top + body - 2:
            top = keep - body + 3
        top = max(0, min(top, max(0, len(lines) - body)))
        app._top = top
    scr.addnstr(0, 0, title, width - 1, styles["bold"])
    for n, (text, style) in enumerate(lines[top:top + body]):
        attr = styles.get(style, curses.A_NORMAL)
        if style == "sel":
            scr.addnstr(n + 1, 0, text.ljust(width - 1), width - 1, attr)
        else:
            scr.addnstr(n + 1, 0, text, width - 1, attr)
    bottom = app.ask[0] if app.ask else app.message or keys
    scr.addnstr(height - 1, 0, bottom, width - 1, styles["warn"] if app.ask else styles["dim"])
    scr.refresh()


def read_line(scr, label):
    """A line typed at the bottom; None on Esc."""
    height, width = scr.getmaxyx()
    text = ""
    curses.curs_set(1)
    scr.timeout(-1)
    try:
        while True:
            shown = (label + text)[-(width - 2):]
            scr.move(height - 1, 0)
            scr.clrtoeol()
            scr.addnstr(height - 1, 0, shown, width - 1)
            scr.refresh()
            ch = scr.get_wch()
            if ch in ("\n", "\r", curses.KEY_ENTER):
                return text.strip() or None
            if ch == "\x1b":
                return None
            if ch in ("\x7f", "\b", curses.KEY_BACKSPACE):
                text = text[:-1]
            elif isinstance(ch, str) and ch.isprintable():
                text += ch
    finally:
        curses.curs_set(0)
        scr.timeout(250)


def edit(scr, template):
    """The answer written in $VISUAL / $EDITOR, or None."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(template)
        path = f.name
    curses.endwin()
    try:
        subprocess.call("%s %s" % (editor, path), shell=True)
        with open(path) as f:
            return parse_answer(f.read())
    finally:
        os.remove(path)
        scr.refresh()


def run(client):
    os.environ.setdefault("ESCDELAY", "25")

    def loop(scr):
        curses.curs_set(0)
        scr.timeout(250)
        styles = {"normal": curses.A_NORMAL, "bold": curses.A_BOLD, "dim": curses.A_DIM,
                  "sel": curses.A_REVERSE}
        styles.update({t: curses.A_BOLD for t in TONES})
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for n, (tone, color) in enumerate((("ok", curses.COLOR_GREEN), ("warn", curses.COLOR_YELLOW),
                                               ("bad", curses.COLOR_RED), ("info", curses.COLOR_CYAN)), 1):
                curses.init_pair(n, color, -1)
                styles[tone] = curses.color_pair(n) | (curses.A_BOLD if tone in ("warn", "bad") else 0)
        app = App(client)
        while True:
            app.load()
            draw(scr, app, styles)
            try:
                ch = scr.get_wch()
            except curses.error:
                continue
            k = curses.keyname(ch).decode() if isinstance(ch, int) else ch
            result = app.key(k)
            if result is False:
                return
            if isinstance(result, tuple):
                text = read_line(scr, result[1]) if result[0] == "line" else edit(scr, result[1])
                app.answer(text)
    curses.wrapper(loop)


def main(argv):
    parser = argparse.ArgumentParser(prog="cond tui", description=(
        "The goals in the terminal, through the conductor service."))
    parser.add_argument("--status", action="store_true", help="print the goals, then exit")
    parser.add_argument("--url", help="the service (default: %s, or COND_URL)" % DEFAULT_URL)
    args = parser.parse_args(argv)
    client = Client(args.url)
    if args.status:
        try:
            print("\n".join(status_lines(client.goals())))
        except (Unreachable, Refused) as e:
            sys.stderr.write("tui: %s\n" % e)
            return 1
        return 0
    try:
        run(client)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
