#
# board.py — a goal's questions and plan on its Asana ticket, kept by the runner.
#
# Under the task that stands for the goal — the ticket, or a part's subtask — are
# three sections of subtasks, after any subtasks already there:
#
#   Questions  one subtask for each question only the person can answer
#   Review     "Review the plan": completing it approves the plan
#   Execution  the plan's steps, or the goal's parts, in order: the work
#
# The person answers a question in a comment on its subtask and completes it, and
# approves the plan by completing its review. Subtasks the goal made start with 🤖
# and carry st.GOAL_MADE in their description, so the queue and the boards leave
# them out.
# No agent reads or writes Asana: only the runner, through this file.

import os
import re
import tempfile
import time

import start_task as st

BOARD_FILE = "asana.json"
QUESTIONS, REVIEW, EXECUTION = "Questions", "Review", "Execution"
REVIEW_NAME = "Review the plan"
INTEGRATION = "Integration: the parts together"
APPROVED = "continue"
# How often Asana is read while the goal waits on the person there.
POLL = 60
_APPROVALS = {"", "c", "continue", "ok", "okay", "go", "go on", "yes", "y", "approve",
              "approved", "lgtm"}


# --- pure helpers (unit-tested) ----------------------------------------------

def approves(text):
    """Whether an answer to the plan's review only approves it, with nothing to change."""
    return re.sub(r"[\s.!]+$", "", (text or "").strip().lower()) in _APPROVALS


def title(text, width=200):
    """A subtask's name, from a line of the journal: one line, no checkbox."""
    line = re.sub(r"^\s*(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?", "", (text or "").splitlines()[0]
                  if (text or "").strip() else "")
    line = re.sub(r"\s+", " ", line).strip()
    return line if len(line) <= width else line[:width - 1].rstrip() + "…"


def step_key(text):
    """What a plan step is known by, from its first words, so that a note the lead
    adds after it, such as the file that did it, does not make it another step."""
    return " ".join(re.findall(r"[a-z0-9]+", title(text).lower()))[:60]


def same_step(a, b):
    """Whether two step keys are the one step: the lead may add a note after it."""
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def made(lines, how=None):
    """A description: what the subtask is, then, under a line, how to use it and
    who made it, apart so it is easy to skip."""
    lines = list(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    foot = ["_%s_" % how] if how else []
    return "\n".join(lines + ([""] if lines else []) + ["---"] + foot + ["_%s._" % st.GOAL_MADE])


QUESTION_TITLE = 70


def question_title(q):
    """A question's subtask name: the name the agent gave it, or the start of the
    question. The whole question is in the description."""
    text = title(q.get("title") or q["q"], width=10 ** 6)
    if len(text) <= QUESTION_TITLE:
        return text
    cut = text[:QUESTION_TITLE].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def question_body(q):
    lines = [q["q"], ""]
    if q.get("why"):
        lines += ["Why: " + q["why"], ""]
    return made(lines, "Answer in a comment on this subtask, then complete it. The goal goes "
                       "on when every question under Questions is complete. You can answer "
                       "on the cortex TUI instead.")


def review_body(split):
    what = "parts" if split else "steps"
    return made([], "Complete this subtask to approve the plan and start building. Until then "
                    "the goal waits. To change the plan first: edit, add or delete the %s under "
                    "Execution, or say what to change in a comment here. The goal reads them "
                    "once, when you complete this subtask." % what)


def part_body(part):
    lines = [part.get("brief") or "", ""]
    if part.get("plan_after"):
        lines.append("**Plans after:** %s" % ", ".join(part["plan_after"]))
    if part.get("after"):
        lines.append("**Builds after:** %s" % ", ".join(part["after"]))
    lines += ["", "**Acceptance criteria**", ""] + ["- %s" % c for c in part.get("criteria") or []]
    return made(lines)


def plan_changes(snapshot, rows, known):
    """What the person changed in the plan since it was written: lines for the
    lead. `snapshot` is {gid: {name, description, completed}} as written; `rows`
    the subtasks now; `known` the gids of the goal's other subtasks."""
    now = {r["ref"]: r for r in rows}
    out = []
    for gid, was in snapshot.items():
        row = now.get(gid)
        if not row:
            out.append("- Deleted: \"%s\"" % was["name"])
            continue
        if row.get("name") != was["name"]:
            out.append("- Renamed: \"%s\" is now \"%s\"" % (was["name"], row.get("name")))
        if (row.get("description") or "").strip() != (was.get("description") or "").strip():
            out.append("- Changed the description of \"%s\". It now says:\n\n%s\n"
                       % (row.get("name"), _quote(row.get("description"))))
        if row.get("completed") and not was.get("completed"):
            out.append("- Marked \"%s\" complete, before anything was built" % row.get("name"))
    for row in rows:
        if row["ref"] not in snapshot and row["ref"] not in known and not row.get("completed") \
                and not st.made_by_goal(row):
            text = (row.get("description") or "").strip()
            out.append("- Added: \"%s\"%s" % (row.get("name"), ", which says:\n\n%s\n" % _quote(text)
                                             if text else ""))
    return out


def _quote(text):
    return "\n".join("  > %s" % l for l in (text or "").strip().splitlines())


def answers_text(questions, said):
    """The person's answers, from the comments on each question's subtask:
    `said` is [[comment text]] in the questions' order."""
    lines = []
    for q, comments in zip(questions, said):
        lines += ["- %s" % q["q"], "  %s" % ("\n  ".join(comments) if comments else
                                             "(completed with no comment)")]
    return "\n".join(lines)


def comments_since(comments, since):
    """The texts of the comments a person made at or after `since` (an ISO time)."""
    return [c["text"].strip() for c in comments or []
            if (c.get("text") or "").strip() and not c["text"].startswith(st.BOT_MARK)
            and (c.get("created_at") or "") >= (since or "")]


# --- the board ---------------------------------------------------------------

class Board(object):
    """A goal's subtasks on Asana. Every call is best effort: when Asana fails, the
    goal carries on, and the TUI still shows and answers everything."""

    def __init__(self, main_root, state, task):
        self.main_root, self.state, self.task = main_root, state, task

    @property
    def on(self):
        return bool(self.task)

    def load(self):
        return self.state.read(BOARD_FILE, {}) or {}

    def save(self, data):
        self.state.write(BOARD_FILE, data)

    def asana(self, args, body=None):
        if body is None:
            return st.asana(args, cwd=self.main_root)
        fd, path = tempfile.mkstemp(suffix=".md")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(body)
            return st.asana(args + ["--body-file", path], cwd=self.main_root)
        finally:
            os.remove(path)

    def safely(self, what, fn, *args):
        if not self.on:
            return None
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 — Asana is never a reason to stop the goal
            st.warn("Asana: could not %s: %s" % (what, str(e).splitlines()[0][:200] if str(e) else e))
            return None

    def add(self, data, name, body, after=None, section=False):
        args = ["task", "add-subtask", self.task, "--title", st.GOAL_NAME + name]
        gid = str((self.asana(args + (["--section"] if section else []), body)
                   or {}).get("ref") or "")
        if not gid:
            raise st.Failure("Asana gave no id for the subtask \"%s\"" % name)
        data.setdefault("made", []).append(gid)
        self.save(data)
        if after:
            self.asana(["task", "set-parent", gid, self.task, "--after", after])
        return gid

    def sections(self, data):
        """The three sections, made once, in order, after the subtasks already there.
        Asana puts a new subtask at the top, so each is placed after the one before."""
        if data.get("section_execution"):
            return data
        rows = self.asana(["task", "subtasks", self.task]) or []
        after = rows[-1]["ref"] if rows else None
        for key, name in (("questions", QUESTIONS), ("review", REVIEW), ("execution", EXECUTION)):
            data["section_" + key] = self.add(data, name, "", after, section=True)
            after = data["section_" + key]
        return data

    def last_under(self, data, key):
        """The subtask the next one in a section goes after."""
        gids = {"questions": data.get("asked") or [], "review": [data.get("review")],
                "execution": [i["gid"] for i in data.get("items") or []]}[key]
        return ([g for g in gids if g] or [data["section_" + key]])[-1]

    # questions

    def ask(self, questions):
        """A subtask for each question, under Questions. Returns their ids."""
        return self.safely("add the questions", self._ask, questions) or []

    def _ask(self, questions):
        data = self.sections(self.load())
        gids = []
        for q in questions:
            gid = self.add(data, question_title(q), question_body(q), self.last_under(data, "questions"))
            data.setdefault("asked", []).append(gid)
            gids.append(gid)
        self.save(data)
        return gids

    def answers(self, questions, gids, since):
        """The answers, once every question's subtask is complete; None until then."""
        return self.safely("read the answers", self._answers, questions, gids, since)

    def _answers(self, questions, gids, since):
        said = []
        for gid in gids:
            task = self.asana(["task", "get", gid]) or {}
            if not task.get("completed"):
                return None
            said.append(comments_since(self.asana(["comment", "list", gid]), since))
        return answers_text(questions, said)

    def answered(self, gids, text):
        """An answer given on the TUI, onto each question's subtask, which it completes."""
        def post():
            for gid in gids:
                self.asana(["comment", "add", gid, text])
                self.asana(["task", "complete", gid])
        self.safely("write the answer", post)

    # the plan

    def publish(self, items, split, before_build=True):
        """The plan's review under Review, and the plan under Execution. `items` are
        [(key, name, body)]: the steps, or the parts. A subtask of the person's
        with the same name is used as it is. Before the build, a step the plan no
        longer has is deleted; after it, nothing is."""
        self.safely("write the plan", self._publish, items, split, before_build)

    def _publish(self, items, split, before_build):
        data = self.sections(self.load())
        if not data.get("review"):
            data["review"] = self.add(data, REVIEW_NAME, review_body(split), data["section_review"])
        old = {i["key"]: i for i in data.get("items") or []}
        theirs = {r["name"].strip().lower(): r["ref"]
                  for r in self.asana(["task", "subtasks", self.task]) or []
                  if r["ref"] not in data.get("made", []) and not st.made_by_goal(r)}
        out, after = [], data["section_execution"]
        for key, name, body in items:
            item = old.pop(key, None) or old.pop(next((k for k in old if same_step(k, key)), None), None)
            if not item and name.strip().lower() in theirs:
                item = {"key": key, "gid": theirs[name.strip().lower()], "made": False}
            if not item:
                item = {"key": key, "gid": self.add(data, name, body), "made": True}
            self.asana(["task", "set-parent", item["gid"], self.task, "--after", after])
            out.append(item)
            after = item["gid"]
        for item in old.values():
            if before_build and item.get("made") and not item.get("done"):
                self.asana(["task", "delete", item["gid"]])
                data["made"] = [g for g in data.get("made", []) if g != item["gid"]]
            elif not before_build:
                out.append(item)
        data["items"] = out
        data["published"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        rows = {r["ref"]: r for r in self.asana(["task", "subtasks", self.task]) or []}
        data["seen"] = sorted(rows)
        data["snapshot"] = {i["gid"]: {k: (rows.get(i["gid"]) or {}).get(k) for k in
                                       ("name", "description", "completed")} for i in out}
        self.save(data)

    def gid_of(self, key):
        return next((i["gid"] for i in self.load().get("items") or [] if i["key"] == key), None)

    def approval(self):
        """APPROVED, or with what the person commented on the review, once they
        completed it; None until then."""
        return self.safely("read the review", self._approval)

    def _approval(self):
        data = self.load()
        if not data.get("review"):
            return None
        if not (self.asana(["task", "get", data["review"]]) or {}).get("completed"):
            return None
        said = comments_since(self.asana(["comment", "list", data["review"]]), data.get("published"))
        return "\n\n".join(said) if said else APPROVED

    def approve(self):
        """The review completed, when the plan was approved elsewhere: on the TUI, or
        by the reviewer agent."""
        data = self.load()
        if data.get("review"):
            self.safely("complete the review", self.asana, ["task", "complete", data["review"]])

    def changes(self):
        """What the person changed in the plan before approving it: lines for the lead."""
        return self.safely("read the plan back", self._changes) or []

    def _changes(self):
        data = self.load()
        known = set(data.get("made", [])) | {data.get("review")} | set(data.get("asked") or []) \
            | set(data.get("seen") or [])
        rows = self.asana(["task", "subtasks", self.task]) or []
        return plan_changes(data.get("snapshot") or {}, rows, known)

    # progress

    def tick(self, done_keys):
        """Each step or part now done, completed in Asana."""
        data = self.load()
        todo = [i for i in data.get("items") or [] if not i.get("done")
                and any(same_step(i["key"], k) for k in done_keys)]
        if todo:
            self.safely("tick the plan", self._tick, data, todo)

    def _tick(self, data, todo):
        for item in todo:
            self.asana(["task", "complete", item["gid"]])
            item["done"] = True
        self.save(data)
