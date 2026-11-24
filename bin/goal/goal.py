#!/usr/bin/env python3
#
# goal.py — a prompt, implemented autonomously on one branch, into one PR.
#
# The ask is the person's prompt and the files they gave with it. Each Asana ticket
# the prompt links to is read once, when the goal starts, with its subtasks,
# comments and attachments; nothing is ever written to Asana. The person answers
# the goal's questions and approves its plan through conductor: its service, web
# page, TUI or `cond`. A lead agent gets the ask and nothing else. It first reads
# every reference the ask names and writes the acceptance criteria and the plan
# into its journal; the checker's model reviews those criteria against the
# references before anything is built. Then the lead builds, and keeps the journal
# so it can always pick the thread back up. This program is the harness around it.
# It calls the lead in rounds, hands the person's answers back when the lead has a
# question only they can answer, and pushes the branch only when the lead reports
# done, because every push runs CI. It waits for that CI, has an independent
# checker confirm "done" against the ask, and pauses while the Claude subscription
# is at or over its usage threshold. It never merges anything.
#
#   cond goal new "<prompt>" [-f FILE]... [--base BRANCH] [--start]   # prints the goal's id
#   cond goal run <id>                                                # run or resume it
#
# A goal's state is `.cortex/state/<id>/` — `goal.json`, the journal, its
# questions and answers, and the files it was given.

import argparse
import datetime
import fcntl
import glob
import hashlib
import html.parser
import json
import os
import re
import shlex
import shutil
import signal
import tempfile
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, LIB_DIR)
import core as st  # noqa: E402
import notes as nt  # noqa: E402
import repos  # noqa: E402
from agent.base import extract_last_json_block, usage_from  # noqa: E402
from agent.claude_cli import parse_envelope, unattended  # noqa: E402
from agent import opencode_cli as oc  # noqa: E402
from ci import (CI_NOT_STARTED, actions_refused, check_states, collect_feedback,  # noqa: E402
                    failed_runs, failure_excerpt, render_feedback)
sys.path.insert(0, HERE)

HOOK = os.path.join(HERE, "hook.py")

PROMPTS = os.path.join(HERE, "prompts")
GOAL_FILE = "goal.json"
GOAL_LOCK = "goal.lock"
RUN_LOCK = "run.lock"
_RUN_LOCK = []
JOURNAL_FILE = "journal.md"
LOG_FILE = "goal.log"
CALLS_FILE = "calls.json"
REPORT_FILE = "usage.txt"
INPUTS_DIR = "inputs"
PR_ASK_MAX = 3000
# A folder's README.md up to this size is shown in the ask; its other files never are.
FOLDER_README_MAX = 16 * 1024
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")

DEFAULT_MODEL = "claude-opus-5-5"
# The lead's sub-agents mostly do narrow, well-briefed parts of the work. The lead
# can still ask for a stronger model for one that needs it.
DEFAULT_SUBAGENT_MODEL = "claude-sonnet-5-5"
# The checker reviews the plan before the build and verifies the branch after it.
DEFAULT_CHECK_MODEL = "claude-opus-5-5"
DEFAULT_CHECK_EFFORT = "high"
DEFAULT_THRESHOLD = 75
# Goals made from now on run this flow: the plan is approved before it is built,
# and parts plan before the parts they build on are done. Older goals keep theirs.
FLOW = 2
# Who approves a plan: the person at every level ("wait"), the person for the
# goal and the reviewer for its parts ("top"), or the reviewer only ("auto").
GATES = ("wait", "top", "auto")
DEFAULT_GATE = "wait"
# Turns in one call before the runner takes the wheel back: to push, to read the
# usage, to see the lead is still getting somewhere. The session carries on.
MAX_TURNS = 200
# How often the usage is read while a call runs, and while one winds down.
USAGE_CHECK = 300
WIND_CHECK = 60
# At the threshold a call is asked to wind down: no new work, and an end at the next
# safe point. Only this many points past it is it cut off.
HARD_MARGIN = 2
WIND_FILE = "wind-down"
PARALLEL_TASKS = 6
# Tools that keep a call alive after its answer, waiting for a timer: a goal's call
# ends with its answer, and the runner starts the next.
NO_WAITING = "ScheduleWakeup,CronCreate,CronDelete,CronList,Monitor,RemoteTrigger"
# No MCP servers: each call would start every plugin's server (browsers, devices), and
# a goal's agents use none of them.
NO_MCP = ["--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}']
TASKS_FILE = "tasks.json"
TASK_CHECK = 15
DEP_DIRS = ("node_modules", ".venv")
SETTINGS_FILE = "settings.json"
WIND_DOWN = ("WIND DOWN: the person's Claude usage limit is reached, so this work pauses "
             "now. Start no new sub-agent and no new step. Finish the step you are on. If "
             "you lead the work: wait for the sub-agents already running, commit what is "
             "finished, write in the journal exactly where you stopped, and end your turn "
             "with the progress block. If you are a sub-agent: stop, and report what you "
             "finished and what you did not.")
# While paused, how often the usage is read again when no reset time is known.
PAUSE_CHECK = 900
# Rounds in a row that change nothing before the person is asked.
STALL_ROUNDS = 3
# Over this, the journal is compacted before the next session, by the sub-agent model.
JOURNAL_MAX = 40 * 1024
# After a compaction that failed, how much more it grows before one is tried again.
JOURNAL_REGROW = 20 * 1024
ARCHIVE_DIR = "journal-archive"
# Checks in a row that find gaps before the person is asked.
MAX_CHECKS = 4
# However much each fix changes, the person is asked after this many in a row.
MAX_FIX_ROUNDS = 10
ANSWER_CHECK = 2
# How often CI is read while its checks run, how long a PR may go without any
# check reporting before it counts as having no CI, and how long CI may take.
CI_CHECK = 60
CI_START = 600
CI_NUDGE = 120
CI_TIMEOUT = 2 * 3600
# Tries a cheap fixer gets at failing CI before the lead takes it on.
CI_FIXES = 2
# Each lockfile, the folder its install writes, and the repo's own install for it.
LOCKFILES = (("package-lock.json", "node_modules", "npm ci"),
             ("pnpm-lock.yaml", "node_modules", "pnpm install --frozen-lockfile"),
             ("yarn.lock", "node_modules", "yarn install --frozen-lockfile"),
             ("uv.lock", ".venv", "uv sync --frozen"))
INSTALL_TIMEOUT = 15 * 60
# A step that exits so did not find a program it runs: no change to the branch fixes it.
MISSING_TOOL = (126, 127)
# A step that checks a budget: only a change to the design brings the work under it.
BUDGET = re.compile(r"budget|size", re.I)
# A sound for each thing that needs the person, and how often a pause may sound.
SOUNDS = {"waiting": "Glass", "paused": "Basso"}
PAUSE_SOUND_EVERY = 600
NOTIFY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "notify", "notify.py")
ROLES = {"lead": "lead", "check": "checker", "ci-fix": "CI fixes", "review": "reviewer",
         "task": "coding tasks", "explore": "explorers", "compact": "journal compaction"}

# A large goal is split into parts, each a goal of its own on a branch off the
# goal's, merged back into it when done. A part does not split again.
PARTS_FILE = "parts.json"
MAX_DEPTH = 1
PARALLEL_PARTS = 2
PARTS_CHECK = 30
# How often a finished goal looks at its PR: for review comments, and the merge.
PR_CHECK = 60
MAX_PARTS = 8
PLANNING = ("This first round is the analysis: steps 1 to 4 of How to work. Do not "
            "change code yet. When the journal has the references, the acceptance criteria "
            "and the plan, end with the `planned` block.")
BUILDING = ("The analysis is finished: the journal has the references, the acceptance "
            "criteria and the plan. Build the work.")
SPLIT = """   Build the work yourself, as one goal, unless it is very large. In the build you
   do not code: you hand over tasks, and the runner runs them at the same time. So
   an API and the screens on it, or several screens, are one goal: your plan's
   steps and their tasks cover them. Each part costs its own lead, analysis, plan
   review and checker. Split only when the work is more than about 60 acceptance
   criteria AND falls into areas that can be built at the same time. Never split
   into a chain where each part waits for the one before: that only adds cost.
   Each part is built by its own lead, with its own tasks, journal and checker, on
   its own branch, and merged into yours. Write the parts to `{{parts_file}}` as
   JSON:

   ```json
   {"parts": [{"name": "Tasks API and data model", "after": [], "summary": "…", "brief": "…", "criteria": ["…"]}]}
   ```

   - `criteria`: the acceptance criteria the part must meet, copied word for word
     from your list. Each criterion goes to one part at most. Keep the criteria
     about how the parts fit together for yourself.
   - `after`: the names of the parts it builds on. They are merged into your
     branch before this part starts to build. Put the shared layers first, such
     as the data model and the API, and the parts that use them after. Parts with
     nothing between them run at the same time, so give them work that does not
     touch the same files.
   - `summary`: for the person, who reads it to approve the split: two to
     four short sentences in ASD-STE100 Simplified Technical English, about what
     the part builds and what changes for the users. No file paths, no code.
   - `brief`: about a dozen short lines, in Markdown, under these headings:
     `**Builds**` (what the part builds, and for whom), `**References**` (the
     references and their sections that cover it, such as the prototype's
     functions), `**Does not touch**`, and `**Meets other parts**` (only what
     another part depends on, when it is known now: an endpoint and its shape, a
     shared type, a function another part calls, a shared fact and its owner, and
     the steps of the technical plan's paths that this part builds; write each the
     same in every part that uses it). Leave the design inside the part to its lead: its
     tables and columns, its files and functions, its internal rules. The part's
     lead plans that from the references. A part's lead gets its brief, its
     criteria and the whole ask, and nothing else from you.
{{plan_after}}
   Two to %d parts is usual. For small work, do not split, and do not write the
   file. Once the person approves the split, the runner replaces each part's
   criteria in your journal with one line for the part, ticked when the part is
   merged: its own checker checks its criteria. When every part is merged into
   your branch, you integrate: write the tests of the paths that cross parts
   first, check that the parts fit together, build what no part covers, and tick
   your own criteria.""" % MAX_PARTS
NO_SPLIT = ("   This is one part of a larger goal. Do not split it: build it yourself, with "
            "sub-agents.")
PLAN_AFTER = """   - `plan_after`: usually left out. Every part plans as soon as the person
     approves the split, while the parts before it are still built. Name a part
     here only when this part cannot sensibly be planned until that one is built,
     such as when it builds on something whose shape only building it settles.
"""
TECHNICAL_FILE = "technical-plan.md"
TECHNICAL = """   Write the technical plan to `{{technical_plan}}`, for a technical person
   who reviews how the work will be built. The person reads it next to your plan.
   Write it in ASD-STE100 Simplified Technical English: short sentences,
   the active voice, one word for one meaning, and code names as they are in the
   code. Use tables for lists of things, and mermaid diagrams for structure and
   flow. In a diagram's labels and messages, never write `;` or `#`: mermaid reads
   `;` as the end of a line. Use commas. Use these numbered sections, and leave out a section that does not apply:

   1. Purpose and scope: what this work builds and what it does not, and a table
      of the references and where they are.
   2. Terms: the words that have one meaning in this work.
   3. Overview: the parts of the system the work touches, in a few lines and a
      mermaid flowchart.
   4. Where the code goes: a table of area, path, and what changes there.
   5. Data model: the new and changed tables, columns and enums, as a mermaid
      erDiagram and a table; a status as a mermaid stateDiagram.
   6. Behaviour: the diagrams and tables of step 3 of How to work, each with a
      short name (`P1`, `S1`) that the criteria and the tests use. In a sequence
      diagram, note on each step the fields it writes and what each person sees
      after it.
   7. Invariants: a table of each invariant, each way it can break, and what the
      design does about it.
   8. Existing code touched: a table of each existing field, rule, screen, route
      or job the work changes, removes or relies on; every place that reads or
      writes it; and what changes there.
   9. The API: a table of routes: method, path, what it does, its errors.
   10. The frontend: the screens, what each shows, and how the data moves.
   11. Configuration: new settings and variables.
   12. Tests: how the repository tests, in a few lines (from its testing guide,
       its conventions and its existing tests); the test map: each rule the work
       adds, changes or removes, and the one place its test lives, or "no test"
       and why; and the test of each diagram and table of section 6, with its
       entry point.
   13. Risks and open decisions: what could still change the plan.
   14. Out of scope.

   It is a plan, so it is shorter than a document of finished work. Decide what
   you can now, and say what you decide later, while you build. If you split the
   work, write only sections 1, 3 (the parts and how they meet), 6 for the paths
   that cross parts (each step names the part that builds it), 7, 8, 13, a table
   of the meeting points (each endpoint, shared type or event: which part provides
   it and which parts use it), and a table of the shared facts (each value or rule
   that two parts, or a part and the existing code, must agree on, such as where a
   number is read, how money is shown, or which call step a task opens: its owner
   and the one function that gives it). Each part's lead reads this plan and
   writes the rest for its part.
   Keep the technical plan in step with your journal: when the plan changes,
   change it too.
"""
PLAN_NOTE = """   The person reads your questions and your plan on the goal's page, and approves
   the plan there before anything is built. So write each step of the plan, and
   each part, as one line a person can follow. When a ticket's subtasks already
   break the work down, follow that breakdown: give each step or part the exact
   name of its subtask, and add, merge or split only where the work needs it, with
   the reason in the journal.
"""
TESTING = """   The repository's testing guide is %s. Read it in the analysis and list it
   under `## References`. Plan the tests by it, write them as it says, and give
   it to every sub-agent that writes or runs tests. Where it says to run more
   tests than step 9 allows, step 9 wins: many agents share this machine.
"""
NO_TESTING = """   The repository has no testing guide. Learn how it tests from its convention
   files and its existing tests (step 7), and write what you find in a few lines
   at the top of the test map, so every coding task follows the same rules.
"""
BUILD_NOW = ("The plan is approved. Build the work, as the plan says. The analysis is "
             "finished.")
FRESH = ("This is a new session. The earlier conversation is gone on purpose: carried "
         "into the build, it is sent again with every step and costs more than the work. "
         "Your journal, the technical plan and the branch hold everything that is true. "
         "Read the journal and the technical plan first.\n\n"
         "In the build you coordinate. You do not write or read the code, and you do not "
         "start sub-agents: the runner does. To get work done, end your reply with the "
         "`dispatch` block, a list of tasks. A coding task makes one change; a question "
         "asks an explorer one narrow thing about the code. The runner runs every task in "
         "the block at the same time, each coding task in its own worktree off the branch, "
         "merges their branches into yours, and calls you again, in a new session, with "
         "their reports. So put every task that does not wait on another in one block: the "
         "next step of the plan, and every later step that does not depend on it. Give two "
         "tasks that change the same file to two blocks, one after the other.\n\n"
         "A coding task gets work that is decided: it does not find causes or choose "
         "designs. When the cause of a problem is not known yet, first ask explorers for "
         "the facts, decide the fix yourself from their answers, and then hand over the "
         "coding task. When a gap or a review comment already says where and what is "
         "wrong, hand over the fix at once. Once a report gives you the facts, hand over "
         "the fix in the next block: never ask an explorer the same question again. "
         "Brief each task completely, because it knows only its brief: the step, what to "
         "change and where, the parts of the technical plan it needs, the steps of a diagram "
         "or the rows of a table it builds and the test that covers them, the prototype file "
         "and lines for a screen, the tests to write, and what done means. In the journal, "
         "tick the steps and criteria a batch meets, and update the Status: no build log, "
         "the runner keeps one. A decision goes under Decisions only when it departs from the "
         "references, fills a gap in them, or follows the person's answer; how it is built "
         "goes in the technical plan. You can "
         "run git, read Markdown documents, and edit your journal and the technical plan. "
         "You do not run tests, type checks or builds. Tests guide the coding tasks while "
         "they code: each runs the tests of its own change. When you report done, the runner "
         "merges the base in and runs the repo's CI static checks here (type checks, lint, "
         "format), and a fixer repairs what fails, before the checker and the push. So do "
         "not hand over tasks that only run checks or verify a merge: report done, and the "
         "runner finds what is broken. Never tell a task to run a whole-project check. To "
         "know whether a task's work is right, read its report, or hand over a reviewer task.")
NEXT_STEP = ("Hand over the next tasks: the first step of the plan not ticked, and with it "
             "every later step that does not depend on it. The session before this one handed "
             "over:\n\n%s")
RESUME_STEP = ("The session before this one stopped before it handed over its tasks. Find "
               "where the work is from the journal and `git log`, and hand over the next tasks "
               "with the `dispatch` block, or end with `done` when every step is ticked.")
NOTE_FIRST = ("You reported done, but the person sent a note since. Deal with it first, "
              "then report done again.")
REPLAN = ("Plan what the person's note adds, as in the analysis, and only that. What is "
          "built already is existing code. Change the technical plan's diagrams and tables "
          "in place, and add a line for the note to its `## Additions` section. Add the "
          "note's acceptance criteria under `### Added: <a name>`; edit and untick the "
          "criteria it makes wrong; list in the plan the built work it redoes. Ask your "
          "questions together. Then report `planned`. Nothing is built until the plan is "
          "reviewed and approved.")
CONTINUE = ("Continue the work. Read your journal if you need to remind yourself where "
            "you are, and end with the result block when you stop.")

# Goals this process started, so finished ones are reaped rather than left as
# zombies that still look alive.
_CHILDREN = []

LIVE = ("setting-up", "working", "checking", "waiting", "paused", "parts", "queued", "review")
FINISHED = ("done", "failed", "stopped")


# --- pure helpers (unit-tested) ----------------------------------------------

def goal_id(key, name):
    """A goal's id: its ticket's key, when it has one, and a few words of its name."""
    if not key:
        return "goal-%s" % st.slugify(name, max_words=5)
    return "goal-%s-%s" % (st.slugify(key, max_words=3), st.slugify(name, max_words=4))


ASANA_URL = re.compile(r"https?://app\.asana\.com/[^\s)>\]\"']+")
NAME_WIDTH = 70


def asana_urls(prompt):
    """The Asana links in a prompt, each once, in order."""
    out = []
    for url in ASANA_URL.findall(prompt or ""):
        url = url.rstrip(".,;:")
        if url not in out:
            out.append(url)
    return out


def prompt_name(prompt, width=NAME_WIDTH):
    """A goal's name from its prompt: the first line with words in it, links left
    out. None when the prompt is only links."""
    for line in (prompt or "").splitlines():
        line = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", line)).strip(" -*#>:")
        if re.search(r"[A-Za-z0-9]", line):
            return line if len(line) <= width else line[:width - 1].rstrip() + "…"
    return None


NAME_PROMPT = """Name this piece of software work for a list of goals and its pull request
title. Say what it adds or changes, in at most eight words, in sentence case. Leave
out ticket keys, quotes and a full stop. Reply with the name only.

%s"""
NAME_ASK_MAX = 6000


def model_name(ask, cwd, run=subprocess.run):
    """A name for the goal from its ask, by Haiku, or None when it gives none."""
    try:
        out = run(["claude", "-p", NAME_PROMPT % ask[:NAME_ASK_MAX], "--model", "haiku",
                   "--max-turns", "1"] + NO_MCP, cwd=cwd, stdin=subprocess.DEVNULL,
                  capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return prompt_name((out.stdout or "").strip().strip("\"'`").rstrip("."))


def files_lines(files):
    """Files for the ask, as Markdown lines: each path, with a small text file's
    text and an HTML prototype's text without its markup."""
    out = []
    for a in files:
        if ONE_PAGER.search(os.path.basename(a["path"])):
            out.append("- `%s`: a one-pager. It is not used, and it decides nothing." % a["path"])
            continue
        if a.get("folder") is not None:
            out.append("- `%s/`: a folder of %d files. Do not read its files into your own context: "
                       "have explorers read them and report what you need." % (a["path"], a["folder"]))
            if a.get("readme"):
                out += ["", "Its `README.md`:", "", "```", a["readme"].rstrip(), "```", ""]
            continue
        out.append("- `%s`%s" % (a["path"], " (an image)" if a.get("is_image") else ""))
        inline = a.get("inline")
        if inline and a["path"].lower().endswith((".html", ".htm")):
            out += ["", "Its text is below, without the markup, styles and scripts. The file "
                    "itself holds the prototype: read it for how each screen looks and "
                    "behaves."]
            inline = html_text(inline)
        if inline:
            out += ["", "```", inline.rstrip(), "```", ""]
    return out


def ask_from_prompt(prompt, files=(), tickets=()):
    """The ask, as the lead reads it: the person's prompt, the files they gave with
    it, and each ticket it links to (as `ask_from_ticket` writes it)."""
    out = ["# The ask", "", (prompt or "").strip(), ""]
    if files:
        out += ["## Files given with it", ""] + files_lines(files) + [""]
    text = "\n".join(out).rstrip() + "\n"
    for ticket in tickets:
        text += "\n" + ticket
    return text


def title_of(goal, width=70):
    """The goal's key, when it has one, and name, short enough for a row."""
    line = " ".join(x for x in ((goal or {}).get("key"), (goal or {}).get("name")) if x) or "goal"
    return line if len(line) <= width else line[:width - 1].rstrip() + "…"


ONE_PAGER = re.compile(r"one[-_ ]?pager|\bprd\b|product[-_ ]requirements", re.I)


def ask_from_ticket(task, url, subtasks=(), comments=(), attachments=()):
    """The ask, as the lead reads it: the ticket and everything hanging off it.
    `subtasks` are full tickets too; `attachments` are download entries with an
    absolute `path`."""
    out = ["# %s: %s" % (st.task_key(task), task.get("name") or ""), url, ""]
    if (task.get("description") or "").strip():
        out += [task["description"].strip(), ""]
    open_subtasks = [t for t in subtasks if not t.get("completed") and not st.made_by_goal(t)]
    if open_subtasks:
        out += ["## Subtasks", "", "All of them are part of the ask.", ""]
        for t in open_subtasks:
            out += ["### %s: %s" % (st.task_key(t), t.get("name") or ""), ""]
            if (t.get("description") or "").strip():
                out += [t["description"].strip(), ""]
    said = [c for c in comments
            if (c.get("text") or "").strip() and not st.is_marked(c["text"])]
    if said:
        out += ["## Comments", ""]
        out += ["- %s: %s" % (c.get("author") or "someone", c["text"].strip()) for c in said]
        out.append("")
    if attachments:
        out += ["## Attachments", ""] + files_lines(attachments) + [""]
    return "\n".join(out).rstrip() + "\n"


class _Text(html.parser.HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "header", "footer", "li", "tr", "br", "h1",
              "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "pre", "blockquote", "dt", "dd"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "template"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4") and not self.skip:
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li" and not self.skip:
            self.parts.append("- ")
        if tag in ("td", "th", "button", "span", "a") and not self.skip:
            self.parts.append(" | " if tag in ("td", "th") else " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "template"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(markup):
    """The readable text of an HTML page: no scripts, styles or markup, one block
    to a line."""
    parser = _Text()
    parser.feed(markup)
    lines = [re.sub(r"\s+", " ", l).strip() for l in "".join(parser.parts).splitlines()]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


_LIMIT_LINE = re.compile(r"^(?P<name>[^:\n]+):\s*(?P<used>\d+)%\s*used(?:\s*·\s*resets\s+(?P<resets>.+))?$")
_RESET = re.compile(r"^(?:(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+at\s+)?"
                    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>[ap]m)"
                    r"(?:\s*\((?P<zone>[^)]+)\))?")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_reset(text, now):
    """When a limit resets, as epoch seconds, from "Oct 27 at 3:30pm (Africa/Johannesburg)"
    or "3:30pm (…)". None when it cannot be read."""
    m = _RESET.match((text or "").strip())
    if not m:
        return None
    zone = None
    if m.group("zone"):
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(m.group("zone").strip())
        except Exception:
            zone = None
    current = datetime.datetime.fromtimestamp(now, zone)
    hour = int(m.group("hour")) % 12 + (12 if m.group("half") == "pm" else 0)
    try:
        reset = current.replace(hour=hour, minute=int(m.group("minute") or 0),
                                second=0, microsecond=0)
        if m.group("month"):
            reset = reset.replace(month=_MONTHS.index(m.group("month")) + 1,
                                  day=int(m.group("day")))
            if reset < current - datetime.timedelta(days=1):
                reset = reset.replace(year=reset.year + 1)
        elif reset <= current:
            reset += datetime.timedelta(days=1)
    except ValueError:
        return None
    return reset.timestamp()


def parse_usage(text, now):
    """The limits `/usage` reports: [{name, used, resets_at}]."""
    out = []
    for line in (text or "").splitlines():
        m = _LIMIT_LINE.match(line.strip())
        if m:
            out.append({"name": m.group("name").strip(), "used": int(m.group("used")),
                        "resets_at": parse_reset(m.group("resets"), now)})
    return out


def over_threshold(limits, threshold):
    """The limit at or over the threshold that frees up last — the one a pause has
    to outlast — or None."""
    over = [l for l in limits or [] if l["used"] >= threshold]
    if not over:
        return None
    return max(over, key=lambda l: l["resets_at"] or 0)


def lead_report(structured):
    """What the lead's result block says: ("progress" | "planned" | "dispatch" | "step" |
    "replan" | "done" | "question", block). A missing or unreadable block is progress — the lead
    stopped, not finished."""
    if not isinstance(structured, dict):
        return "progress", {}
    status = structured.get("status")
    if status == "question" and st.parse_agent_questions(structured):
        return "question", structured
    if status in ("done", "planned", "step", "replan"):
        return status, structured
    if status == "dispatch" and isinstance(structured.get("tasks"), list) and structured["tasks"]:
        return status, structured
    return "progress", structured


def check_verdict(structured):
    """The checker's verdict: (done, gaps, questions). None when it gave no verdict
    to read, which is no verdict at all, not a gap."""
    if not isinstance(structured, dict) or structured.get("verdict") not in ("done", "not_done"):
        return None
    gaps = [str(g) for g in structured.get("gaps") or [] if str(g).strip()]
    questions = st.parse_agent_questions(structured) or []
    return structured["verdict"] == "done" and not gaps and not questions, gaps, questions


def review_verdict(structured):
    """The criteria review: (gaps, questions), or None when it gave none to read."""
    if not isinstance(structured, dict) or "gaps" not in structured:
        return None
    gaps = [str(g) for g in structured.get("gaps") or [] if str(g).strip()]
    return gaps, st.parse_agent_questions(structured) or []


def checklist(text, heading):
    """The `- [ ]` / `- [x]` items under a journal's `## heading`, down to its next
    heading of the same level or higher: [(ticked, text)]. None when there is no
    such heading."""
    items, inside = [], False
    for line in (text or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            if inside and len(m.group(1)) <= 2:
                break
            if len(m.group(1)) == 2 and m.group(2).lower() == heading.lower():
                inside = True
            continue
        item = re.match(r"^\s*(?:[-*]|\d+\.)\s+\[([ xX])\]\s+(.*)$", line) if inside else None
        if item:
            items.append((item.group(1) != " ", item.group(2).strip()))
    return items if inside else None


def section_text(text, heading):
    """The lines under a journal's `## heading`, down to its next `##` heading."""
    out, inside = [], False
    for line in (text or "").splitlines():
        m = re.match(r"^(#{1,2})\s+(.*?)\s*$", line)
        if m:
            if inside:
                break
            inside = m.group(2).lower() == heading.lower()
            continue
        if inside and line.strip():
            out.append(line)
    return out


def small_reason(block, part, split):
    """Why the lead says the work needs no plan review, or None. A part or a split
    goal is always reviewed."""
    small = (block or {}).get("small")
    if part or split or not isinstance(small, str) or not small.strip():
        return None
    return small.strip()


def plan_problems(journal):
    """What the journal still lacks after the analysis: [] when it has references,
    acceptance criteria and a plan."""
    problems = []
    if not section_text(journal, "References"):
        problems.append("a `## References` section that lists every reference the ask names that is used")
    if not checklist(journal, "Acceptance criteria"):
        problems.append("a `## Acceptance criteria` checklist")
    if not checklist(journal, "Plan"):
        problems.append("a `## Plan` checklist")
    return problems


def unmet_criteria(journal):
    """The acceptance criteria not ticked yet."""
    return [text for ticked, text in checklist(journal, "Acceptance criteria") or [] if not ticked]


def planning_prompt(problems):
    return ("You reported the analysis finished, but your journal does not have:\n\n%s\n\n"
            "Write them, then report planned again." % "\n".join("- %s" % p for p in problems))


def unmet_prompt(unmet):
    return ("You reported done, but these acceptance criteria in your journal are not "
            "ticked:\n\n%s\n\nBuild them, and tick each one with the file that meets it. "
            "If one should not be built, ask the person: only they can drop a criterion. "
            "Then report done again." % "\n".join("- %s" % c for c in unmet))


def review_prompt(gaps, answers, again=False):
    """What the lead hears after the criteria review: what to change in the
    criteria, and the person's answers. Then it builds, or with `again`, corrects
    its criteria and its parts before they start."""
    parts = []
    if gaps:
        parts += ["Before you build, a reviewer compared your acceptance criteria and your "
                  "technical plan with the references the ask names, and found these "
                  "problems:", ""]
        parts += ["- %s" % g for g in gaps] + [""]
        parts += ["Check each one against the references. Correct the criteria, the "
                  "technical plan and the tests they name where it is right. Where it is "
                  "wrong, write why in the journal. The prototype wins, "
                  "unless the ask says explicitly that it replaces the prototype, or the "
                  "person's answers say otherwise. One-pagers decide nothing.", ""]
    if answers:
        parts += [answers, ""]
    if again:
        parts += ["Correct the criteria, the plan and the parts first: everything is "
                  "built from them. Then report planned again."]
    else:
        parts += ["Then build the work, as the plan says. The analysis is finished.", "", CONTINUE]
    return "\n".join(parts)


def read_parts(text):
    """The parts a lead wrote, from the JSON of its parts file: [{name, after,
    brief, criteria}], or None when it is not that."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    parts = data.get("parts") if isinstance(data, dict) else None
    if not isinstance(parts, list):
        return None
    out = []
    for p in parts:
        if not isinstance(p, dict):
            return None
        out.append({"name": str(p.get("name") or "").strip(),
                    "after": [str(a).strip() for a in p.get("after") or []],
                    "plan_after": [str(a).strip() for a in p.get("plan_after") or []],
                    "summary": str(p.get("summary") or "").strip(),
                    "brief": str(p.get("brief") or "").strip(),
                    "criteria": [str(c).strip() for c in p.get("criteria") or [] if str(c).strip()]})
    return out


def parts_problems(parts, criteria):
    """What is wrong with a split: [] when every part has a name, a brief and
    criteria from the lead's list, builds only on parts before it in a way that
    can finish, and no criterion is in two parts."""
    if parts is None:
        return ["the parts file is not JSON of the form {\"parts\": [...]}"]
    problems, names, seen = [], [p["name"] for p in parts], {}
    known = {re.sub(r"\s+", " ", c).strip() for _, c in criteria or []}
    if len(parts) < 2:
        problems.append("a split needs two parts or more; for one, do not write the file")
    if len(parts) > MAX_PARTS:
        problems.append("%d parts is too many: %d at most" % (len(parts), MAX_PARTS))
    if len(set(names)) != len(names) or not all(names):
        problems.append("every part needs a name of its own")
    for p in parts:
        if not p["brief"]:
            problems.append("part \"%s\" has no brief" % p["name"])
        if not p["criteria"]:
            problems.append("part \"%s\" has no criteria" % p["name"])
        for a in p["after"] + p.get("plan_after", []):
            if a not in names:
                problems.append("part \"%s\" is after \"%s\", which is not a part" % (p["name"], a))
        for c in p["criteria"]:
            if re.sub(r"\s+", " ", c) not in known:
                problems.append("part \"%s\" has a criterion that is not in your list: %s"
                                % (p["name"], c[:120]))
            if c in seen:
                problems.append("\"%s\" is in both \"%s\" and \"%s\"" % (c[:80], seen[c], p["name"]))
            seen[c] = p["name"]
    if not problems and part_order(parts) is None:
        problems.append("the parts' `after` lists go round in a circle")
    return problems


def part_order(parts):
    """The part names in an order where each comes after what it builds on; None
    when that cannot be."""
    left, out = {p["name"]: set(p["after"]) | set(p.get("plan_after") or []) for p in parts}, []
    while left:
        ready = [n for n, after in left.items() if after <= set(out)]
        if not ready:
            return None
        for n in sorted(ready, key=[p["name"] for p in parts].index):
            out.append(n)
            del left[n]
    return out


def part_ask(parent, part, built, technical_plan=None):
    """A part's ask: its brief and criteria, the goal's technical plan, what was
    built before it, and the whole goal's ask for context."""
    out = ["# %s part: %s" % (parent.get("key") or "", part["name"]), "",
           "This is one part of a larger goal. The goal's lead split the work into parts, "
           "and this part is yours. Other leads build the other parts: build only this one, "
           "and follow the contracts in its brief.", "", "## This part", "", part["brief"], "",
           "## Its acceptance criteria", ""]
    out += ["- %s" % c for c in part["criteria"]] + [""]
    if technical_plan:
        out += ["## The goal's technical plan", "", "`%s`. Read it in your analysis: the "
                "paths that cross parts and the steps this part builds, the invariants, the "
                "existing code the work touches, the meeting points and the shared facts. Your "
                "own plan follows them; where it cannot, ask." % technical_plan, ""]
    if built:
        out += ["## Built before it", "", "These parts are done, and their work is on your "
                "branch already:", ""]
        out += ["- %s: %s" % (b["name"], b.get("summary") or "done") for b in built] + [""]
    out += ["## The whole goal's ask, for context", "", parent.get("ask") or ""]
    return "\n".join(out).rstrip() + "\n"


PART_LINE = re.compile(r"^(\s*[-*]\s+\[)([ xX])(\]\s+Part “(.*?)” meets its)")


def fold_part_criteria(journal, parts):
    """The journal with each part's criteria replaced by one line for the part,
    under `### Parts` in `## Acceptance criteria`. Each part has its `name`,
    `criteria` and `journal`. A `###` section whose criteria all went goes too."""
    owned = {re.sub(r"\s+", " ", c).strip() for p in parts for c in p["criteria"]}
    lines = (journal or "").splitlines()
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^##\s+acceptance criteria\s*$", line, re.I)), None)
    if start is None:
        return journal
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s", lines[i])),
               len(lines))

    def item(line):
        m = re.match(r"^\s*(?:[-*]|\d+\.)\s+\[[ xX]\]\s+(.*)$", line)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else None

    chunks = [[]]
    for line in lines[start + 1:end]:
        if re.match(r"^###\s", line):
            chunks.append([])
        chunks[-1].append(line)
    body = []
    for n, chunk in enumerate(chunks):
        items = [item(line) for line in chunk if item(line) is not None]
        gone = items and all(i in owned for i in items)
        if gone and n:
            continue
        kept = [line for line in chunk if item(line) not in owned]
        if gone:
            kept = [line for line in kept if not line.strip() or not re.match(r"^\s*[-*]", line)]
        body += kept
        if n == 0:
            body += ["", "### Parts", ""] + [
                "- [ ] Part \u201c%s\u201d meets its %d criteria; its own checker checks them "
                "(journal: `%s`)" % (p["name"], len(p["criteria"]), p["journal"]) for p in parts] + [""]
    text = "\n".join(lines[:start + 1] + body + [""] + lines[end:])
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip("\n")
    return text + ("\n" if (journal or "").endswith("\n") else "")


def tick_parts(journal, names):
    """The journal with the lines of the parts named ticked."""
    def tick(line):
        m = PART_LINE.match(line)
        return PART_LINE.sub(r"\1x\3", line) if m and m.group(4) in names else line
    return "\n".join(tick(line) for line in (journal or "").split("\n"))


def part_id(parent_id, name):
    return "%s--%s" % (parent_id, st.slugify(name, max_words=4))


def parts_done_prompt(parts, journal=None):
    """What the lead hears when every part is merged. With `journal`, it starts a new
    session for the integration, from its journal and the parts' journals."""
    lines = []
    if journal:
        lines += ["You integrate the parts in a new session: you do not remember the planning. "
                  "Read your journal, `%s`, first: its decisions and its acceptance criteria. "
                  "The criteria no part has are yours to meet. Then read each part's journal "
                  "for what it built and what it decided." % journal, ""]
    lines += ["Every part is built, passed its own checker, and is merged into your branch:", ""]
    lines += ["- %s: %s%s" % (p["name"], p.get("summary") or "done",
                              " (journal: `%s`)" % p["journal"] if p.get("journal") else "")
              for p in parts]
    lines += ["", "Now integrate. Read what each part did. First hand over the tests of the "
              "paths in the technical plan that cross parts, each from its real entry point "
              "through every part. Then check that the parts fit together: the contracts, the "
              "data flowing between them, the shared facts, and the screens end to end. Build "
              "what no part covers and what the path tests show. Each part's line in your "
              "criteria is ticked already. Tick each of your own criteria the branch meets, "
              "with the file that meets it. Then report done.", "", CONTINUE]
    return "\n".join(lines)


def gaps_prompt(gaps, answers=None):
    parts = ["An independent checker compared the branch with the ask and its references, "
             "and found that it is not finished:", ""]
    parts += ["- %s" % g for g in gaps] + [""]
    if answers:
        parts += [answers, ""]
    parts += ["Before you fix a gap, check it against the references. The prototype wins, "
              "unless the ask says explicitly that it replaces the prototype, or the "
              "person's answers say otherwise. One-pagers decide nothing. Do not change what "
              "the prototype shows to satisfy a gap. If a gap is wrong, do not fix it: write "
              "why in the journal and say so in your summary, and the checker reads that. If "
              "the prototype and the person's answers do not settle a gap, ask the person. "
              "A gap that names where and what is wrong needs no explorer: hand over its fix "
              "at once. A gap that adds a requirement becomes a criterion; do not keep the gap "
              "itself in the journal once it is fixed. Then report done again."]
    return "\n".join(parts)


ADDRESSED = "Addressed the review comments"
REVIEW_DOING = "ready to merge — watching the PR for review comments"


def after(stamp, since):
    """Whether a GitHub time, such as 2026-11-08T21:13:40Z, is after `since`, in
    seconds since the epoch."""
    try:
        return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp() > since
    except (TypeError, ValueError):
        return False


def pr_review_prompt(feedback):
    """What the lead hears when someone commented on the finished goal's PR."""
    return ("The goal is done and its PR is open for review. These review comments were "
            "left on it:\n\n%s\n"
            "Address each one, as in the build: hand over tasks for the changes. Where a "
            "comment is wrong or out of scope, do not change the code for it. Record the "
            "changes in the journal, with an acceptance criterion for each new requirement, "
            "then report done. The runner checks the branch, pushes, waits for CI, and posts "
            "your `walkthrough` on the PR as the reply. Write it for this revision only, "
            "with these `##` sections:\n\n"
            "- **Comments**: each comment in a few words, then what you changed for it and "
            "what is different for users now; or the answer to its question; or why you did "
            "not change the code for it.\n"
            "- **Behaviour**: what else is different when this revision is live, and what it "
            "does not touch. Leave it out when the comments cover it.\n"
            "- **Key files**: only the files that matter in this revision, each as `path`: "
            "one short sentence that says why it changed.\n\n"
            "Write it in ASD-STE100. Put a one-sentence `summary` of the revision in the "
            "result block too." % feedback)


def answers_text(questions, answer):
    """The person's answer to questions a reviewer or checker raised, for the lead."""
    lines = ["The person was asked:", ""] + ["- %s" % st.question_brief(q) for q in questions]
    lines += ["", "They answered:", "", answer.strip()]
    return "\n".join(lines)


def conflict_prompt(base, files):
    return ("You reported done. The runner merged `%s` into your branch to sync "
            "it, and the merge conflicts in:\n\n%s\n\nThe merge is still in progress. "
            "Resolve the conflicts, commit the merge, then report done again."
            % (base, "\n".join("- `%s`" % f for f in files)))


CI_FIX_WORK = (
    "- You find the cause; sub-agents make the changes. Decide each fix yourself: the "
    "file, the lines and the change. Then start one sub-agent for each fix, or for each "
    "group of fixes in the same files. Give each a precise brief: the files and lines, "
    "the change, and the command that checks it. Start the ones that touch different "
    "files at the same time. They run on the sub-agent model. A hook refuses your own "
    "edits, so do not try.\n"
    "- Check what each sub-agent did from its report and `git diff`. When a fix is "
    "wrong or not complete, brief a sub-agent again.\n")


def ci_fix_prompt(branch, failures):
    """The cheap fixer's whole brief: the failing checks, and the rules."""
    return ("You fix failing CI checks on branch `%s`, in this worktree. Another agent "
            "built the work; only make these checks pass.\n\n%s\n\nRules:\n"
            "- Fix the cause in the code or the tests. Never weaken a check, skip a test, "
            "raise a budget, or add a baseline entry.\n"
            "- Change only what the failures need. Do not refactor or add features.\n"
            "- Open only the files and lines the failures name, and the code they call where "
            "the fix needs it. Do not explore or search the codebase beyond that.\n"
            "%s"
            "- Read why it fails from CI, not by running it here: `gh run view <run-id> "
            "--log-failed` gives the whole log of a failed job (the run id is in its URL).\n"
            "- This machine runs many agents at once. Run only single test files by their "
            "path, and a linter or type check on the files you change. Never run a whole "
            "suite (`npx vitest run`, `pytest` with no paths, `npm test`), coverage, "
            "`make verify`, `npm run verify*`, a build, or e2e tests. CI runs those after "
            "your fix.\n"
            "- Commit with a clear message, then stop. Do not push, rebase, or merge: the "
            "runner pushes, and CI checks the fix.\n"
            "- Do not run skills or slash commands."
            % (branch, failures, CI_FIX_WORK))


def script_steps(scripts, name, depth=0):
    """An npm script as its steps: `a && b` is two, and `npm run x` is x's own
    steps. A script with other shell control, such as `||` or `;`, is one step."""
    body = (scripts.get(name) or "").strip()
    if depth > 5 or not body or re.search(r"\|\||;|\(|\)|`|\$\(", body):
        return ["npm run %s" % name] if depth else ([body] if body else [])
    out = []
    for part in [p.strip() for p in body.split("&&") if p.strip()]:
        m = re.fullmatch(r"npm\s+run\s+([\w:.-]+)", part)
        out += script_steps(scripts, m.group(1), depth + 1) if m and m.group(1) in scripts else [part]
    return out


def local_ci_fix_prompt(branch, failures, steps):
    """The CI fixer's brief for the static checks run here: every failing step at
    once, and how to stay on them."""
    rerun = "\n".join("  - `%s`%s" % (cmd, " in `%s`" % sub if sub else "") for _, cmd, sub in steps)
    return ("You fix failing CI static checks on branch `%s`, in this worktree. Another "
            "agent built the work; you only make these checks pass. The runner ran every "
            "step of CI's static checks here, and these steps fail:\n\n%s\n\n"
            "How to work:\n"
            "- Fix every failing step in this one session, not only the first.\n"
            "- Work from the output above. Open only the files and lines it names, and the "
            "code they call where the fix needs it. Do not explore or search the codebase "
            "beyond that. Do not read files to learn the project.\n"
            "- When a failure names no file, such as a size budget, find its cause with the "
            "fewest reads you can: `git diff` against the base for what the branch added.\n"
            "- Fix the cause in the code or the tests. Never weaken a check, skip a test, "
            "raise a budget, or add a baseline entry. Locking in a saving that a check asks "
            "for, such as a budget that is now far under, is allowed.\n"
            "- Change only what the failures need. Do not refactor or add features.\n"
            "%s"
            "- After the fixes, run the failing steps again yourself, and only them:\n%s\n"
            "  Run no other suite, build or check. Brief a sub-agent again for what still "
            "fails.\n"
            "- Commit with a clear message, then stop. Do not push, rebase, or merge.\n"
            "- Do not run skills or slash commands."
            % (branch, failures, CI_FIX_WORK, rerun))


def ci_commands(worktree):
    """The repo's own commands for what CI checks, as [(name, command, cwd)], one a
    step, so that one failing step does not hide the ones after it: each target a
    `ci-verify` make target at the root depends on, and each step of a `ci-verify`
    script in each package."""
    out = []
    try:
        with open(os.path.join(worktree, "Makefile")) as f:
            m = re.search(r"^ci-verify:([^#\n]*)", f.read(), re.M)
        if m:
            targets = m.group(1).split()
            out += [("make %s" % t, "make %s" % t, None) for t in targets] or [
                ("make ci-verify", "make ci-verify", None)]
    except (IOError, OSError):
        pass
    _, files, _ = st.git(["ls-files", "package.json", "*/package.json", "*/*/package.json"],
                         cwd=worktree, check=False)
    for rel in sorted(files.split()):
        try:
            with open(os.path.join(worktree, rel)) as f:
                scripts = json.load(f).get("scripts") or {}
        except (IOError, OSError, ValueError):
            continue
        if "ci-verify" in scripts:
            folder = os.path.dirname(rel)
            out += [("%s: %s" % (folder or "npm", step), step, folder or None)
                    for step in script_steps(scripts, "ci-verify")]
    return out


def run_ci_steps(steps, worktree):
    """Run every step, past a failure too. Returns [(name, cmd, output, exit code)]
    of each step that failed. A step runs as `npm run` would run it: with the package's and
    the root's `node_modules/.bin` on the PATH."""
    failures = []
    for name, cmd, sub in steps:
        cwd = os.path.join(worktree, sub) if sub else worktree
        bins = [os.path.join(cwd, "node_modules", ".bin"), os.path.join(worktree, "node_modules", ".bin")]
        env = dict(os.environ, PATH=os.pathsep.join(bins + [os.environ.get("PATH", "")]))
        st.info("%s%s" % (cmd, " (in %s)" % sub if sub else ""))
        proc = subprocess.run(cmd, cwd=cwd, shell=True, stdin=subprocess.DEVNULL, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            st.warn("%s failed (exit %d)" % (name, proc.returncode))
            failures.append((name, cmd, proc.stdout.decode("utf-8", "replace"), proc.returncode))
    return failures


def lockfiles(worktree):
    """Each lockfile in the repo, up to three folders down, as [(path, folder of its
    install, install command)]."""
    names = {name: (deps, cmd) for name, deps, cmd in LOCKFILES}
    _, out, _ = st.git(["ls-files"] + [p % n for n in names for p in ("%s", "*/%s", "*/*/%s")],
                       cwd=worktree, check=False)
    return [(rel,) + names[os.path.basename(rel)] for rel in sorted(out.split())]


def file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except (IOError, OSError):
        return None


def stale_installs(worktree, installed):
    """The installs a worktree needs: each lockfile whose folder is missing, or that
    changed since its last install, as [(path, folder, its install's folder, command,
    hash)]. `installed` maps each lockfile to its hash at its last install."""
    out = []
    for rel, deps, cmd in lockfiles(worktree):
        folder = os.path.dirname(rel)
        digest = file_hash(os.path.join(worktree, rel))
        if installed.get(rel) != digest or not os.path.isdir(os.path.join(worktree, folder, deps)):
            out.append((rel, folder, deps, cmd, digest))
    return out


def install_dependencies(worktree, installed, source=None):
    """Install what `stale_installs` finds, with the repo's own lockfiles. Where the
    `source` worktree has the same lockfile installed, link its install instead: a
    part shares its goal's. Returns the new `installed`, and a line for each install
    that failed."""
    installed, failed = dict(installed), []
    for rel, folder, deps, cmd, digest in stale_installs(worktree, installed):
        here = os.path.join(worktree, folder, deps)
        if os.path.islink(here):
            os.unlink(here)
        theirs = os.path.join(source, folder, deps) if source else None
        if theirs and file_hash(os.path.join(source, rel)) == digest and os.path.isdir(theirs) \
                and not os.path.islink(theirs) and not os.path.exists(here):
            os.symlink(theirs, here)
            keep_out_of_git(worktree, [os.path.normpath(os.path.join(folder, deps))])
            installed[rel] = digest
            continue
        st.info("%s%s" % (cmd, " (in %s)" % folder if folder else ""))
        try:
            proc = subprocess.run(cmd, cwd=os.path.join(worktree, folder), shell=True,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=INSTALL_TIMEOUT)
            code, output = proc.returncode, proc.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            code, output = None, "timed out"
        if code == 0:
            installed[rel] = digest
        else:
            line = (output.strip().splitlines() or ["exit %s" % code])[-1][:200]
            failed.append("%s: %s" % (cmd, line))
            st.warn("%s failed: %s" % (cmd, line))
    return installed, failed


def notify(title, text, sound, url=None):
    """On macOS, a banner from Conductor.app with a sound, for what needs the person;
    a click on it opens `url`. Nothing on another system, or when COND_QUIET is set."""
    if os.environ.get("COND_QUIET") or sys.platform != "darwin":
        return
    try:
        subprocess.Popen([sys.executable, NOTIFY, title, " ".join((text or "").split()), url or "", sound],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def page_url(main_root, gid=None):
    """The goal's page on the service, or its Runs page."""
    port = os.environ.get("COND_PORT") or "4747"
    rid = st.slugify(os.path.basename(main_root.rstrip(os.sep)) or "repo", max_words=8)
    return "http://127.0.0.1:%s/#/%s" % (port, "g/%s/%s" % (rid, gid) if gid else "")


def ci_failures_text(failures):
    """Every failing step with the end of its output, the most telling part."""
    each = max(1500, 16000 // max(1, len(failures)))
    return "\n\n".join("- `%s`, run here as `%s`:\n\n```\n%s\n```" % (
        f[0], f[1], f[2].strip()[-each:]) for f in failures)


def fix_signature(text):
    """What a fix is about, as the names it lists: two fixes with the same names are
    the same failure again; different names mean the last fix made progress."""
    return sorted(set(re.findall(r"^- `([^`]+)`", text or "", re.M)))


def failed_ci_prompt(failing, excerpts):
    """What CI says when it fails on the PR: each failed check, with the telling
    lines of its log where GitHub gave them."""
    parts = ["You reported done. CI ran on the PR, and these checks fail:", ""]
    for name, url in failing:
        parts.append("- `%s`%s" % (name, " (%s)" % url if url else ""))
    for name, lines in sorted(excerpts.items()):
        parts += ["", "From the log of `%s`:" % name, "", "```", "\n".join(lines)[-4000:], "```"]
    parts += ["", "Fix the cause, then report done again. Never weaken a check, raise a "
              "budget, or add a baseline entry to make it pass."]
    return "\n".join(parts)


def changes_since(sha, base):
    return ("the branch's own commits since then, `git log -p --first-parent --no-merges "
            "%s..HEAD`, and in each merge of `%s` since then only the lines that touch the "
            "work" % (sha, base))


def recheck_scope(sha, gaps, revision, base):
    """check.md's scope for a branch checked before at `sha`."""
    found = ("found these gaps:\n\n%s" % "\n".join("- %s" % g for g in gaps) if gaps
             else "found the work done.")
    lines = ["## What this check covers", "",
             "An earlier check of this branch, at commit `%s`, %s" % (sha, found), ""]
    if revision:
        lines += ["Since then, review comments on the PR asked for changes:", "", revision.strip(), ""]
    lines += ["Everything that check passed is met, unless what changed since breaks it. "
              "So check only these, and nothing else:", ""]
    n = 1
    if gaps:
        lines.append("%d. Each gap above: is it fixed, as its reference requires? Where the "
                     "journal says why it is not a gap, weigh that against the references." % n)
        n += 1
    if revision:
        lines.append("%d. Each review comment: is it addressed, or does the journal say why "
                     "not?" % n)
        n += 1
    lines += ["%d. What changed since: %s. For each criterion these changes touch, is it "
              "met? Do they break anything the earlier check passed?" % (n, changes_since(sha, base)),
              "", "Read the ask, the references and the journal only as far as these need. "
              "Where the steps below say to read or check everything, keep to this list.", ""]
    return "\n".join(lines)


def integration_scope(sha, technical_plan, base):
    """check.md's scope for the first check of a split goal, once its parts are merged."""
    return "\n".join([
        "## What this check covers", "",
        "Each part of this goal was built and checked by its own checker against its own "
        "criteria, and the parts were merged into this branch at commit `%s`. Do not check "
        "the parts' criteria again. Check only these, and nothing else:" % sha, "",
        "1. The goal's own acceptance criteria in the journal, which span the parts. A "
        "line that says a part meets its criteria is met: that part's checker checked them.",
        "2. How the parts meet: each meeting point in the technical plan `%s` (an endpoint, "
        "a shared type, an event). Does the part that provides it match what the parts "
        "that use it expect?" % technical_plan,
        "3. Each path in the technical plan that crosses parts, step by step: the part "
        "that writes a value and the part that reads it agree, and the existing code the "
        "path runs through does what the path expects.",
        "4. Each shared fact and invariant in the technical plan: every part, and the "
        "existing code, follows it.",
        "5. What changed since the parts were merged: %s." % changes_since(sha, base), "",
        "Read the ask, the references and the journal only as far as these need. Where "
        "the steps below say to read or check everything, keep to this list.", ""])


def link_dependencies(source, target):
    """Link the installed dependencies of one worktree into another, so a task's
    tests can run without an install. The links are kept out of git."""
    linked = []
    for root, dirs, _ in os.walk(source):
        rel = os.path.relpath(root, source)
        if rel.count(os.sep) >= 3 or any(p in (".git", ".cortex") for p in rel.split(os.sep)):
            dirs[:] = []
            continue
        for d in list(dirs):
            if d in DEP_DIRS:
                dirs.remove(d)
                path = os.path.normpath(os.path.join(rel, d))
                dest = os.path.join(target, path)
                if os.path.isdir(os.path.dirname(dest)) and not os.path.lexists(dest):
                    os.symlink(os.path.join(root, d), dest)
                    linked.append(path)
            elif d.startswith("."):
                dirs.remove(d)
    keep_out_of_git(target, linked)
    return linked


def keep_out_of_git(target, paths):
    """Keep linked paths out of git, so `git add -A` never commits the links."""
    if not paths:
        return
    _, common, _ = st.git(["rev-parse", "--git-common-dir"], cwd=target, check=False)
    exclude = os.path.join(os.path.join(target, common.strip()) if not os.path.isabs(
        common.strip()) else common.strip(), "info", "exclude")
    try:
        with open(exclude) as f:
            have = set(f.read().splitlines())
    except (IOError, OSError):
        have = set()
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    with open(exclude, "a") as f:
        for path in paths:
            if "/" + path not in have:
                f.write("/%s\n" % path)


TESTING_CHECK = (" Judge the tests against %sthe test map in the technical plan or the "
                 "journal. A rule in the map with no test is a gap. So is a test of a rule "
                 "that another test already covers, a test with no rule in the map, and a "
                 "test the repository's way of testing does not ask for, such as a test of a "
                 "framework's own behaviour or of a test stub, unless the repository tests "
                 "such things. Name each such test.")


def tests_line(tests):
    """A coding task's tests, in one line for the lead: the command and how it went,
    the names of at most five failing tests, or why none ran."""
    if not isinstance(tests, dict):
        return None
    command = str(tests.get("command") or "").strip()
    result = str(tests.get("result") or "").strip().lower()
    if result == "none" or not command:
        return "none run" + (": %s" % str(tests["why"]).strip() if tests.get("why") else "")
    line = "`%s` %s" % (command, result or "ran")
    count = tests.get("count")
    if result == "passed" and isinstance(count, int):
        line += " (%d)" % count
    failed = [str(f) for f in tests.get("failed") or [] if str(f).strip()]
    if failed:
        line += ": " + ", ".join(failed[:5])
        if len(failed) > 5:
            line += " and %d more" % (len(failed) - 5)
    added = [a for a in tests.get("added") or [] if isinstance(a, dict) and a.get("test")]
    if added:
        line += "; added: " + "; ".join(
            "`%s` (%s)" % (a["test"], str(a.get("rule") or "no rule given").strip()) for a in added)
    return line


def dispatched_prompt(reports):
    """What the lead gets back from its tasks, in a new session."""
    lines = ["The runner ran your tasks. Their reports, in your order:", ""]
    for r in reports:
        if not r:
            continue
        lines.append("### %s (%s): %s" % (r["name"], "question" if r["kind"] == "explore"
                                           else "coding task", r["status"]))
        for key, label in (("summary", "Did"), ("answer", "Answer"), ("files", "Files"),
                           ("tests", "Tests"), ("notes", "Notes"), ("merge", "Branch")):
            if key == "tests":
                if tests_line(r.get(key)):
                    lines.append("- Tests: %s" % tests_line(r[key]))
            elif r.get(key):
                value = ", ".join("`%s`" % f for f in r[key]) if isinstance(r[key], list) else r[key]
                lines.append("- %s: %s" % (label, value))
        lines.append("")
    lines += ["Check the results against the plan, from these reports, or with an explorer "
              "or a reviewer task. Check each test a task added against the test map: a test "
              "with no rule in the map, or of a rule another test covers, goes back as a task "
              "that removes it or merges it. Tick what is done in the journal. Then hand over the next "
              "tasks with the `dispatch` block, or end with `done` when every step and "
              "criterion is ticked."]
    return "\n".join(lines)


def checks_text(base):
    """Step 3 of the checker's prompt: CI comes after the check."""
    return ("The runner merged `%s` into the branch. Nothing is pushed yet: CI runs once this "
            "check is clean, and a cheaper agent fixes what fails. Judge the code, not test "
            "results." % base)


def checks_section(checks, left=None):
    """The PR comment's Checks section: what CI passed on the final branch, and the
    static checks left to it because they could not tell here."""
    text = ("## Checks\n\nThe PR has no CI checks." if not checks else
            "## Checks\n\nCI passed: %s." % ", ".join("`%s`" % c for c in checks))
    if left:
        text += "\n\nNot run before the push, left to CI: %s." % "; ".join(left)
    return text


SKIP_DIRS = {".git", "node_modules", ".cortex", "dist", "build", ".venv", "venv", "vendor"}


def testing_guides(root, depth=3):
    """The repository's TESTING.md files, relative to `root`, the top one first."""
    out = []
    for path, dirs, files in os.walk(root):
        rel = os.path.relpath(path, root)
        level = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")) \
            if level < depth else []
        out += [os.path.normpath(os.path.join(rel, f)) for f in files if f.lower() == "testing.md"]
    return sorted(out, key=lambda f: (f.count(os.sep), f))


def journal_lost(before, after):
    """What a compacted journal lost that it must keep, or None: every acceptance
    criterion and plan step with its tick, word for word, and every section of the
    person's answers."""
    if not (after or "").strip():
        return "it is empty"
    for heading in ("Acceptance criteria", "Plan"):
        if (checklist(before, heading) or []) != (checklist(after, heading) or []):
            return "its %s changed" % heading.lower()
    for heading in re.findall(r"^## +(.*answer.*?)\s*$", before or "", re.M | re.I):
        if section_text(before, heading) != section_text(after, heading):
            return "it changed \"%s\"" % heading
    if len(after) >= len(before) * 0.9:
        return "it is not smaller"
    return None


def plan_names(journal, parts=None):
    """The plan as the person reads it: the parts when the work is split, else the
    first line of each step of the journal's `## Plan`."""
    if parts:
        return [p["name"] for p in parts]
    return [re.sub(r"\s+", " ", text.splitlines()[0]).strip()
            for _, text in checklist(journal, "Plan") or [] if text.strip()]


_APPROVALS = {"", "c", "continue", "ok", "okay", "go", "go on", "yes", "y", "approve",
              "approved", "lgtm"}


def approves(text):
    """Whether an answer to the plan's review only approves it, with nothing to change."""
    return re.sub(r"[\s.!]+$", "", (text or "").strip().lower()) in _APPROVALS


def revise_prompt(notes):
    """What the lead hears when the person asked for changes to the plan."""
    return "\n".join(["The person reviewed your plan and asked for changes:", "", notes.strip(), "",
                      "Revise your journal to answer it: the acceptance criteria and the plan, the "
                      "technical plan, and the parts file if you split the work. Where a change is "
                      "unclear or conflicts with the prototype, ask. Do not build yet. Report planned "
                      "again, and in its summary tell the person, in a few sentences, what you changed "
                      "and why: they read it with the plan."])


def built_text(built):
    if not built:
        return ""
    return "\n".join(["These parts are done, and merged into your branch now:", ""] + [
        "- %s: %s" % (b["name"], b.get("summary") or "done") for b in built] + [""])


def hook_settings(flag, subagent=None, fence=(), allow=None, delegate=None, lead=False,
                  readonly=None, task=False, force_subagent=False, explore=False, notes=None):
    """Claude Code settings whose hooks reach the call and its sub-agents alike.
    While `flag` exists the call winds down: a new sub-agent is refused, and every
    other tool call says to stop at the next safe point. A push, a CI run and a
    change to the PR are always refused: only the runner pushes. A sub-agent
    started without a model gets `subagent`. A tool call that names one of the
    `fence` texts is refused. With `delegate`, the worktree, the lead may not
    change or read the code there itself: its sub-agents do. With `notes`, the
    goal's state, the person's notes reach the lead after its next tool call."""
    check = "test -f %s && { printf '%%s\\n' %s >&2; exit 2; }; exit 0" % (
        shlex.quote(flag), shlex.quote(WIND_DOWN))
    hook = [{"type": "command", "command": check}]

    def guard(*args):
        return {"type": "command", "command": " ".join(
            shlex.quote(a) for a in (sys.executable, HOOK) + args)}
    agent = hook + ([guard(*(("agent", subagent, "force") if force_subagent else ("agent", subagent)))]
                    if subagent else [])
    pre = [{"matcher": "Agent|Task", "hooks": agent},
           {"matcher": "Bash", "hooks": [guard(*(("bash", "lead") if lead else ("bash",)))]}]
    if fence:
        pre.append({"matcher": "*", "hooks": [guard("fence", *fence)]})
    if delegate:
        pre.append({"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|Read|Grep|Glob",
                    "hooks": [guard("delegate", delegate)]})
    if readonly:
        pre.append({"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
                    "hooks": [guard("readonly", readonly)]})
    if task:
        pre.append({"matcher": "Bash", "hooks": [guard("task")]})
    if explore:
        pre.append({"matcher": "Bash", "hooks": [guard("explore")]})
    out = {"hooks": {"PreToolUse": pre,
                     "PostToolUse": [{"matcher": "*", "hooks": hook + (
                         [guard("note", notes)] if notes else [])}]}}
    if allow:
        out["permissions"] = {"allow": allow}
    return out


def cut_off_prompt(at, agents, dirty):
    """What the lead is told when its last call had to be cut off mid-work."""
    lines = ["Your last call was cut off at %s, because the person's usage limit ran over "
             "while it was working. Nothing was handed back to you from it." % time.strftime(
                 "%H:%M", time.localtime(at)), ""]
    if agents:
        lines += ["These sub-agents were still working and were stopped. Their reports "
                  "never reached you:", ""] + ["- %s" % a for a in agents] + [""]
    if dirty:
        lines += ["These files have changes that are not committed. Some may be "
                  "half done:", ""] + ["- `%s`" % f for f in dirty[:60]]
        if len(dirty) > 60:
            lines.append("- … and %d more" % (len(dirty) - 60))
        lines.append("")
    lines += ["Check that work before you build on it: finish it, or redo it. Then "
              "continue.", "", CONTINUE]
    return "\n".join(lines)


def answer_prompt(questions, answer):
    lines = ["You asked the person:", ""]
    lines += ["- %s" % st.question_brief(q) for q in questions or []]
    lines += ["", "They answered:", "", answer.strip(), "", CONTINUE]
    return "\n".join(lines)


# --- what each call cost --------------------------------------------------------
#
# A call's own messages and each sub-agent's are in Claude Code's transcripts, with
# their model, tokens and times. The call's result says what each model cost in
# all; that is shared out by tokens, weighted as the API prices them.

TOKEN_KEYS = (("input", "input_tokens", "inputTokens"),
              ("output", "output_tokens", "outputTokens"),
              ("cache_read", "cache_read_input_tokens", "cacheReadInputTokens"),
              ("cache_write", "cache_creation_input_tokens", "cacheCreationInputTokens"))
TOKEN_WEIGHTS = {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25}
MODEL_NAMES = (("fable", "fable"), ("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku"))


def _when(text):
    try:
        return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def transcript_usage(lines, since=0):
    """From a transcript's JSON lines: {model, tokens, first, last}, counting each
    message once and only what came at or after `since`. None when nothing did."""
    seen, tokens, models, times = set(), dict.fromkeys(TOKEN_WEIGHTS, 0), {}, []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = _when(row.get("timestamp"))
        if at is None or at < since:
            continue
        times.append(at)
        message = row.get("message") or {}
        usage = message.get("usage")
        if not isinstance(usage, dict) or message.get("id") in seen:
            continue
        seen.add(message.get("id"))
        for name, key, _ in TOKEN_KEYS:
            tokens[name] += usage.get(key) or 0
        if message.get("model"):
            models[message["model"]] = models.get(message["model"], 0) + 1
    if not seen:
        return None
    return {"model": max(models, key=models.get) if models else None, "tokens": tokens,
            "first": min(times), "last": max(times)}


def weight(tokens):
    return sum(TOKEN_WEIGHTS[k] * (tokens.get(k) or 0) for k in TOKEN_WEIGHTS)


def unit_costs(model_usage):
    """{model: dollars per weighted token}, from a call result's `modelUsage`."""
    out = {}
    for model, use in (model_usage or {}).items():
        units = weight({name: use.get(camel) or 0 for name, _, camel in TOKEN_KEYS})
        if units and use.get("costUSD") is not None:
            out[model] = use["costUSD"] / units
    return out


def priced(entry, costs):
    cost = costs.get(entry.get("model"))
    return dict(entry, cost=None if cost is None else cost * weight(entry["tokens"]))


def short_model(model):
    return next((short for key, short in MODEL_NAMES if key in (model or "")), model or "?")


def _tokens(n):
    return "%.1fM" % (n / 1e6) if n >= 1e6 else "%dk" % round(n / 1e3) if n >= 1e3 else str(n)


def _span(seconds):
    seconds = int(seconds or 0)
    return ("%dh %02dm" % (seconds // 3600, seconds % 3600 // 60) if seconds >= 3600
            else "%dm %02ds" % (seconds // 60, seconds % 60) if seconds >= 60 else "%ds" % seconds)


def _cost(cost, estimated=False):
    if cost is None:
        return "cost unknown"
    return "≈ $%.2f%s" % (cost, " est." if estimated else "")


# What each model costs per weighted token, learned from calls that reported their
# cost, so a call that was cut off before it could can still be priced.
RATES_FILE = os.path.join(os.path.expanduser("~"), ".cortex", "cli", "model-rates.json")


def normalise(calls):
    """Calls as they are priced now. Before, a call's cost was what its result
    reported, and a resumed session reports its running total: so the lead's own
    cost in each call after its first is dropped, to be estimated from its tokens."""
    out, leads = [], 0
    for call in calls or []:
        if not call.get("v") and call.get("label") == "lead":
            leads += 1
            if leads > 1:
                call = dict(call, cost=None, main=dict(call["main"], cost=None))
        out.append(call)
    return out


def learned_rates(calls):
    """{model: dollars per weighted token} from every agent entry with a cost."""
    totals = {}
    for call in calls or []:
        for entry in [call.get("main")] + list(call.get("subagents") or []):
            if entry and entry.get("cost") is not None and not entry.get("estimated") \
                    and entry.get("model"):
                units = weight(entry["tokens"])
                if units:
                    t = totals.setdefault(entry["model"], [0.0, 0.0])
                    t[0] += entry["cost"]
                    t[1] += units
    return {m: cost / units for m, (cost, units) in totals.items() if units}


def load_rates(path=RATES_FILE):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def save_rates(rates, path=RATES_FILE):
    known = load_rates(path)
    known.update(rates)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(known, f, indent=2)


def estimate(calls, rates):
    """The calls, with every agent whose cost is unknown priced from its tokens at
    its model's learned rate (marked `estimated`), and each call's total made the
    sum of its agents where its own result gave none."""
    out = []
    for call in calls or []:
        call = dict(call)
        entries = []
        for entry in [call["main"]] + list(call.get("subagents") or []):
            entry = dict(entry)
            if entry.get("cost") is None and rates.get(entry.get("model")):
                entry["cost"] = rates[entry["model"]] * weight(entry["tokens"])
                entry["estimated"] = True
            entries.append(entry)
        call["main"], call["subagents"] = entries[0], entries[1:]
        if call.get("cost") is None and all(e.get("cost") is not None for e in entries):
            call["cost"] = sum(e["cost"] for e in entries)
            call["estimated"] = True
        out.append(call)
    return out


def write_report(goal, extra_rates=None, write=True):
    """A goal's calls priced as far as they can be, and their total cost; with
    `write`, its usage report is rewritten from them too."""
    calls = normalise(goal.state.read(CALLS_FILE))
    rates = dict(load_rates())
    rates.update(extra_rates or {})
    rates.update(learned_rates(calls))
    priced = estimate(calls, rates)
    if write and calls:
        with open(goal.state.path(REPORT_FILE), "w") as f:
            f.write(usage_report(priced))
    return priced, sum(c.get("cost") or 0 for c in priced)


def repo_rates(main_root):
    """Rates learned from every goal's calls in a repo."""
    calls = []
    for g in list_goals(main_root):
        calls += normalise(Goal(main_root, g["id"]).state.read(CALLS_FILE))
    return learned_rates(calls)


def _line(name, entry, width=46):
    tokens = entry["tokens"]
    total = sum(tokens.values())
    name = name if len(name) <= width else name[:width - 1] + "…"
    return "  %-*s %-7s %8s  %6s in · %5s out  %s" % (
        width, name, entry.get("model") if "/" in (entry.get("model") or "") else short_model(
            entry.get("model")), _span(entry.get("seconds")),
        _tokens(total - tokens["output"]), _tokens(tokens["output"]),
        _cost(entry.get("cost"), entry.get("estimated")))


def usage_report(calls):
    """The goal's usage, as the TUI shows it: totals by role, then each call with
    its sub-agents."""
    roles = {}
    for call in calls:
        for role, entry in [(ROLES.get(call["label"], call["label"]), call["main"])] + [
                ("sub-agents", a) for a in call.get("subagents") or []]:
            r = roles.setdefault(role, {"tokens": dict.fromkeys(TOKEN_WEIGHTS, 0), "seconds": 0,
                                        "cost": 0.0, "count": 0, "models": set(), "estimated": False})
            r["estimated"] = r["estimated"] or bool(entry.get("estimated"))
            for k in TOKEN_WEIGHTS:
                r["tokens"][k] += entry["tokens"][k]
            r["seconds"] += entry.get("seconds") or 0
            r["count"] += 1
            r["models"].add(short_model(entry.get("model")))
            r["cost"] = None if r["cost"] is None or entry.get("cost") is None else r["cost"] + entry["cost"]
    total_cost = sum(c["cost"] or 0 for c in calls) if calls else 0
    known = all(c.get("cost") is not None for c in calls)
    out = ["Costs are at API prices: on a subscription, what the work would cost, not a bill.",
           "Time is each agent's own; sub-agents run alongside their call.", "",
           "All calls: %s · %s%s" % (_span(sum(c["main"].get("seconds") or 0 for c in calls)),
                                     _tokens(sum(sum(r["tokens"].values()) for r in roles.values())),
                                     " · ≈ $%.2f" % total_cost + (
                                         "" if not known else " (some estimated)" if any(
                                             c.get("estimated") for c in calls) else "")
                                     + ("" if known else " so far known")),
           ""]
    for role in ("lead", "coding tasks", "explorers", "sub-agents", "CI fixes", "reviewer", "checker"):
        if role in roles:
            r = roles[role]
            entry = dict(r, model="/".join(sorted(r["models"])))
            out.append(_line("%s (%d)" % (role, r["count"]), entry))
    for call in calls:
        out += ["", "%s · %s%s · %s · %s" % (
            ({"lead": "Round %s", "check": "Check %s", "review": "Review %s", "ci-fix": "CI fix %s",
              "task": "Task %s", "explore": "Explorer %s"}.get(call["label"], call["label"] + " %s")
             % call["round"]) + (": " + call["name"] if call.get("name") else ""),
            short_model(call["model"]), " %s effort" % call["effort"] if call.get("effort") else "",
            time.strftime("%a %H:%M", time.localtime(call["started"])),
            _cost(call.get("cost"), call.get("estimated")))]
        out.append(_line(call["label"] + " itself", call["main"]))
        for agent in call.get("subagents") or []:
            out.append(_line("  " + (agent.get("description") or "sub-agent"), agent))
    return "\n".join(out) + "\n"


def unfinished_subagents(session, since, claude_dir=None):
    """The descriptions of a session's sub-agents started since `since` that never
    finished."""
    base = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    out = []
    for meta in glob.glob(os.path.join(base, "projects", "*", session, "subagents", "agent-*.meta.json")):
        try:
            with open(meta) as f:
                data = json.load(f)
        except (IOError, OSError, ValueError):
            continue
        if data.get("finished") is not True and os.path.getmtime(meta[:-len(".meta.json")] + ".jsonl") >= since:
            out.append(data.get("description") or "a sub-agent")
    return sorted(out)


def read_call(session, since, model_usage=None, claude_dir=None):
    """(main, [sub-agents]) of a call, from its session's transcripts: each with
    model, tokens, seconds and cost."""
    base = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    found = glob.glob(os.path.join(base, "projects", "*", session + ".jsonl"))
    if not found:
        return None, []
    costs = unit_costs(model_usage)

    def entry(path, **extra):
        with open(path) as f:
            use = transcript_usage(f, since)
        if not use:
            return None
        return priced(dict(extra, model=use["model"], tokens=use["tokens"],
                           seconds=use["last"] - use["first"]), costs)

    main = entry(found[0])
    agents = []
    for path in sorted(glob.glob(os.path.join(found[0][:-len(".jsonl")], "subagents", "agent-*.jsonl"))):
        try:
            with open(path[:-len(".jsonl")] + ".meta.json") as f:
                meta = json.load(f)
        except (IOError, OSError, ValueError):
            meta = {}
        agent = entry(path, description=meta.get("description"), depth=meta.get("spawnDepth"))
        if agent:
            agents.append(agent)
    agents.sort(key=lambda a: a.get("seconds") or 0, reverse=True)
    return main, agents


# --- state -------------------------------------------------------------------

class Goal(object):
    def __init__(self, main_root, gid):
        self.main_root = main_root
        self.id = gid
        self.state = st.State(main_root, gid)

    def read(self):
        return self.state.read(GOAL_FILE, {})

    def update(self, **fields):
        """Under a lock: a part's runner and its parent's both write here, and neither
        may lose the other's fields."""
        self.state.ensure()
        with open(self.state.path(GOAL_LOCK), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read()
            if data.get("marked_done"):
                fields = {k: v for k, v in fields.items() if k not in ("status", "phase", "doing")}
            data.update(fields)
            data["updated"] = time.time()
            self.state.write(GOAL_FILE, data)
        return data

    def runner_alive(self):
        """Whether a runner holds this goal: it keeps its run lock while it lives,
        so a pid written over or left behind cannot mislead."""
        if not os.path.isdir(self.state.dir):
            return False
        with open(self.state.path(RUN_LOCK), "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
        return False

    def hold(self):
        """Take the run lock for the life of this process. False when another
        runner has it."""
        self.state.ensure()
        lock = open(self.state.path(RUN_LOCK), "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            return False
        _RUN_LOCK.append(lock)
        return True

    @property
    def journal(self):
        return self.state.path(JOURNAL_FILE)

    @property
    def log(self):
        return self.state.path(LOG_FILE)


RUNNERS = ("claude", "opencode")


def active_models(control):
    """{lead, subagent, check}: the models of what goals run on, Claude Code or
    OpenCode, from the repo's settings."""
    control = control or {}
    if control.get("runner") == "opencode":
        return control.get("opencode") or {}
    return control.get("models") or {}


def settings_from(control):
    """The models a new goal uses, from the repo's settings: {model, subagent_model,
    check_model, check_effort, threshold, gate}."""
    models = active_models(control)
    if (control or {}).get("runner") == "opencode" and not all(models.get(k) for k in ("lead", "subagent", "check")):
        raise st.Failure("goals run on OpenCode, but its lead, coding-task and checker models are not all set")
    return {"model": models.get("lead") or DEFAULT_MODEL,
            "subagent_model": models.get("subagent") or DEFAULT_SUBAGENT_MODEL,
            "check_model": models.get("check") or DEFAULT_CHECK_MODEL,
            "check_effort": ((control or {}).get("models") or {}).get("check_effort") or DEFAULT_CHECK_EFFORT,
            "threshold": (control or {}).get("usage_threshold") or DEFAULT_THRESHOLD,
            "gate": (control or {}).get("goal_gate") if (control or {}).get("goal_gate") in GATES
            else DEFAULT_GATE}


def create(main_root, prompt, files=(), base=None, name=None, key=None,
           threshold=DEFAULT_THRESHOLD, model=DEFAULT_MODEL,
           subagent_model=DEFAULT_SUBAGENT_MODEL, check_model=DEFAULT_CHECK_MODEL,
           check_effort=DEFAULT_CHECK_EFFORT, gate=DEFAULT_GATE, now=None):
    """Write a new goal for a prompt and the files given with it, which are copied
    into the goal. Returns its id; nothing runs yet, and the tickets the prompt
    links to are read when it starts. `key` and `name` default to the first linked
    ticket's key and name, and `name` else to the prompt's first line."""
    if not (prompt or "").strip():
        raise st.Failure("a goal needs a prompt")
    for path in files:
        if not (os.path.isfile(path) or os.path.isdir(path)):
            raise st.Failure("no file or folder %s" % path)
    ticket = first_ticket(main_root, prompt) if not (name and key) else {}
    key = key or (st.task_key(ticket) if ticket else None)
    name = name or prompt_name(ticket.get("name")) or prompt_name(prompt) or "goal"
    gid, n = goal_id(key, name), 1
    while os.path.isdir(Goal(main_root, gid).state.dir):
        n += 1
        gid = "%s-%d" % (goal_id(key, name), n)
    goal = Goal(main_root, gid)
    goal.state.ensure()
    given = []
    if files:
        import shutil
        os.makedirs(goal.state.path(INPUTS_DIR), exist_ok=True)
        for path in files:
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(path)) or "file"
            while os.path.exists(goal.state.path(os.path.join(INPUTS_DIR, safe))):
                safe = "_" + safe
            if os.path.isdir(path):
                shutil.copytree(path, goal.state.path(os.path.join(INPUTS_DIR, safe)),
                                ignore=shutil.ignore_patterns(".*"))
            else:
                shutil.copyfile(path, goal.state.path(os.path.join(INPUTS_DIR, safe)))
            given.append(os.path.join(INPUTS_DIR, safe))
    goal.update(id=gid, prompt=prompt.strip(), files=given, key=key, name=name, base=base,
                threshold=threshold, model=model, subagent_model=subagent_model,
                check_model=check_model or model, check_effort=check_effort,
                created=now or time.time(), status="new", flow=FLOW, gate=gate,
                round=0, phase="planning")
    return gid


def first_ticket(main_root, prompt):
    """The first Asana ticket the prompt links to, as `asana task get` gives it, or
    {} when it links to none or Asana cannot be read."""
    for url in asana_urls(prompt):
        try:
            ref = st.asana(["ref", "parse", url], cwd=main_root)
            if ref:
                return st.asana(["task", "get", str(ref).strip()], cwd=main_root) or {}
        except st.Failure:
            continue
    return {}


def file_entry(path, rel):
    """A file given with the prompt, as the ask lists it: an absolute path, whether
    it is an image, and a small text file's text. A folder is listed, never pasted
    in: its path, how many files it holds, and its README.md when it has a short
    one, so the lead reads its files through explorers."""
    if os.path.isdir(path):
        count = sum(len(names) for _, _, names in os.walk(path))
        entry = {"path": path, "folder": count}
        readme = os.path.join(path, "README.md")
        try:
            if os.path.isfile(readme) and os.path.getsize(readme) <= FOLDER_README_MAX:
                with open(readme) as f:
                    entry["readme"] = f.read()
        except (OSError, UnicodeDecodeError):
            pass
        return entry
    entry = {"path": path, "is_image": rel.lower().endswith(IMAGE_EXTS)}
    try:
        if not entry["is_image"] and os.path.getsize(path) <= st.INLINE_ATTACHMENT_MAX_BYTES:
            with open(path, "rb") as f:
                entry["inline"] = f.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        pass
    return entry


def create_part(main_root, parent, part, index, built):
    """Write the goal for one part of `parent`, unless it is written already.
    Returns its id; nothing runs yet."""
    gid = part_id(parent["id"], part["name"])
    goal = Goal(main_root, gid)
    if os.path.exists(goal.state.path(GOAL_FILE)):
        return gid
    technical_plan = Goal(main_root, parent["id"]).state.path(TECHNICAL_FILE)
    goal.state.ensure()
    goal.update(id=gid, parent=parent["id"], part=part["name"], part_index=index,
                depth=parent.get("depth", 0) + 1, key=parent.get("key"),
                name="part: %s" % part["name"], base=parent["branch"],
                ask=part_ask(parent, part, built, technical_plan if os.path.exists(
                    technical_plan) else None), threshold=parent.get("threshold"),
                model=parent.get("model"), subagent_model=parent.get("subagent_model"),
                check_model=parent.get("check_model"), check_effort=parent.get("check_effort"),
                fence=parent.get("fence"), created=time.time(), status="new", round=0,
                phase="planning", flow=parent.get("flow"), gate=parent.get("gate"))
    return gid


def launch(main_root, gid):
    """Run a goal in its own session, so closing the TUI leaves it going. Returns
    its pid."""
    goal = Goal(main_root, gid)
    if goal.runner_alive():
        return goal.read().get("pid")
    repos.add(main_root)
    logfile = open(goal.log, "a")
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run", gid,
                             "--repo", main_root], cwd=main_root, stdin=subprocess.DEVNULL,
                            stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
    logfile.close()
    _CHILDREN.append(proc)
    goal.update(pid=proc.pid, status="setting-up", reason=None)
    return proc.pid


def list_goals(main_root):
    """Every goal in the repo not cleared from the list, newest first, with whether
    its process still runs, where its log is, and what it is asking you, if anything."""
    for proc in list(_CHILDREN):
        if proc.poll() is not None:
            _CHILDREN.remove(proc)
    root = os.path.join(main_root, st.CORTEX_DIRNAME, st.STATE_DIRNAME)
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if not name.startswith("goal-"):
            continue
        goal = Goal(main_root, name)
        data = goal.read()
        if data and not data.get("cleared"):
            data.setdefault("id", name)
            data["alive"] = bool(data.get("pid")) and st._pid_alive(data["pid"])
            data["log"] = goal.log
            data["awaiting"] = goal.state.read("awaiting.json")
            out.append(data)
    # Each goal, newest first, with its parts after it in their order.
    tops = sorted((g for g in out if not g.get("parent")), key=lambda g: -(g.get("created") or 0))
    ordered = []
    for top in tops:
        ordered.append(top)
        ordered += sorted((g for g in out if g.get("parent") == top["id"]),
                          key=lambda g: g.get("part_index") or 0)
    return ordered


MARKED = "marked"


def mark_done(main_root, gid):
    """You mark a goal done by hand: it and its unfinished parts are stopped and
    stay done, whatever their runners write as they end. Its branch and PR stay
    as they are."""
    for one in goal_and_parts(main_root, gid):
        data = one.read()
        if not data or (data.get("parent") and data.get("status") == "done"):
            continue
        one.update(status="done", phase=MARKED, doing="marked done by you", marked_done=True)
        pid = data.get("pid")
        if pid and st._pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass


def goal_and_parts(main_root, gid):
    """A goal and its parts, each as a Goal, the parts first; cleared ones too."""
    root = os.path.join(main_root, st.CORTEX_DIRNAME, st.STATE_DIRNAME)
    names = sorted(n for n in os.listdir(root) if n.startswith(gid + "--")) if os.path.isdir(root) else []
    return [Goal(main_root, n) for n in names] + [Goal(main_root, gid)]


def clean_up(main_root, gid, keep_branch=False):
    """Remove what an ended goal or a merged part leaves here: its worktrees, its
    parts' and its tasks' worktrees, and their local branches; its own branch too,
    unless `keep_branch`. Returns the worktrees and branches removed."""
    goals = [Goal(main_root, gid)] if (Goal(main_root, gid).read() or {}).get("parent") \
        else goal_and_parts(main_root, gid)
    data = Goal(main_root, gid).read() or {}
    branch, removed = data.get("branch"), []
    # A part marked done by hand was never merged: its work stays.
    marked = [d for d in (g.read() or {} for g in goals[:-1]) if d.get("phase") == MARKED] \
        if not data.get("parent") else []
    kept = [d["branch"] for d in marked if d.get("branch")]
    homes = [d["worktree"] for d in marked if d.get("worktree")]
    goals = [g for g in goals if (g.read() or {}).get("branch") not in kept]
    with st.repo_lock(main_root):
        for g in goals:
            home = (g.read() or {}).get("worktree")
            for path in ([home] + sorted(glob.glob(glob.escape(home) + "--*"))) if home else []:
                if any(path == h or path.startswith(h + "--") for h in homes):
                    continue
                if os.path.isdir(path):
                    st.git(["worktree", "remove", "--force", path], cwd=main_root, check=False)
                    removed.append(path)
        st.git(["worktree", "prune"], cwd=main_root, check=False)
        if branch:
            _, out, _ = st.git(["for-each-ref", "--format=%(refname:short)",
                                "refs/heads/%s--*" % branch], cwd=main_root, check=False)
            for name in out.split() + ([] if keep_branch else [branch]):
                if any(name == k or name.startswith(k + "--") for k in kept):
                    continue
                if st.git(["branch", "-D", name], cwd=main_root, check=False)[0] == 0:
                    removed.append(name)
    return removed


def sweep(main_root):
    """Clean up after every goal here that ended, and every part that is merged.
    A goal whose PR was closed without a merge keeps its branch; one marked done by
    hand keeps everything. Returns what was removed."""
    root = os.path.join(main_root, st.CORTEX_DIRNAME, st.STATE_DIRNAME)
    removed = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        g = Goal(main_root, name)
        data = g.read() or {}
        if g.runner_alive() or data.get("status") != "done":
            continue
        if data.get("parent") and data.get("phase") != MARKED or data.get("phase") in ("merged", "closed"):
            removed += clean_up(main_root, name, keep_branch=data.get("phase") == "closed")
    return removed


# Tools a discussion may not use: it changes nothing but scratch files in a temp
# folder, which a hook holds it to.
DISCUSS_DENY = ["AskUserQuestion", "mcp__claude_ai_Asana__add_comment",
                "mcp__claude_ai_Asana__create_tasks", "mcp__claude_ai_Asana__update_tasks",
                "mcp__claude_ai_Asana__delete_task", "mcp__claude_ai_Asana__create_project",
                "mcp__claude_ai_Asana__update_project",
                "mcp__claude_ai_Asana__create_project_status_update",
                "mcp__claude_ai_Asana__create_task_from_template",
                "mcp__claude_ai_Asana__create_project_from_template"]

DISCUSS = """You help the person who runs a conductor goal talk it through. A conductor goal
is an autonomous run that implements what the person asked for. Other agents analyse
it, plan it, review the plan and build it. You change nothing in the repository, the
goal's files or Asana.

How you talk:

- Answer what the person asks, and only that. Do not add opinions, assessments,
  risks, recommendations or scope advice they did not ask for: the goal's own
  agents do that work.
- Give your view only when they ask for it, on what they ask about.
- Do not ask them questions, and do not offer menus of topics. Ask only when you
  cannot understand what they want.
- Be short. State facts from the files and the code, and say where they come from.

The goal's files, as they were when this session started, are below. Read them
again from their paths when the person asks for the latest.

- `journal.md` is the lead's journal: its references, decisions, acceptance
  criteria and plan.
- `awaiting.json`, when it exists, holds what the goal waits on the person for.
- `goal.log` is what the runner did.

Of a split goal's parts, only their state and the paths of their files are below.
Read a part's journal, technical plan or log when the talk needs it, not before.

The goal's branch is checked out in `%s`. Read its code as you need.

You may write scratch files in the temp folder `%s` and run them: a script that
reads the code or the logs, a draft, a diagram, a comparison. Do it when the person
asks for it, or when it answers their question better than reading does. Change no
other file. Do not run commands that write elsewhere, such as `git commit`,
`git checkout`, `git stash`, or any write to Asana; a hook refuses them. Do not answer the goal's
questions or approve its plan. When the talk changes an answer, tell the person
to give it in conductor: its web page, the TUI or `cond`.

%s
"""

DISCUSS_FILES = ("journal.md", "awaiting.json", "goal.log")
DISCUSS_PART_FILES = ("journal.md", "technical-plan.md", "awaiting.json", "goal.log")
DISCUSS_LOG_LINES = 200
DISCUSS_OPEN = ("In at most eight short lines, tell me what you have loaded: the goal, its state, "
                "what it waits on me for, and each part with its state. Then wait for my question.")


def discuss_files(goals):
    """The goal's own files, and each part's state with the paths of its files, as
    text for the session's prompt. A part's files are read only when the talk needs
    them: a split goal's files in full are too much to send on every turn."""
    top, parts = goals[0], goals[1:]
    out = []
    for name in DISCUSS_FILES:
        path = top.state.path(name)
        if not os.path.exists(path):
            continue
        with open(path, errors="replace") as f:
            text = f.read()
        if name == "goal.log":
            lines = text.splitlines()
            text = "\n".join(lines[-DISCUSS_LOG_LINES:])
            if len(lines) > DISCUSS_LOG_LINES:
                name = "goal.log, its last %d lines" % DISCUSS_LOG_LINES
        out.append("## The goal: %s (`%s`)\n\n````\n%s\n````" % (name, path, text.strip()))
    if parts:
        lines = []
        for g in parts:
            data = g.read()
            state = "%s, %s, round %s" % (data.get("status") or "?", data.get("phase") or "?",
                                          data.get("round") or 0)
            if os.path.exists(g.state.path("awaiting.json")):
                state += ", waits on the person"
            files = ", ".join("`%s`" % g.state.path(n) for n in DISCUSS_PART_FILES
                              if os.path.exists(g.state.path(n)))
            lines.append("- **%s**: %s. Files: %s" % (data.get("part") or g.id, state, files or "none yet"))
        split = top.state.path("parts.json")
        out.append("## The parts%s\n\n%s" % (" (the split: `%s`)" % split if os.path.exists(split) else "",
                                               "\n".join(lines)))
    return "\n\n".join(out) or "Nothing is written yet."


def pick_goal(main_root, ask=input, say=print):
    """The goal to discuss, picked from the repo's goals by number; the only one
    without asking. None when there is none, or nothing is picked."""
    goals = [g for g in list_goals(main_root) if not g.get("parent") and g.get("status") != "done"]
    if not goals:
        say("there are no goals in this repo that are not done")
        return None
    if len(goals) == 1:
        say("discussing %s" % goals[0]["id"])
        return goals[0]["id"]
    width = max(len(g.get("key") or "") for g in goals)
    for i, g in enumerate(goals, 1):
        state = "waiting on you" if g.get("awaiting") else g.get("status") or "?"
        say("%2d  %-*s  %s — %s" % (i, width, g.get("key") or "", g.get("name") or g["id"], state))
    try:
        pick = ask("which goal? ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if pick.isdigit() and 1 <= int(pick) <= len(goals):
        return goals[int(pick) - 1]["id"]
    return next((g["id"] for g in goals if pick and pick in (g["id"], g.get("key"))), None)


def discuss_command(main_root, gid):
    """The argv and the folder of a Claude session about a goal and its
    parts, for the person to talk it through. The goal's files are in its prompt,
    so it starts knowing them. It opens by saying what it has loaded, so the person
    sees it, and then waits for them."""
    goals = goal_and_parts(main_root, gid)
    top = goals[-1]
    worktree = top.read().get("worktree")
    cwd = worktree if worktree and os.path.isdir(worktree) else main_root
    dirs = []
    for g in [top] + goals[:-1]:
        dirs.append(g.state.dir)
        tree = g.read().get("worktree")
        if g is not top and tree and os.path.isdir(tree):
            dirs.append(tree)
    scratch = os.path.join(os.path.realpath(tempfile.gettempdir()), "conductor-discuss-%s" % gid)
    os.makedirs(scratch, exist_ok=True)
    # Edits are accepted without a prompt, and the hook refuses any outside the temp
    # folders. A shell command still asks the person first.
    argv = ["claude", "--permission-mode", "acceptEdits"]
    for d in dirs + [scratch]:
        argv += ["--add-dir", d]
    guard = " ".join(shlex.quote(a) for a in (sys.executable, HOOK, "discuss"))
    argv += ["--settings", json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
         "hooks": [{"type": "command", "command": guard}]}]}})]
    argv += ["--append-system-prompt", DISCUSS % (cwd, scratch, discuss_files([top] + goals[:-1])),
             DISCUSS_OPEN]
    argv += ["--disallowedTools"] + DISCUSS_DENY
    return argv, cwd


def undo_plan(main_root, gid):
    """What undoing a goal does, a line a step, before anything is done."""
    goals = goal_and_parts(main_root, gid)
    data = goals[-1].read()
    steps = []
    if any(g.read().get("pid") and st._pid_alive(g.read()["pid"]) for g in goals):
        steps.append("stop the goal and its parts")
    steps.append("close its PR and delete its branch, on GitHub and here" if data.get("pr_url")
                 else "delete its branch %s" % (data.get("branch") or "?"))
    if len(goals) > 1:
        steps.append("delete its %s" % ("part's branch" if len(goals) == 2 else
                                         "%d parts' branches" % (len(goals) - 1)))
    steps.append("remove its worktrees and saved state")
    return steps


def undo(main_root, gid, wait=20):
    """Take a goal's work back out, all of it: its runs, its PR and branches, its
    worktrees and state. Returns what was done."""
    goals = goal_and_parts(main_root, gid)
    done = []
    pids = [g.read().get("pid") for g in goals]
    for pid in [p for p in pids if p and st._pid_alive(p)]:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + wait
    while any(p and st._pid_alive(p) for p in pids) and time.time() < deadline:
        time.sleep(1)
    if any(p and st._pid_alive(p) for p in pids):
        raise st.Failure("the goal did not stop within %d seconds — try again" % wait)
    if any(pids):
        done.append("stopped")
    data = goals[-1].read()
    pr, branch = data.get("pr_url"), data.get("branch")
    # The worktrees go first: a branch a worktree still uses cannot be deleted.
    with st.repo_lock(main_root):
        for g in goals:
            d = g.read()
            if d.get("worktree") and os.path.isdir(d["worktree"]):
                st.git(["worktree", "remove", "--force", d["worktree"]], cwd=main_root, check=False)
            if d.get("branch"):
                st.git(["branch", "-D", d["branch"]], cwd=main_root, check=False)
        st.git(["worktree", "prune"], cwd=main_root, check=False)
    done.append("worktrees and branches removed here")
    if pr:
        code, _, err = st.run(["gh", "pr", "close", pr, "--comment",
                               st.mark("Undone from conductor — this goal's work is discarded.")],
                              cwd=main_root, check=False)
        done.append("PR closed" if code == 0 else "PR not closed: %s" % err.strip())
    if branch:
        code, _, _ = st.run(["git", "push", "origin", "--delete", branch], cwd=main_root, check=False)
        done.append("branch deleted on GitHub" if code == 0 else "no branch on GitHub to delete")
    import shutil
    for g in goals:
        shutil.rmtree(g.state.dir, ignore_errors=True)
    done.append("saved state removed")
    return done


# --- the run -----------------------------------------------------------------

class Stopped(Exception):
    pass


class Runner(object):
    def __init__(self, main_root, gid):
        self.main_root = main_root
        self.goal = Goal(main_root, gid)
        self.data = self.goal.read()
        if not self.data:
            st.die("no goal %s in %s" % (gid, main_root), escalate=False)
        self.child = None
        self.children = []
        self.cut_off = None
        signal.signal(signal.SIGTERM, self.on_term)

    def step(self, text):
        """A step of the run: in the log, and as what the goal is doing, so the TUI
        never shows an earlier step as the current one."""
        st.step(text)
        self.set(doing=text[:1].lower() + text[1:])

    def on_term(self, *_):
        for child in [self.child] + list(self.children):
            if child and child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except OSError:
                    pass
        for part in self.data.get("parts") or []:
            pid = (Goal(self.main_root, part["id"]).read() or {}).get("pid")
            if pid and st._pid_alive(pid):
                try:
                    os.killpg(pid, signal.SIGTERM)
                except OSError:
                    pass
        raise Stopped()

    def set(self, **fields):
        self.data = self.goal.update(**fields)

    def flow2(self):
        return (self.data.get("flow") or 0) >= FLOW

    def waits_for_person(self):
        """Whether this goal's plan waits for the person's approval."""
        gate = self.data.get("gate") or DEFAULT_GATE
        return gate == "wait" or (gate == "top" and not self.data.get("parent"))

    def split_now(self):
        return self.data.get("depth", 0) < MAX_DEPTH and os.path.exists(
            self.goal.state.path(PARTS_FILE))

    def written_parts(self):
        with open(self.goal.state.path(PARTS_FILE)) as f:
            return read_parts(f.read())

    # setup

    def read_ask(self):
        """The ask: the prompt, its files, and each ticket it links to as it is now.
        Read once, when the goal starts. A goal made from a ticket before goals took
        a prompt has the ticket's URL for its prompt."""
        self.step("Reading the ask")
        prompt = self.data.get("prompt") or self.data.get("url") or ""
        files = [file_entry(self.goal.state.path(rel), rel) for rel in self.data.get("files") or []]
        tickets = [t for t in (self.read_ticket(url) for url in asana_urls(prompt)) if t]
        st.info("%d file(s) · %d ticket(s)" % (len(files), len(tickets)))
        self.set(ask=ask_from_prompt(prompt, files, tickets))

    def read_ticket(self, url):
        """One ticket the prompt links to, as the ask shows it, or None when it is not
        a task or cannot be read."""
        try:
            ref = st.asana(["ref", "parse", url], cwd=self.main_root)
            if not ref:
                return None
            ref = str(ref).strip()
            task = st.asana(["task", "get", ref], cwd=self.main_root)
            subtasks = [dict(st.asana(["task", "get", t["ref"]], cwd=self.main_root) or {},
                             completed=t.get("completed"))
                        for t in st.asana(["task", "subtasks", ref], cwd=self.main_root) or []
                        if not t.get("completed")]
            comments = st.asana(["comment", "list", ref], cwd=self.main_root) or []
            attachments = []
            for att in st.asana(["task", "attachments", ref], cwd=self.main_root) or []:
                entry = st.download_attachment(att, self.goal.state.path("attachments"))
                if entry:
                    attachments.append(dict(entry, path=self.goal.state.path(entry["path"])))
        except st.Failure as e:
            st.warn("could not read %s: %s" % (url, e))
            return None
        st.info("%s: %d subtask(s) · %d comment(s) · %d attachment(s)"
                % (st.task_key(task), len(subtasks), len(comments), len(attachments)))
        return ask_from_ticket(task, url, subtasks, comments, attachments)

    def pr_ask(self):
        """The ask, as the PR's description opens: the prompt, or the ticket of a goal
        made from one before goals took a prompt."""
        prompt = (self.data.get("prompt") or self.data.get("url") or "").strip()
        if len(prompt) > PR_ASK_MAX:
            prompt = prompt[:PR_ASK_MAX].rstrip() + "…"
        return "## Ask\n\n%s" % prompt

    def set_up(self):
        if not self.data.get("ask"):
            os.makedirs(self.goal.state.path("attachments"), exist_ok=True)
            self.read_ask()
        if self.data.get("worktree") and os.path.isdir(self.data["worktree"]):
            return
        self.step("Setting up")
        if not self.data.get("parent"):
            self.name_it()
        if self.data.get("parent"):
            parent = Goal(self.main_root, self.data["parent"]).read()
            branch = "%s--%s" % (parent["branch"], st.slugify(self.data["part"], max_words=4))
            worktree = st.worktree_path(self.main_root, self.goal.id)
            with st.repo_lock(self.main_root):
                st.git(["worktree", "add", worktree, "-b", branch, parent["branch"]],
                       cwd=self.main_root)
            st.info("created %s off %s in %s" % (branch, parent["branch"], worktree))
            self.set(branch=branch, worktree=worktree, parent_worktree=parent["worktree"])
            return
        key, name = self.data.get("key"), self.data["name"]
        base = st.resolve_base(self.main_root, self.data.get("base"))
        branch = "%s/goal-%s" % (key, st.slugify(name)) if key else "goal/%s" % st.slugify(name)
        worktree = st.worktree_path(self.main_root, self.goal.id)
        with st.repo_lock(self.main_root):
            st.git(["fetch", "origin"], cwd=self.main_root, check=False)
            st.git(["worktree", "add", worktree, "-b", branch, base], cwd=self.main_root)
        st.git(["commit", "--allow-empty", "-m", "%s :: start the goal" % (key or "goal")],
               cwd=worktree)
        st.git(["push", "-u", "origin", branch], cwd=worktree)
        st.info("created %s off %s in %s" % (branch, base, worktree))
        pr_url, error = st.create_draft_pr("%s :: %s" % (key, name) if key else name,
                                           self.pr_ask(), base, branch, worktree)
        if pr_url:
            st.info("draft PR: %s" % pr_url)
        else:
            st.warn("could not open the draft PR: %s" % error)
        self.set(base=base.replace("origin/", "", 1), branch=branch, worktree=worktree,
                 pr_url=pr_url)

    def name_it(self):
        """Haiku names the goal from its ask, before its branch and PR take the name.
        On OpenCode, or when Haiku gives none, the goal keeps the name it has."""
        if oc.is_opencode(self.data.get("model") or DEFAULT_MODEL):
            return
        name = model_name(self.data.get("ask") or self.data.get("prompt") or "", self.main_root)
        if name:
            st.info("named: %s" % name)
            self.set(name=name)

    # usage

    def setup(self, key):
        """A value from the TUI's Setup tab, read each time so a change reaches a
        goal already running; None when the tab has none saved."""
        try:
            with open(os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "control.json")) as f:
                return (json.load(f).get("models") or {}).get(key)
        except (IOError, OSError, ValueError, AttributeError):
            return None

    def check_model(self):
        """The checker's model: the settings' now, for what goals run on, else the one
        the goal started with."""
        try:
            with open(os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "control.json")) as f:
                model = active_models(json.load(f)).get("check")
        except (IOError, OSError, ValueError, AttributeError):
            model = None
        return model or self.data.get("check_model") or DEFAULT_CHECK_MODEL

    def check_effort(self):
        """The checker's effort: what the TUI's Setup tab shows, its saved value or
        else the default, read each time so it reaches a goal already running. Not
        the goal's own: the tab must be true for every goal it lists."""
        try:
            with open(os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "control.json")) as f:
                value = (json.load(f).get("models") or {}).get("check_effort")
        except (IOError, OSError, ValueError, AttributeError):
            value = None
        return value or DEFAULT_CHECK_EFFORT

    def effort(self, role):
        """The lead's or the sub-agents' effort from the settings, read each time;
        None runs the model at its own default."""
        return self.setup("%s_effort" % role) or None

    def threshold(self):
        """The usage limit to pause at: the TUI's Setup tab's, read each time so a
        change reaches a goal already running, else the goal's own."""
        try:
            with open(os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "control.json")) as f:
                value = json.load(f).get("usage_threshold")
        except (IOError, OSError, ValueError):
            value = None
        return value if isinstance(value, int) else self.data.get("threshold", DEFAULT_THRESHOLD)

    def uses_claude(self):
        """Whether any of the goal's models runs on the Claude subscription, whose
        usage limits it pauses for. Models on API keys have no such limits."""
        return any(not oc.is_opencode(m) for m in (
            self.data.get("model") or DEFAULT_MODEL, self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL,
            self.check_model()))

    def providers(self):
        """The custom OpenCode providers, from the repo's settings, read each time."""
        try:
            with open(os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "control.json")) as f:
                return json.load(f).get("providers") or []
        except (IOError, OSError, ValueError, AttributeError):
            return []

    def opencode_run(self, model, prompt, session, cwd, **rules):
        """Start one OpenCode run in `cwd`. Returns the process."""
        conf = oc.config(self.goal.state.dir, self.providers(),
                         self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL, **rules)
        return subprocess.Popen(oc.command(model, prompt, session), cwd=cwd,
                                env=oc.environment(os.environ, conf), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    def call_opencode(self, prompt, session, label, model):
        """One OpenCode call, as `call` makes a Claude one. No usage limit applies."""
        building = label == "lead" and self.data.get("phase") == "building"
        st.info("%s: calling opencode (%s)" % (label, model))
        started = time.time()
        self.child = self.opencode_run(model, prompt, session, self.data["worktree"],
                                       readonly=label == "ci-fix", lead_building=building,
                                       subagents=not building)
        out, err = self.child.communicate()
        code, self.child = self.child.returncode, None
        text, telemetry = oc.parse_events(out.decode("utf-8", "replace"))
        self.record_usage(label, model, None, session, started, telemetry)
        if telemetry.get("denied"):
            st.info("%s: refused %s" % (label, ", ".join(sorted(set(telemetry["denied"])))))
        if telemetry.get("ok") is False:
            return None, None, (telemetry.get("error") or err.decode("utf-8", "replace").strip()
                                or "opencode exited %d" % code)
        st.info("%s: %s steps" % (label, telemetry.get("turns") or "?"))
        return extract_last_json_block(text), telemetry.get("stop_reason"), None

    def record_usage(self, label, model, effort, session, started, telemetry, name=None):
        """Note an OpenCode call's tokens and cost, which its events report; the
        runs its sub-agents made are not in them."""
        usage = telemetry.get("usage")
        if not usage:
            return
        at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.goal.state.write(st.USAGE_FILE, st.add_usage(
            self.goal.state.read(st.USAGE_FILE), usage, label, model, at))
        calls = self.goal.state.read(CALLS_FILE) or []
        rounds = self.data.get("round") if label == "lead" else len(
            [c for c in calls if c["label"] == label]) + 1
        tokens = {k: usage.get(k) or 0 for k in ("input", "output", "cache_read", "cache_write")}
        cost = usage.get("cost_usd") or None
        calls.append(dict({"v": 2, "label": label, "round": rounds, "model": model, "effort": effort,
                           "started": started, "session": session, "cost": cost,
                           "main": {"model": model, "tokens": tokens, "seconds": time.time() - started,
                                    "cost": cost}, "subagents": []},
                          **({"name": name} if name else {})))
        self.goal.state.write(CALLS_FILE, calls)
        _, total = write_report(self.goal)
        self.set(cost=total)

    def usage(self):
        if not self.uses_claude():
            return []
        code, out, _ = st.run(["claude", "-p", "/usage", "--output-format", "json"],
                              cwd=self.main_root, check=False)
        text = out
        try:
            text = json.loads(out).get("result") or ""
        except (ValueError, AttributeError):
            pass
        limits = parse_usage(text, time.time())
        if limits:
            self.set(limits=limits, limits_at=time.time())
        return limits

    def wait_for_usage(self):
        """Pause while the subscription is at or over the threshold."""
        while True:
            worst = over_threshold(self.usage(), self.threshold())
            if not worst:
                if self.data.get("status") == "paused":
                    st.info("usage is back under %d%% — going on" % self.threshold())
                    before = self.data.get("before_pause") or {}
                    self.set(status=before.get("status") or "working",
                             doing=before.get("doing") or "going on", before_pause=None)
                return
            until = worst["resets_at"] or time.time() + PAUSE_CHECK
            what = "%s at %d%%" % (worst["name"], worst["used"])
            if self.data.get("status") != "paused":
                self.set(before_pause={"status": self.data.get("status"),
                                       "doing": self.data.get("doing")})
                self.step("Paused — %s" % what)
                st.info("resumes at %s" % time.strftime("%a %H:%M", time.localtime(until)))
                self.sound_pause(what, until)
            self.set(status="paused", doing="paused — %s, until %s"
                     % (what, time.strftime("%a %H:%M", time.localtime(until))))
            time.sleep(max(60, min(until - time.time() + 60, PAUSE_CHECK)))

    def clean_up(self, keep_branch=False):
        """The goal ended, or the part is merged: its worktrees and branches go."""
        removed = clean_up(self.main_root, self.goal.id, keep_branch)
        if removed:
            st.info("removed %d worktree(s) and branch(es) here" % len(removed))

    def prune_task_branches(self):
        """Drop the branches of tasks kept after a conflict, once the goal's branch
        holds their work."""
        worktree, branch = self.data["worktree"], self.data["branch"]
        _, out, _ = st.git(["for-each-ref", "--merged", "HEAD", "--format=%(refname:short)",
                            "refs/heads/%s--r[0-9]*" % branch], cwd=worktree, check=False)
        for name in out.split():
            st.git(["branch", "-D", name], cwd=worktree, check=False)

    def sound_pause(self, what, until):
        """Tell the person a pause started: once for all the goals that pause together."""
        mark = os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "paused-sound")
        try:
            if time.time() - os.path.getmtime(mark) < PAUSE_SOUND_EVERY:
                return
        except OSError:
            pass
        try:
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            with open(mark, "w") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        notify("Goals paused", "%s, until %s" % (what, time.strftime(
            "%a %H:%M", time.localtime(until))), SOUNDS["paused"], page_url(self.main_root))

    # agent calls

    def call(self, prompt, session, resume, label, model=None, effort=None):
        """One `claude -p` call. Returns (structured, stop_reason, error). A call
        cut off because the usage crossed the threshold returns stop_reason
        "usage"; its session carries on afterwards."""
        model = model or self.data["model"]
        if oc.is_opencode(model):
            return self.call_opencode(prompt, session, label, model)
        flag = self.goal.state.path(WIND_FILE)
        if os.path.exists(flag):
            os.remove(flag)
        # Bypass is not used: a repo may turn it off. Auto mode, with the goal's usual
        # work allowed: reading, edits in its worktree and state, sub-agents, the web.
        mode, allow = unattended(model, [self.data["worktree"], self.goal.state.dir],
                                 ["Agent", "Task"])
        self.goal.state.write(SETTINGS_FILE, hook_settings(flag, short_model(
            self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL), self.data.get("fence") or (),
            allow, delegate=self.data["worktree"] if label == "lead" and self.data.get(
                "phase") == "building" else None, lead=label == "lead",
            # The CI fixer judges and briefs; its sub-agents, on the sub-agent model,
            # make the changes.
            readonly=self.data["worktree"] if label == "ci-fix" else None,
            force_subagent=label == "ci-fix", notes=self.goal.state.dir if label == "lead" else None))
        cmd = ["claude", "-p", "--output-format", "json", "--model", model,
               "--permission-mode", mode, "--max-turns", str(MAX_TURNS),
               "--add-dir", self.goal.state.dir, "--settings", self.goal.state.path(SETTINGS_FILE)]
        cmd += ["--effort", effort] if effort else []
        cmd += NO_MCP
        if label == "lead" and self.data.get("phase") == "building":
            # In the build the runner starts the agents: the lead hands it their tasks.
            cmd += ["--disallowedTools", "Agent,Task," + NO_WAITING]
        else:
            cmd += ["--disallowedTools", NO_WAITING]
        cmd += ["--resume", session] if resume else ["--session-id", session]
        st.info("%s: calling claude%s" % (label, " (continuing)" if resume else ""))
        started = time.time()
        env = dict(os.environ, CLAUDE_CODE_SUBAGENT_MODEL=self.data.get(
            "subagent_model") or DEFAULT_SUBAGENT_MODEL)
        self.child = subprocess.Popen(cmd + [prompt], cwd=self.data["worktree"], env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, start_new_session=True)
        winding = False
        while True:
            try:
                out, err = self.child.communicate(timeout=WIND_CHECK if winding else USAGE_CHECK)
                break
            except subprocess.TimeoutExpired:
                limits = self.usage()
                threshold = self.threshold()
                hard = over_threshold(limits, threshold + HARD_MARGIN)
                if hard:
                    st.warn("%s at %d%% — cutting the call off; it carries on later"
                            % (hard["name"], hard["used"]))
                    self.cut_off = {"at": time.time(), "session": session, "since": started}
                    os.killpg(self.child.pid, signal.SIGTERM)
                    self.child.communicate()
                    self.child = None
                    self.record_call(label, model, effort, session, started)
                    return None, "usage", None
                worst = over_threshold(limits, threshold)
                if worst and not winding:
                    st.warn("%s at %d%% — winding the call down: no new work, then it stops"
                            % (worst["name"], worst["used"]))
                    with open(flag, "w") as f:
                        f.write("%s at %d%%\n" % (worst["name"], worst["used"]))
                    winding = True
                    self.set(doing="winding down — %s at %d%%" % (worst["name"], worst["used"]))
        code, self.child = self.child.returncode, None
        if winding:
            st.info("%s: wound down" % label)
        self.record_call(label, model, effort, session, started, out)
        text, telemetry = parse_envelope(out.decode("utf-8", "replace"))
        usage = telemetry.get("usage")
        if usage:
            at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.goal.state.write(st.USAGE_FILE, st.add_usage(
                self.goal.state.read(st.USAGE_FILE), usage, label, model, at))
        if telemetry.get("ok") is False or not out.strip():
            return None, None, (telemetry.get("error") or err.decode("utf-8", "replace").strip()
                                or "claude exited %d" % code)
        st.info("%s: %s turns" % (label, telemetry.get("turns") or "?"))
        return extract_last_json_block(text), telemetry.get("stop_reason"), None

    def record_call(self, label, model, effort, session, started, out=b"", name=None):
        """Note what a call cost, by agent, and rewrite the goal's usage report."""
        try:
            envelope = json.loads(out.decode("utf-8", "replace")) if out.strip() else {}
        except ValueError:
            envelope = {}
        main, agents = read_call(session, started - 1, envelope.get("modelUsage"))
        if not main:
            return
        calls = self.goal.state.read(CALLS_FILE) or []
        rounds = self.data.get("round") if label == "lead" else len(
            [c for c in calls if c["label"] == label]) + 1
        entries = [main] + agents
        cost = (sum(e["cost"] for e in entries)
                if all(e.get("cost") is not None for e in entries) else None)
        calls.append(dict({"v": 2, "label": label, "round": rounds, "model": model, "effort": effort,
                           "started": started, "session": session, "cost": cost,
                           "main": dict(main, seconds=time.time() - started), "subagents": agents},
                          **({"name": name} if name else {})))
        self.goal.state.write(CALLS_FILE, calls)
        save_rates(learned_rates(normalise(calls)))
        _, total = write_report(self.goal)
        self.set(cost=total)

    def cut_off_notice(self):
        """The prompt after a call was cut off: which sub-agents were stopped and
        which files were left uncommitted."""
        cut = getattr(self, "cut_off", None) or {"at": time.time()}
        agents = unfinished_subagents(cut.get("session"), cut.get("since", 0)) if cut.get("session") else []
        _, status, _ = st.git(["status", "--porcelain"], cwd=self.data["worktree"], check=False)
        dirty = [line[3:] for line in status.splitlines() if len(line) > 3]
        self.cut_off = None
        return cut_off_prompt(cut["at"], agents, dirty)

    def lead(self, prompt):
        """Call the lead on its session, through failures and pauses. Returns
        (report, block)."""
        failures = 0
        while True:
            self.wait_for_usage()
            session = self.data.get("session")
            resume = bool(session) and self.data.get("session_used")
            if not session:
                session = str(uuid.uuid4())
                self.set(session=session)
            self.set(status="working", doing="round %d" % self.data["round"])
            note = nt.take(self.goal.state.dir)
            if note:
                st.info("your note goes to the lead")
                prompt += "\n\n" + note
            block, stop, error = self.call(prompt, session, resume, "lead",
                                           effort=self.effort("lead"))
            self.set(session_used=True)
            if error:
                pause = st.limit_pause(error, time.time())
                if pause:
                    st.wait_out_limit(self.goal.state, "lead", *pause)
                    continue
                if resume and failures == 0 and re.search(r"session|conversation", error, re.I):
                    st.warn("could not continue the session (%s) — starting a new one" % error)
                    self.set(session=None, session_used=False)
                    prompt = self.first_prompt() + "\n\n" + CONTINUE
                    failures += 1
                    continue
                failures += 1
                if failures < 3:
                    st.warn("the call failed (%s) — trying again" % error.splitlines()[0][:200])
                    time.sleep(30)
                    continue
                answer = self.ask_problem("The lead agent keeps failing", error)
                prompt, failures = "The person says:\n\n%s\n\n%s" % (answer, CONTINUE), 0
                continue
            if stop == "usage":
                return "cut", {}
            if stop == "max_turns":
                return "progress", {}
            return lead_report(block)

    def judge(self, label, template, read):
        """A call on the checker's model that must give a verdict: `read` makes it of
        the call's block, None when there is none. One cut off by the usage limit,
        or that failed, runs again, so only a real verdict comes back."""
        failures = 0
        while True:
            self.wait_for_usage()
            prompt = render(os.path.join(PROMPTS, template), **self.fields())
            block, stop, error = self.call(prompt, str(uuid.uuid4()), False, label,
                                           self.check_model(), self.check_effort())
            self.cut_off = None
            # Files a check leaves behind — caches, reports — are not changes to the work.
            _, dirty, _ = st.git(["status", "--porcelain", "--untracked-files=no"],
                                 cwd=self.data["worktree"], check=False)
            if dirty:
                st.git(["stash", "push", "-m", "changes the %s made" % label],
                       cwd=self.data["worktree"], check=False)
                st.warn("the %s changed files — they are set aside in `git stash`" % label)
            if stop == "usage":
                st.info("the %s stopped at the usage limit — it runs again" % label)
                continue
            pause = st.limit_pause(error, time.time()) if error else None
            if pause:
                st.wait_out_limit(self.goal.state, label, *pause)
                continue
            verdict = None if error else read(block)
            if verdict is not None:
                return verdict
            failures += 1
            reason = error.splitlines()[0][:200] if error else "it gave no verdict"
            if failures < 3:
                st.warn("the %s did not finish (%s) — running it again" % (label, reason))
                continue
            self.ask_problem("the %s did not finish %d times" % (label, failures), error or reason)
            self.set(status="checking")
            failures = 0

    def check_scope(self, head):
        """What a check covers when the branch was checked before, or its parts were:
        the text for check.md, or "" for a full check."""
        worktree = self.data["worktree"]

        def under(sha):
            return sha and st.git(["merge-base", "--is-ancestor", sha, head], cwd=worktree,
                                  check=False)[0] == 0
        since, merged = self.data.get("checked_head"), self.data.get("parts_merged_head")
        if under(since):
            return recheck_scope(since, self.data.get("last_gaps") or [],
                                 self.data.get("revision_ask"), self.data["base"])
        if under(merged):
            return integration_scope(merged, self.technical_plan(), self.data["base"])
        return ""

    def review(self):
        """The acceptance criteria, reviewed against the references before anything
        is built: (gaps, questions)."""
        self.set(status="checking", doing="reviewing the acceptance criteria")
        self.step("Reviewing the acceptance criteria")
        gaps, questions = self.judge("review", "review.md", review_verdict)
        st.info("review: %d problem(s), %d question(s)" % (len(gaps), len(questions)))
        for gap in gaps:
            st.info("- %s" % gap)
        return gaps, questions

    def check(self):
        """An independent check of the branch against the ask: (done, gaps, questions).
        After an earlier check, only what changed since and that check's gaps."""
        self.set(status="checking", doing="checking the branch against the ask")
        self.step("Checking against the ask")
        _, head, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
        self.scope = self.check_scope(head.strip())
        if self.scope:
            st.info("only what changed since the last check")
        done, gaps, questions = self.judge("check", "check.md", check_verdict)
        self.scope = ""
        self.set(checked_head=head.strip(), last_gaps=[] if done else gaps,
                 revision_ask=None if done else self.data.get("revision_ask"))
        st.info("verdict: %s" % ("done" if done else "%d gap(s), %d question(s)"
                                 % (len(gaps), len(questions))))
        for gap in gaps:
            st.info("- %s" % gap)
        return done, gaps, questions

    def sync(self):
        """Merge into the branch, without pushing, what others merged into it on GitHub,
        such as a PR into the goal's branch, and then its base. Returns None, or what
        the lead is to fix first."""
        worktree, base, branch = self.data["worktree"], self.data["base"], self.data["branch"]
        self.set(status="checking", doing="syncing with %s" % base)
        self.step("Syncing with %s" % base)
        st.git(["fetch", "origin", base, branch], cwd=worktree, check=False)
        theirs = "origin/%s" % branch
        if st.git(["rev-parse", "--verify", "--quiet", theirs], cwd=worktree, check=False)[0] == 0 \
                and st.git(["merge-base", "--is-ancestor", theirs, "HEAD"], cwd=worktree,
                           check=False)[0] != 0:
            st.info("%s has work merged into it on GitHub — merging it in" % branch)
            fix = self.merge_in(theirs)
            if fix:
                return fix
        return self.merge_in("origin/%s" % base)

    def merge_in(self, ref):
        """Merge `ref` into the branch. Returns None, or what the lead is to fix."""
        worktree = self.data["worktree"]
        code, out, err = st.git(["merge", "--no-edit", ref], cwd=worktree, check=False)
        if code != 0:
            _, files, _ = st.git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree,
                                 check=False)
            if not files.strip():
                return ("You reported done, but the runner could not merge `%s` into "
                        "your branch:\n\n```\n%s\n```\n\nCommit or remove what is in the "
                        "way, then report done again." % (ref, (err or out).strip()[-2000:]))
            st.warn("the merge conflicts — back to the lead")
            return conflict_prompt(ref, files.split())
        return None

    def install(self):
        """Install the dependencies the worktree's lockfiles ask for, when one changed
        or its folder is missing. Only while no task runs: the tasks use them too."""
        worktree = self.data["worktree"]
        if not stale_installs(worktree, self.data.get("installed") or {}):
            return
        self.step("Installing dependencies")
        self.set(runner_doing="installing dependencies", runner_since=time.time())
        installed, _ = install_dependencies(worktree, self.data.get("installed") or {},
                                            self.data.get("parent_worktree"))
        self.set(installed=installed, runner_doing=None)

    def left_to_ci(self, failures):
        """The failing steps no change to the branch fixes, as {name: why}: a step
        that cannot find a program it runs, and one that fails on the base too. The
        base's results are kept for each commit of it."""
        left = {f[0]: "needs a program this machine does not have (exit %d)" % f[3]
                for f in failures if f[3] in MISSING_TOOL}
        rest = [f for f in failures if f[0] not in left]
        if not rest:
            return left
        worktree = self.data["worktree"]
        ref = self.data["base"] if self.data.get("parent") else "origin/%s" % self.data["base"]
        _, sha, _ = st.git(["rev-parse", ref], cwd=worktree, check=False)
        sha = sha.strip()
        if not sha:
            return left
        known = self.data.get("base_steps") or {}
        fails = dict(known.get("fails") or {}) if known.get("sha") == sha else {}
        todo = [f for f in rest if f[0] not in fails]
        if todo:
            self.step("Running the failing steps on %s too" % ref)
            fails.update(self.run_on_base(sha, [(f[0], f[1], self.ci_steps[f[0]])
                                                for f in todo if f[0] in self.ci_steps]))
            self.set(base_steps={"sha": sha, "fails": fails})
        left.update({f[0]: "fails on `%s` too" % self.data["base"] for f in rest if fails.get(f[0])})
        return left

    def run_on_base(self, sha, steps):
        """Run steps in a worktree of the base at `sha`, made for it and removed after.
        Returns {name: whether it fails}."""
        worktree = self.data["worktree"]
        path = st.worktree_path(self.main_root, self.goal.id + "--base")
        try:
            with st.repo_lock(self.main_root):
                if os.path.exists(path):
                    st.git(["worktree", "remove", "--force", path], cwd=worktree, check=False)
                st.git(["worktree", "add", "--detach", path, sha], cwd=worktree)
            install_dependencies(path, {}, worktree)
            failed = {f[0] for f in run_ci_steps(steps, path)}
        finally:
            for rel, deps, _ in lockfiles(path) if os.path.isdir(path) else []:
                link = os.path.join(path, os.path.dirname(rel), deps)
                if os.path.islink(link):
                    os.unlink(link)
            with st.repo_lock(self.main_root):
                st.git(["worktree", "remove", "--force", path], cwd=worktree, check=False)
        return {name: name in failed for name, _, _ in steps}

    def local_ci(self):
        """The repo's own CI static checks (`ci-verify`), run here before the check
        and the push, every step past a failure too. What no change to the branch
        fixes is left to CI; a budget goes to the lead; the rest goes to the fixer,
        twice, then to the lead. Returns None when they pass or the repo has none,
        else what the lead fixes."""
        worktree = self.data["worktree"]
        steps = ci_commands(worktree)
        if not steps:
            return None
        self.ci_steps = {name: sub for name, _, sub in steps}
        self.install()
        attempt = 0
        while True:
            self.step("Running CI's static checks here" + (" again" if attempt else ""))
            self.set(status="checking", doing="running CI's static checks here",
                     runner_doing="%d step(s) of CI's static checks" % len(steps),
                     runner_since=time.time())
            failures = run_ci_steps(steps, worktree)
            self.set(runner_doing=None)
            left = self.left_to_ci(failures) if failures else {}
            for name, why in sorted(left.items()):
                st.info("left to CI: %s — %s" % (name, why))
            self.set(ci_left=["`%s` (%s)" % (n, w) for n, w in sorted(left.items())])
            failures = [f for f in failures if f[0] not in left]
            if not failures:
                st.info("CI's static checks pass here%s" % (
                    ", but for %d left to CI" % len(left) if left else ""))
                return None
            st.info("%d of %d step(s) fail" % (len(failures), len(steps)))
            budgets = [f for f in failures if BUDGET.search(f[1])]
            fixable = [f for f in failures if f not in budgets]
            if attempt == CI_FIXES or not fixable:
                st.warn("%d step(s) still fail — over to the lead" % len(failures))
                return ("You reported done. The runner ran each step of CI's static checks "
                        "here, before the push, and these fail:\n\n%s\n\n%sHand over the "
                        "tasks that fix every cause at once, then report done again. Never "
                        "weaken a check." % (ci_failures_text(failures), (
                            "%s check%s a budget. Bring the work back under it, such as by "
                            "splitting a file or loading code only where it is used. Never "
                            "raise the budget.\n\n" % (", ".join("`%s`" % f[0] for f in budgets),
                                                       "s" if len(budgets) == 1 else ""))
                            if budgets else ""))
            attempt += 1
            model = self.data.get("model")
            prompt = local_ci_fix_prompt(self.data["branch"], ci_failures_text(fixable),
                                         [(f[0], f[1], self.ci_steps.get(f[0])) for f in fixable])
            _, before, _ = st.git(["rev-parse", "HEAD"], cwd=worktree, check=False)
            self.step("Fixing CI's static checks (%d/%d) on %s" % (attempt, CI_FIXES, short_model(model)))
            self.wait_for_usage()
            self.set(status="checking", doing="fixing CI's static checks, try %d" % attempt)
            self.call(prompt, str(uuid.uuid4()), False, "ci-fix", model,
                      self.effort("lead"))
            _, after, _ = st.git(["rev-parse", "HEAD"], cwd=worktree, check=False)
            if after == before:
                st.warn("the fixer committed nothing — over to the lead")
                attempt = CI_FIXES

    def gate(self):
        """Sync the branch with its base, push it, mark the PR ready, and wait for
        its CI. Returns (None, None) when CI passes, else ("merge" | "ci", what failed)."""
        worktree = self.data["worktree"]
        fix = self.sync()
        if fix:
            return "merge", fix
        pr_url = self.data.get("pr_url")
        if pr_url and not self.data.get("ready"):
            # Ready before the push: a push to a draft starts a run that skips every
            # job, and the run that marking it ready starts can be for the commit
            # before the push. CI may run only on PRs ready for review.
            st.run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
            self.set(ready=True)
            st.info("PR marked ready for review: %s" % pr_url)
        self.push()
        if not pr_url:
            st.warn("no PR, so no CI to wait for")
            self.set(checks=[])
            return None, None
        return self.wait_for_ci(pr_url)

    def wait_for_ci(self, pr_url):
        self.step("Waiting for CI")
        worktree = self.data["worktree"]
        _, head, _ = st.git(["rev-parse", "HEAD"], cwd=worktree, check=False)
        started, nudged = time.time(), False
        while True:
            _, out, _ = st.run(["gh", "pr", "view", pr_url, "--json",
                                "headRefOid,statusCheckRollup"], cwd=worktree, check=False)
            try:
                view = json.loads(out)
            except ValueError:
                view = {}
            rollup = view.get("statusCheckRollup") or []
            waited = time.time() - started
            if view.get("headRefOid") == head.strip():
                pending, failing = check_states(rollup)
                running = [p for p in pending if p != CI_NOT_STARTED]
                if failing and not running:
                    refused = actions_refused(failing, worktree)
                    if refused:
                        self.ask_problem("GitHub did not run CI: %s" % refused,
                                         "Fix it on GitHub. When you answer, the runner "
                                         "re-runs the failed jobs.")
                        for run_id in failed_runs(failing):
                            st.run(["gh", "run", "rerun", run_id, "--failed"], cwd=worktree,
                                   check=False)
                        self.set(status="checking")
                        started = time.time()
                        time.sleep(CI_CHECK)
                        continue
                    st.warn("CI failed: %s" % ", ".join(n for n, _ in failing))
                    return "ci", failed_ci_prompt(failing, self.ci_excerpts(failing))
                if failing:
                    # A fix pushed now would start CI over while this run still bills:
                    # wait for all of it, and fix every failure at once.
                    self.set(doing="waiting for CI to finish: %s failed, %d still running"
                             % (", ".join(n for n, _ in failing), len(running)))
                    time.sleep(CI_CHECK)
                    continue
                if rollup and not pending:
                    names = sorted({c.get("name") or c.get("context") or "?" for c in rollup})
                    st.info("CI passed: %s" % ", ".join(names))
                    self.set(checks=names)
                    return None, None
                if pending == [CI_NOT_STARTED] and waited >= CI_NUDGE and not nudged:
                    # Every job skipped, as on a draft: draft and ready again starts a run
                    # for the commit as it is now.
                    st.warn("every CI job was skipped — marking the PR draft and ready again")
                    st.run(["gh", "pr", "ready", "--undo", pr_url], cwd=worktree, check=False)
                    st.run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
                    nudged = True
                elif pending == [CI_NOT_STARTED] and waited >= CI_START:
                    self.ask_problem("every CI job on %s was skipped, so CI has not checked "
                                     "the branch" % pr_url,
                                     "Start CI on the PR, for example by marking it draft and "
                                     "ready again. When you answer, the runner waits for it.")
                    self.set(status="checking")
                    started, nudged = time.time(), True
                    time.sleep(CI_CHECK)
                    continue
                elif not rollup and waited >= CI_START:
                    st.warn("no CI check ran in %d minutes — taking it as none" % (CI_START // 60))
                    self.set(checks=[])
                    return None, None
                self.set(doing="waiting for CI%s" % (": %s" % ", ".join(pending) if pending else ""))
            if waited >= CI_TIMEOUT:
                # Whatever the person says, CI is what is waited for: start the clock again.
                self.ask_problem("CI has not finished in %d hours" % (CI_TIMEOUT // 3600), pr_url)
                self.set(status="checking")
                started = time.time()
            time.sleep(CI_CHECK)

    def sync_and_ci(self):
        """The gate, with CI failures handed to a cheap fixer first: (None, None)
        when CI passes, else what the lead is to fix."""
        attempt = 0
        while True:
            kind, fix = self.gate()
            if kind != "ci" or attempt == CI_FIXES:
                return kind, fix
            attempt += 1
            model = self.data.get("model")
            prompt = ci_fix_prompt(self.data["branch"], fix.split("\n", 2)[2])
            _, before, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
            while True:
                self.step("Fixing CI (%d/%d) on %s" % (attempt, CI_FIXES, short_model(model)))
                self.wait_for_usage()
                self.set(status="checking", doing="fixing CI, try %d" % attempt)
                _, stop, error = self.call(prompt, str(uuid.uuid4()), False, "ci-fix", model,
                                           self.effort("lead"))
                # A call cut off at the usage threshold was not a try: it starts over
                # once the limit frees up.
                if stop != "usage":
                    break
            if error:
                st.warn("the CI fixer failed: %s" % error.splitlines()[0][:200])
            _, after, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
            if after == before:
                # Nothing new to push: CI would only say the same again.
                st.warn("the CI fixer committed nothing — over to the lead")
                return kind, fix

    def sync_part(self):
        """Merge the goal's branch into a part's, to bring in the parts finished
        before it. Returns None, or what the lead is to fix."""
        worktree, base = self.data["worktree"], self.data["base"]
        self.set(status="checking", doing="syncing with the goal's branch")
        self.step("Syncing with %s" % base)
        code, out, err = st.git(["merge", "--no-edit", base], cwd=worktree, check=False)
        if code == 0:
            return None
        _, files, _ = st.git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree, check=False)
        if not files.strip():
            return ("You reported done, but the runner could not merge `%s` into your branch:"
                    "\n\n```\n%s\n```\n\nCommit or remove what is in the way, then report "
                    "done again." % (base, (err or out).strip()[-2000:]))
        st.warn("the merge conflicts — back to the lead")
        return conflict_prompt(base, files.split())

    def deliver(self):
        """Merge a part into the goal's branch, one part at a time. Returns None,
        or what the lead is to fix first."""
        parent = Goal(self.main_root, self.data["parent"])
        with open(parent.state.path("parts.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            while True:
                fix = self.sync_part()
                if fix:
                    return fix
                code, _, err = st.git(["merge", "--ff-only", self.data["branch"]],
                                      cwd=self.data["parent_worktree"], check=False)
                if code == 0:
                    st.info("merged into %s" % self.data["base"])
                    return None
                self.ask_problem("could not merge the part into %s" % self.data["base"], err)

    def run_parts(self):
        """Build the parts: each as a goal of its own, started once the parts it
        builds on are done, a few at a time. Returns the lead's next prompt, once
        every part is merged into the goal's branch."""
        parts, first = self.data["parts"], True
        while True:
            goals = {p["name"]: Goal(self.main_root, p["id"]).read() or {} for p in parts}
            alive = {p["name"] for p in parts if Goal(self.main_root, p["id"]).runner_alive()}
            done = [p for p in parts if goals[p["name"]].get("status") == "done"]
            journal = self.read_journal()
            ticked = tick_parts(journal, {p["name"] for p in done})
            if ticked != journal:
                self.write_journal(ticked)
            flow2 = self.flow2()
            if len(done) == len(parts):
                st.info("every part is done — the integration starts in a new session")
                _, merged, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
                self.set(parts_merged_head=merged.strip())
                # The planning's context is stale by now: the journal and the branch hold
                # what is true, so the integration starts fresh from them.
                self.set(session=None, session_used=False)
                return self.first_prompt() + "\n\n" + parts_done_prompt(
                    [dict(p, summary=goals[p["name"]].get("summary"),
                          journal=Goal(self.main_root, p["id"]).journal) for p in parts],
                    self.goal.journal)
            running, ready = [], []
            for p in parts:
                g = goals[p["name"]]
                if g.get("status") == "done":
                    continue
                if p["name"] in alive:
                    running.append(p["name"])
                elif not os.path.exists(Goal(self.main_root, p["id"]).state.path(GOAL_FILE)) \
                        or g.get("status") == "new" or first:
                    ready.append(p)
                else:
                    reason = g.get("reason") if g.get("status") == "failed" else g.get("status")
                    self.ask_problem("part \"%s\" %s" % (p["name"], "failed" if g.get(
                        "status") == "failed" else "stopped"), reason)
                    ready.append(p)
            names = {p["name"] for p in done}
            built = [{"name": p["name"], "summary": goals[p["name"]].get("summary")} for p in done]
            for p in ready:
                # In flow 2 a part plans at once, and waits by itself before it builds.
                if not flow2 and len(running) >= PARALLEL_PARTS:
                    break
                if set((p.get("plan_after") or []) if flow2 else p["after"]) <= names:
                    gid = create_part(self.main_root, self.data, p,
                                      [x["name"] for x in parts].index(p["name"]), built)
                    st.info("part \"%s\": starting" % p["name"])
                    launch(self.main_root, gid)
                    running.append(p["name"])
            self.set(status="parts", doing="parts: %d of %d done%s" % (
                len(done), len(parts), " · running %s" % ", ".join(running) if running else ""))
            first = False
            time.sleep(PARTS_CHECK)

    def start_parts(self):
        """After the review: when the lead split the work, the parts it wrote.
        None when it did not."""
        if self.data.get("depth", 0) >= MAX_DEPTH or not os.path.exists(
                self.goal.state.path(PARTS_FILE)):
            return None
        with open(self.goal.state.path(PARTS_FILE)) as f:
            parts = read_parts(f.read())
        parts = [dict(p, id=part_id(self.goal.id, p["name"])) for p in parts]
        order = part_order(parts)
        parts.sort(key=lambda p: order.index(p["name"]))
        _, dirty, _ = st.git(["status", "--porcelain"], cwd=self.data["worktree"], check=False)
        if dirty.strip():
            st.git(["add", "-A"], cwd=self.data["worktree"], check=False)
            st.git(["commit", "-m", "%s :: work before the parts" % (self.data.get("key") or "goal")],
                   cwd=self.data["worktree"], check=False)
        self.step("Splitting into %d parts" % len(parts))
        for p in parts:
            st.info("- %s%s" % (p["name"], " (after %s)" % ", ".join(p["after"]) if p["after"] else ""))
        self.install()
        self.set(parts=parts, phase="parts")
        self.write_journal(fold_part_criteria(self.read_journal(), [
            dict(p, journal=Goal(self.main_root, p["id"]).journal) for p in parts]))
        return parts

    # the plan, for the person

    def planned(self, summary=None):
        """The lead's plan is complete: reviewed, corrected, then put to the
        person. Returns the lead's next prompt."""
        if self.data.get("revising"):
            # Revised after the person asked for changes: to them again.
            self.set(revising=False)
            return self.plan_gate(reply=summary)
        if self.data.get("replanning"):
            # A goal from before: the person approved the plan with changes, applied now.
            return self.after_plan()
        if self.data.get("small"):
            self.set(reviewed=True)
            self.step("Small change: building without a plan review")
            return self.after_plan()
        gaps, questions = [], []
        if not self.data.get("reviewed") and not (self.data.get("parent") and self.waits_for_person()):
            gaps, questions = self.review()
        self.set(reviewed=True)
        answers = answers_text(questions, self.ask_questions(questions, "review")) if questions else None
        if gaps or answers:
            return review_prompt(gaps, answers, again=True)
        return self.plan_gate()

    def plan_gate(self, reply=None):
        """After the review: the plan, approved by the person when the goal waits for
        them. Returns the lead's next prompt."""
        if not self.waits_for_person():
            return self.after_plan()
        parts = self.written_parts() if self.split_now() else None
        what = "split" if parts else "plan"
        self.step("The %s is ready for your review" % what)
        names = plan_names(self.read_journal(), parts)
        detail = "\n".join("- %s" % n for n in names) or None
        if reply:
            detail = "What changed: %s\n\n%s" % (reply.strip(), detail or "")
        return self.await_plan({"kind": "plan", "headline": "%s ready for your review" % what,
                                "split": bool(parts), "detail": detail})

    def await_plan(self, record):
        """Approval goes on to the build; anything else the person says is changes
        the lead makes before the plan comes back to them."""
        text = self.wait_for_answer(record)
        if not approves(text):
            st.info("you asked for changes — back to the lead")
            self.set(revising=True, phase="planning")
            return revise_prompt(text)
        st.info("the plan is approved")
        return self.after_plan()

    def after_plan(self):
        """The plan is approved: start the parts, or build. Returns the lead's
        next prompt."""
        self.set(approved=True, replanning=False)
        if self.split_now():
            if not self.data.get("parts"):
                self.start_parts()
            prompt = self.run_parts()
            self.set(phase="building", status="working")
            return prompt
        prompt = BUILD_NOW
        if self.data.get("parent"):
            built = self.wait_to_build()
            fix = self.sync_part()
            prompt = "\n\n".join(x for x in (built_text(built), prompt, fix) if x)
        self.set(phase="building", status="working")
        return self.fresh(prompt + "\n\n" + CONTINUE)

    def compact_journal(self):
        """Before a new session reads it, a journal over JOURNAL_MAX is rewritten by the
        sub-agent model to what is true now. The runner keeps the rewrite only when
        it keeps every criterion, step and answer and is smaller; the old one goes
        to the archive. Returns the archived copy's path, or None."""
        try:
            with open(self.goal.journal) as f:
                before = f.read()
        except (IOError, OSError):
            return None
        size = len(before.encode())
        if size <= JOURNAL_MAX or size < (self.data.get("compact_after") or 0):
            return None
        self.step("Compacting the journal (%d KB)" % (size // 1024))
        target = self.goal.state.path("journal.compact.md")
        self.goal.state.remove("journal.compact.md")
        self.wait_for_usage()
        _, _, error = self.call(render(os.path.join(PROMPTS, "compact.md"), source=self.goal.journal,
                                       target=target), str(uuid.uuid4()), False, "compact",
                                self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL)
        try:
            with open(target) as f:
                after = f.read()
        except (IOError, OSError):
            after = ""
        problem = error or journal_lost(before, after)
        if problem:
            st.warn("the compacted journal is not kept: %s" % problem)
            self.goal.state.remove("journal.compact.md")
            self.set(compact_after=size + JOURNAL_REGROW)
            return None
        os.makedirs(self.goal.state.path(ARCHIVE_DIR), exist_ok=True)
        archived = self.goal.state.path(os.path.join(ARCHIVE_DIR, "round-%s.md" % self.data.get("round", 0)))
        with open(archived, "w") as f:
            f.write(before)
        os.replace(target, self.goal.journal)
        st.info("journal: %d KB → %d KB" % (size // 1024, len(after.encode()) // 1024))
        self.set(compact_after=None)
        return archived

    def fresh(self, prompt):
        """The build starts, or carries on after a pause or a restart, in a new
        session: the lead's context is the journal and the branch, not history."""
        archived = self.compact_journal()
        if archived:
            prompt += ("\n\nThe runner compacted your journal to what is true now. The journal "
                       "before it is `%s`: read it only for something the new one dropped." % archived)
        self.set(session=None, session_used=False)
        _, dirty, _ = st.git(["status", "--porcelain"], cwd=self.data["worktree"], check=False)
        left = ("\n\nThe worktree has changes that are not committed, from a session that was "
                "stopped: `git status` shows them. Check them with an explorer or a reviewer "
                "task. The runner commits them before it runs your next tasks."
                if dirty.strip() else "")
        return self.first_prompt() + "\n\n" + FRESH + left + "\n\n" + prompt

    # the build's tasks: the lead hands them over, the runner runs them

    def run_tasks(self, tasks):
        """Run the lead's tasks, PARALLEL_TASKS at a time: each coding task in its own
        worktree off the branch, merged back when it ends; each question on the goal's
        worktree, read only. Returns a report per task, in the lead's order."""
        tasks = [t for t in tasks if isinstance(t, dict) and str(t.get("brief") or "").strip()]
        self.install()
        self.prune_task_branches()
        self.step("Running %d task(s) from the lead" % len(tasks))
        # Tasks start from the last commit, and merge back into a clean tree.
        st.git(["add", "-A"], cwd=self.data["worktree"], check=False)
        if st.git(["commit", "-q", "-m", "Work left uncommitted by an earlier session"],
                  cwd=self.data["worktree"], check=False)[0] == 0:
            st.info("committed the work an earlier session left uncommitted")
        self.set(status="working", doing="running %d task(s)" % len(tasks))
        results = [None] * len(tasks)
        self.goal.state.write(TASKS_FILE, {"round": self.data.get("round"), "tasks": [
            {"name": str(t.get("name") or "task %d" % (n + 1)), "kind": t.get("kind") or "code",
             "status": "waiting"} for n, t in enumerate(tasks)]})
        todo = list(enumerate(tasks))
        self.stopping = False
        while todo and not self.stopping:
            self.wait_for_usage()
            first, todo[:] = todo[:PARALLEL_TASKS], todo[PARALLEL_TASKS:]
            held = []

            def refill(ended):
                # A slot is free as soon as one task ends: the next task starts then,
                # from the branch with that task merged. Near the usage limit, none
                # starts until the limit resets.
                if ended.get("cut") or (todo and not held and over_threshold(
                        self.usage(), self.threshold())):
                    held.append(True)
                if held or not todo or self.stopping:
                    return []
                return [self.start_task(*todo.pop(0))]
            running = [self.start_task(n, task) for n, task in first]
            for run in self.wait_tasks(running, refill):
                results[run["n"]] = self.end_task(run)
        for n, task in todo if self.stopping else []:
            results[n] = {"name": str(task.get("name") or "task %d" % (n + 1)),
                          "kind": "explore" if task.get("kind") == "explore" else "code",
                          "status": "not started: the person's note stopped the tasks"}
        return results

    def start_task(self, n, task):
        explore = task.get("kind") == "explore"
        name = str(task.get("name") or ("question %d" % (n + 1) if explore else "task %d" % (n + 1)))
        # Tasks code or answer questions: the reasoning is the lead's. So every task
        # runs on the sub-agent model, whatever the lead asks for.
        model = self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL
        run = {"n": n, "name": name, "explore": explore, "model": model,
               "session": str(uuid.uuid4()), "started": time.time()}
        if explore:
            cwd = self.data["worktree"]
            prompt = render(os.path.join(PROMPTS, "explore.md"), question=task["brief"].strip())
        else:
            stamp = "r%d-%d" % (self.data.get("round", 0), n + 1)
            _, start, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
            run["branch"] = "%s--%s" % (self.data["branch"], stamp)
            cwd = run["worktree"] = "%s--%s" % (self.data["worktree"], stamp)
            st.git(["worktree", "add", "-b", run["branch"], cwd, "HEAD"], cwd=self.data["worktree"])
            link_dependencies(self.data["worktree"], cwd)
            guides = ", ".join("`%s`" % g for g in testing_guides(self.data["worktree"]))
            prompt = render(os.path.join(PROMPTS, "task.md"), brief=task["brief"].strip(),
                            worktree=cwd, branch=run["branch"], start=start.strip()[:12],
                            testing=" The testing guide is %s." % guides if guides else
                            " The repository has no testing guide: the brief's test map and "
                            "the existing tests show how it tests.")
        if oc.is_opencode(model):
            st.info("%s: %s on %s" % ("question" if explore else "task", name, model))
            self.task_state(n, status="running", model=model, session=run["session"], cwd=cwd,
                            started=run["started"], name=name)
            run["harness"] = "opencode"
            run["child"] = self.opencode_run(model, prompt, run["session"], cwd, readonly=explore,
                                             subagents=False)
            self.children.append(run["child"])
            return run
        settings = self.goal.state.path("settings-%s.json" % run["session"][:8])
        mode, allow = unattended(model, [cwd, self.goal.state.dir], [])
        with open(settings, "w") as f:
            json.dump(hook_settings(self.goal.state.path(WIND_FILE), fence=self.data.get("fence") or (),
                                    allow=allow, readonly=cwd if explore else None,
                                    task=not explore, explore=explore), f)
        run["settings"] = settings
        cmd = ["claude", "-p", "--output-format", "json", "--model", model,
               "--permission-mode", mode, "--max-turns", str(MAX_TURNS), "--settings", settings,
               "--disallowedTools", "Agent,Task," + NO_WAITING] + NO_MCP + (
                   ["--effort", self.effort("subagent")] if self.effort("subagent") else []) + [
                   "--session-id", run["session"], prompt]
        st.info("%s: %s on %s" % ("question" if explore else "task", name, short_model(model)))
        self.task_state(n, status="running", model=model, session=run["session"], cwd=cwd,
                        started=run["started"], name=name)
        run["child"] = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True)
        self.children.append(run["child"])
        return run

    def wait_tasks(self, running, refill=None):
        """Each task as it ends; after each, `refill(run)` may start more, which are
        waited for too. Over the usage limit, every task still running is stopped:
        its report says so, and the lead starts it again later."""
        import threading
        outs = {}

        def drain(run):
            outs[run["n"]] = run["child"].communicate()

        def watch(run):
            threading.Thread(target=drain, args=(run,), daemon=True).start()
        for run in running:
            watch(run)
        left, checked = list(running), time.time()
        while left:
            for run in list(left):
                if run["n"] in outs:
                    run["out"], run["err"] = outs[run["n"]]
                    left.remove(run)
                    yield run
                    for new in (refill(run) if refill else []):
                        watch(new)
                        left.append(new)
            if not left:
                break
            if nt.stop_asked(self.goal.state.dir):
                st.warn("your note asks to stop the tasks that run now")
                self.stopping = True
                for run in left:
                    run["stopped"] = True
                    try:
                        os.killpg(run["child"].pid, signal.SIGTERM)
                    except OSError:
                        pass
            if time.time() - checked >= USAGE_CHECK:
                checked = time.time()
                hard = over_threshold(self.usage(), self.threshold() + HARD_MARGIN)
                if hard:
                    st.warn("%s at %d%% — stopping the tasks; the lead starts them again later"
                            % (hard["name"], hard["used"]))
                    for run in left:
                        run["cut"] = True
                        try:
                            os.killpg(run["child"].pid, signal.SIGTERM)
                        except OSError:
                            pass
            time.sleep(TASK_CHECK if left else 0)

    def end_task(self, run):
        """A task's report for the lead; a coding task's branch merged into the goal's."""
        self.children.remove(run["child"])
        out = run.get("out") or b""
        label = "explore" if run["explore"] else "task"
        if run.get("harness") == "opencode":
            text, telemetry = oc.parse_events(out.decode("utf-8", "replace"))
            self.record_usage(label, run["model"], None, run["session"], run["started"], telemetry,
                              name=run["name"])
        else:
            self.record_call(label, run["model"], self.effort("subagent"), run["session"], run["started"], out,
                             name=run["name"])
            try:
                os.remove(run["settings"])
            except OSError:
                pass
            text, telemetry = parse_envelope(out.decode("utf-8", "replace"))
        block = extract_last_json_block(text) or {}
        report = {"name": run["name"], "kind": "explore" if run["explore"] else "code"}
        if run.get("stopped"):
            report["status"] = "stopped by the person's note"
        elif run.get("cut"):
            report["status"] = "stopped at the usage limit"
        elif telemetry.get("ok") is False or not out.strip():
            report["status"] = "failed"
            report["notes"] = (telemetry.get("error") or (run.get("err") or b"").decode(
                "utf-8", "replace").strip())[-1500:]
        else:
            report["status"] = block.get("status") or "done"
        for key in ("summary", "answer", "notes", "files", "tests"):
            if block.get(key):
                report[key] = block[key]
        if not run["explore"]:
            report["merge"] = self.merge_task(run, report["status"] == "done")
        st.info("%s: %s%s" % (run["name"], report["status"], " · %s" % report["merge"]
                              if report.get("merge") else ""))
        self.task_state(run["n"], status=report["status"], merge=report.get("merge"),
                        ended=time.time(), summary=report.get("summary") or report.get("answer"))
        return report

    def task_state(self, n, **fields):
        """What the TUI shows of the tasks running now: `tasks.json` in the state."""
        data = self.goal.state.read(TASKS_FILE) or {"tasks": []}
        if n < len(data["tasks"]):
            data["tasks"][n].update(fields)
            self.goal.state.write(TASKS_FILE, data)

    def merge_task(self, run, finished=True):
        """Commit what a task left, merge its branch into the goal's when it finished,
        and remove its worktree. Returns what happened, in a few words."""
        worktree, branch, home = run["worktree"], run["branch"], self.data["worktree"]
        st.git(["add", "-A"], cwd=worktree, check=False)
        st.git(["commit", "-q", "-m", "%s (left uncommitted)" % run["name"]], cwd=worktree, check=False)
        st.git(["worktree", "remove", "--force", worktree], cwd=home, check=False)
        _, ahead, _ = st.git(["rev-list", "--count", "HEAD.." + branch], cwd=home, check=False)
        if ahead.strip() in ("", "0"):
            st.git(["branch", "-D", branch], cwd=home, check=False)
            return "no changes"
        if not finished:
            return "not merged, because the task did not finish. Its work is kept on branch `%s`" % branch
        code, _, _ = st.git(["merge", "--no-ff", "--no-edit", "-m", "Merge task: %s" % run["name"],
                             branch], cwd=home, check=False)
        if code != 0:
            _, files, _ = st.git(["diff", "--name-only", "--diff-filter=U"], cwd=home, check=False)
            st.git(["merge", "--abort"], cwd=home, check=False)
            return ("not merged: it conflicts with the tasks merged before it in %s. Its "
                    "work is kept on branch `%s`" % (", ".join("`%s`" % f for f in files.split())
                                                     or "some files", branch))
        st.git(["branch", "-D", branch], cwd=home, check=False)
        return "merged"

    def decide(self, prompt):
        """What the runner hands the lead in the build — a fix, gaps, a failure —
        starts a new session: the work before it is in the journal and the branch."""
        return self.fresh(prompt) if self.data.get("phase") == "building" else prompt

    def wait_to_build(self):
        """A part's plan is approved: wait until the parts it builds on are merged,
        and fewer than PARALLEL_PARTS others are building. Returns the parts done."""
        parent = Goal(self.main_root, self.data["parent"])
        while True:
            parts = parent.read().get("parts") or []
            me = next((p for p in parts if p["name"] == self.data["part"]), {})
            needs = set(me.get("after") or []) | set(me.get("plan_after") or [])
            with open(parent.state.path("parts.lock"), "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                goals = {p["name"]: Goal(self.main_root, p["id"]).read() or {} for p in parts}
                done = [p["name"] for p in parts if goals[p["name"]].get("status") == "done"]
                building = [n for n, g in goals.items() if n != self.data["part"]
                            and g.get("phase") == "building" and g.get("status") != "done"
                            and Goal(self.main_root, g.get("id") or "-").runner_alive()]
                if needs <= set(done) and len(building) < PARALLEL_PARTS:
                    self.set(phase="building", status="working")
                    return [{"name": n, "summary": goals[n].get("summary")} for n in done]
            waiting = sorted(needs - set(done))
            self.set(status="queued", doing="plan approved — %s" % (
                "builds after %s" % ", ".join(waiting) if waiting else
                "waits for a free slot: %d parts build at a time" % PARALLEL_PARTS))
            time.sleep(PARTS_CHECK)

    def ci_excerpts(self, failing):
        """For each failed check, the telling lines of its job's log: {name: [lines]}."""
        out = {}
        for name, url in failing:
            m = re.search(r"github\.com/([^/]+)/([^/]+)/actions/runs/\d+/job/(\d+)", url or "")
            if not m:
                continue
            code, text, _ = st.run(["gh", "api", "--allow-escape-sequences",
                                    "repos/%s/%s/actions/jobs/%s/logs" % m.groups()],
                                   cwd=self.data["worktree"], check=False)
            if code == 0 and text:
                out[name] = failure_excerpt(text)
        return out

    def fields(self):
        part = bool(self.data.get("parent"))
        branch, base = self.data["branch"], self.data["base"]
        where = ("You are in a worktree on branch `%s`, made from the goal's branch `%s`. All "
                 "of this part's work goes on this branch. The runner merges it into the "
                 "goal's branch when the part is done." % (branch, base) if part else
                 "You are in a worktree on branch `%s`, made from `%s`. All of the work goes "
                 "on this branch. It becomes one PR into `%s`." % (branch, base, base))
        delivery = ("When you report done, the runner merges the goal's branch `%s` into "
                    "yours, to bring in the parts finished before yours. Nothing is pushed "
                    "and no CI runs for a part: CI runs once, when the whole goal is done. If "
                    "the merge conflicts, it tells you, and you fix it." % base if part else
                    "When you report done, the runner merges `%s` into your branch, pushes it "
                    "once, marks the PR ready, and waits for CI. If the merge conflicts or CI "
                    "fails, it tells you what failed, and you fix it." % base)
        split = (NO_SPLIT if self.data.get("depth", 0) >= MAX_DEPTH
                 else SPLIT.replace("{{parts_file}}", self.goal.state.path(PARTS_FILE)).replace(
                     "{{plan_after}}", PLAN_AFTER if self.flow2() else ""))
        guides = ", ".join("`%s`" % g for g in testing_guides(self.data["worktree"]))
        return {"ask": self.data["ask"], "branch": self.data["branch"],
                "where": where, "delivery": delivery, "split": split,
                "testing": TESTING % guides if guides else NO_TESTING,
                "testing_check": TESTING_CHECK % (
                    "the repository's testing guide, %s, and " % guides if guides else ""),
                "plan_note": PLAN_NOTE + (TECHNICAL.replace("{{technical_plan}}", self.technical_plan())
                                          if self.flow2() else ""),
                "parts_file": self.goal.state.path(PARTS_FILE),
                "phase": PLANNING if self.data.get("phase") == "planning" else BUILDING,
                "base": self.data["base"], "journal": self.goal.journal,
                "technical_plan": self.technical_plan(),
                "scope": getattr(self, "scope", ""), "sources": SOURCES,
                "checks": ("This part has run no CI: CI runs once, when the whole goal is "
                           "done. Judge the code, not test results." if part else
                           checks_text(self.data["base"])),
                "subagent_model": self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL,
                "subagent_alias": short_model(self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL)}

    def technical_plan(self):
        return self.goal.state.path(TECHNICAL_FILE)

    def write_journal(self, text):
        if text:
            with open(self.goal.journal, "w") as f:
                f.write(text)

    def read_journal(self):
        try:
            with open(self.goal.journal) as f:
                return f.read()
        except (IOError, OSError):
            return ""

    def first_prompt(self):
        return render(os.path.join(PROMPTS, "lead.md"), **self.fields())

    # the person

    def wait_for_answer(self, record):
        """Leave a question for the person and wait for their answer, which conductor
        writes to the goal's answer file."""
        asked_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        pending = self.goal.state.read("awaiting.json") or {}
        if pending.get("asked_at") and pending.get("kind") == record["kind"]:
            asked_at = pending["asked_at"]
        else:
            self.goal.state.write("awaiting.json", dict(record, asked_at=asked_at))
            asked = record.get("questions")
            notify("Waiting on you", "%s: %s" % (self.data.get("name") or self.goal.id, record.get(
                "headline") or ("%d question(s)" % len(asked) if asked else "it asks you")),
                SOUNDS["waiting"], page_url(self.main_root, self.goal.id))
        self.set(status="waiting", doing="waiting on you")
        st.info("waiting on you")
        while True:
            text = st.local_answer(self.goal.state.read(st.ANSWER_FILE), asked_at)
            if text:
                self.goal.state.remove(st.ANSWER_FILE)
                self.goal.state.remove("awaiting.json")
                st.info("answered")
                return text
            time.sleep(ANSWER_CHECK)

    def ask_questions(self, questions, label="lead"):
        if self.data.get("parent"):
            questions, answered = self.consult(questions)
            if not questions:
                return answered
            return "\n\n".join(x for x in (answered, self.ask_person(questions, label)) if x)
        return self.ask_person(questions, label)

    def consult(self, questions):
        """A part's questions, put to the goal's lead first: (the ones only the
        person can answer, the lead's answers to the rest as text)."""
        self.step("Asking the goal's lead")
        parent = Goal(self.main_root, self.data["parent"])
        try:
            with open(parent.journal) as f:
                journal = f.read()
        except (IOError, OSError):
            journal = ""
        prompt = render(os.path.join(PROMPTS, "consult.md"), ask=parent.read().get("ask") or "", sources=SOURCES,
                        journal=journal or "(empty)", part=self.data["part"],
                        questions="\n".join("- %s (%s)" % (q["q"], q.get("why") or "")
                                             for q in questions))
        for _ in range(3):
            self.wait_for_usage()
            block, stop, error = self.call(prompt, str(uuid.uuid4()), False, "consult",
                                           (parent.read() or {}).get("model"), self.effort("lead"))
            self.cut_off = None
            if stop != "usage" and not error and isinstance(block, dict):
                break
        else:
            return questions, ""
        answers = [a for a in block.get("answers") or [] if isinstance(a, dict) and a.get("a")]
        rest = st.parse_agent_questions({"questions": block.get("for_person") or []}) or []
        for a in answers:
            st.info("lead: %s → %s" % (a.get("q"), a["a"]))
        text = ("The goal's lead answered:\n\n" + "\n".join(
            "- %s\n  %s" % (a.get("q"), a["a"]) for a in answers)) if answers else ""
        return rest, text

    def ask_person(self, questions, label="lead"):
        self.step("Asking you")
        for q in questions:
            st.info("Q: %s" % q["q"])
        return self.wait_for_answer({"kind": "questions", "label": label, "questions": questions})

    def ask_problem(self, headline, detail=None):
        self.step("Stopped — %s" % headline)
        return self.wait_for_answer({"kind": "problem", "headline": headline,
                                     "detail": (detail or "").strip()[-1500:] or None})

    # git

    def push(self):
        worktree, branch = self.data["worktree"], self.data["branch"]
        while True:
            code, _, err = st.git(["push", "-u", "origin", branch], cwd=worktree, check=False)
            if code == 0:
                return
            self.ask_problem("could not push %s" % branch, err)

    def head(self):
        _, sha, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
        return "%s\n%s" % (sha, st.worktree_fingerprint(self.data["worktree"]))

    def finish(self, block):
        self.step("Finishing")
        if self.data.get("parent"):
            self.set(status="done", doing=block.get("summary") or "done",
                     summary=block.get("summary"), finished=time.time())
            self.clean_up()
            return
        worktree, pr_url = self.data["worktree"], self.data.get("pr_url")
        revised = self.data.get("revising_pr")
        self.push()
        if pr_url:
            if revised:
                comment = "%s\n\n%s" % (ADDRESSED, (block.get("walkthrough") or "").strip()
                                          or block.get("summary") or "")
            else:
                body = "%s\n\n%s\n" % (self.pr_ask(), block.get("summary") or "")
                st.run(["gh", "pr", "edit", pr_url, "--body", body], cwd=worktree, check=False)
                comment = "" if self.walked_through(pr_url) else (block.get("walkthrough") or "").strip()
            if comment:
                comment += "\n\n" + checks_section(self.data.get("checks"), self.data.get("ci_left"))
                st.run(["gh", "pr", "comment", pr_url, "--body", st.mark(comment.strip())],
                       cwd=worktree, check=False)
                if not revised:
                    self.set(walked_through=True)
            st.run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
            st.info("PR ready: %s" % pr_url)
        self.set(status="review", phase="review", revising_pr=False, summary=block.get("summary"),
                 doing=REVIEW_DOING, finished=time.time(),
                 watch_from=self.data.get("watch_from") or time.time())

    def walked_through(self, pr_url):
        """Whether the PR has the walkthrough already: the goal's own record, or a
        comment of the runner's on the PR that is not a reply to a review."""
        if self.data.get("walked_through"):
            return True
        code, out, _ = st.run(["gh", "pr", "view", pr_url, "--json", "comments"],
                              cwd=self.main_root, check=False)
        try:
            comments = json.loads(out).get("comments") or [] if code == 0 else []
        except ValueError:
            comments = []
        return any(st.is_marked(c.get("body")) and st.mark(ADDRESSED) not in c.get("body", "")
                   for c in comments)

    def watching(self):
        """Whether the goal is done and watches its PR. A goal that finished before
        goals watched their PR counts too, until its PR is merged or closed."""
        if self.data.get("parent") or not self.data.get("pr_url"):
            return False
        return self.data.get("phase") == "review" or (
            self.data.get("status") == "done" and self.data.get("phase") not in ("merged", "closed", MARKED))

    def watch_pr(self):
        """After the finish, until the PR is merged or closed: each new review comment
        on it, from anyone but the runner, starts a revision. Returns the lead's
        prompt for it, or None once the PR is merged or closed."""
        pr_url = self.data.get("pr_url")
        m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url or "")
        if not m:
            self.set(status="done", phase="merged", doing="done")
            return None
        if not self.data.get("watch_from"):
            self.set(watch_from=self.data.get("finished") or time.time())
        self.step("Watching the PR for review comments and the merge")
        while True:
            state = self.pr_state(pr_url)
            if state == "MERGED":
                self.step("Merged")
                self.set(status="done", phase="merged", doing="merged")
                self.clean_up()
                return None
            if state == "CLOSED":
                self.step("The PR was closed without a merge")
                self.set(status="done", phase="closed", doing="its PR was closed without a merge")
                self.clean_up(keep_branch=True)
                return None
            sent = nt.waiting(self.goal.state.dir)
            if sent:
                nt.take(self.goal.state.dir)
                self.step("Your note on the finished goal")
                feedback = "\n\n".join("- The person's note, sent through conductor, not on "
                                         "GitHub:\n\n  %s" % n["text"].replace("\n", "\n  ")
                                         for n in sent)
                self.set(status="working", phase="building", revising_pr=True,
                         revision_ask=((self.data.get("revision_ask") or "") + "\n\n" + feedback).strip())
                return self.fresh(pr_review_prompt(feedback + "\n"))
            items = self.pr_feedback(*m.groups())
            if items:
                self.step("Review comments on the PR")
                for _, heading, _ in items:
                    st.info(heading)
                self.set(pr_handled=sorted(set(self.data.get("pr_handled") or [])
                                           | {i[0] for i in items}),
                         status="working", phase="building", revising_pr=True,
                         revision_ask=((self.data.get("revision_ask") or "") + "\n\n"
                                       + render_feedback(items)).strip())
                return self.fresh(pr_review_prompt(render_feedback(items)))
            if self.data.get("status") != "review":
                self.set(status="review", doing=REVIEW_DOING)
            time.sleep(PR_CHECK)

    def pr_state(self, pr_url):
        code, out, err = st.run(["gh", "pr", "view", pr_url, "--json", "state"],
                                cwd=self.main_root, check=False)
        if code != 0:
            self.pr_unreadable(err or out)
        try:
            return json.loads(out).get("state") if code == 0 else None
        except ValueError:
            return None

    def pr_unreadable(self, err):
        """GitHub refused a read of the PR: in the log once per new error, and on the
        TUI, so a watch that cannot see comments does not look like one with none."""
        line = ((err or "").strip().splitlines() or ["no output"])[-1][:200]
        if self.data.get("pr_error") != line:
            st.warn("cannot read the PR on GitHub: %s" % line)
            self.set(pr_error=line)

    def pr_feedback(self, owner, name, number):
        """The PR's review comments since the goal finished, not handled yet."""
        base = "repos/%s/%s" % (owner, name)
        lists = []
        for path in ("%s/pulls/%s/reviews" % (base, number), "%s/pulls/%s/comments" % (base, number),
                     "%s/issues/%s/comments" % (base, number)):
            code, out, err = st.run(["gh", "api", "--paginate", path, "--jq", ".[]"],
                                    cwd=self.main_root, check=False)
            if code != 0:
                self.pr_unreadable(err or out)
                return []
            rows = []
            for line in out.splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            lists.append([r for r in rows if after(r.get("submitted_at") or r.get("created_at"),
                                                   self.data.get("watch_from") or 0)])
        if self.data.get("pr_error"):
            st.info("the PR can be read again")
            self.set(pr_error=None)
        return collect_feedback(lists[0], lists[1], lists[2], self.data.get("pr_handled"))

    # the loop

    def run(self):
        try:
            # Read before the status says setting-up: a done goal only watches its PR.
            watch = self.watching()
            self.set(pid=os.getpid(), status="setting-up", reason=None)
            self.set_up()
            pending = self.goal.state.read("awaiting.json") or {}
            if pending.get("kind") == "questions":
                prompt = answer_prompt(pending.get("questions"),
                                       self.wait_for_answer(pending))
            elif pending.get("kind") == "problem" and self.data.get("phase") == "parts":
                # A part's problem is looked at again: the parts loop asks once more if
                # the part is still stopped, and goes on if it runs or is done by now.
                self.goal.state.remove("awaiting.json")
                prompt = self.run_parts()
                self.set(phase="building", status="working")
            elif pending.get("kind") == "problem":
                prompt = "The person says:\n\n%s\n\n%s" % (self.wait_for_answer(pending), CONTINUE)
                if self.data.get("phase") == "building":
                    prompt = self.fresh(prompt)
            elif pending.get("kind") == "plan":
                prompt = self.await_plan(pending)
            elif watch:
                prompt = self.watch_pr()
                if prompt is None:
                    return 0
            elif self.flow2() and self.data.get("approved") and self.data.get("phase") == "planning":
                prompt = self.after_plan()
            elif self.data.get("phase") == "parts":
                prompt = self.run_parts()
                self.set(phase="building", status="working")
            elif self.data.get("phase") == "building":
                # A build always carries on in a new session, even from a call that was
                # stopped before it ended.
                prompt = self.fresh(CONTINUE)
            else:
                prompt = self.first_prompt() if not self.data.get("session_used") else CONTINUE
            unchanged, checks, before = 0, 0, self.head()
            while True:
                self.set(round=self.data.get("round", 0) + 1)
                self.step("Round %d" % self.data["round"])
                report, block = self.lead(prompt)
                if block.get("summary"):
                    st.info(block["summary"])
                # Nothing is pushed until the lead reports done: every push runs CI.
                after = self.head()
                unchanged = unchanged + 1 if after == before and self.data.get(
                    "phase") != "planning" else 0
                before = after
                if report == "question":
                    prompt = answer_prompt(block["questions"], self.ask_questions(block["questions"]))
                    continue
                if report == "cut":
                    prompt = self.cut_off_notice()
                    if self.data.get("phase") == "building":
                        prompt = self.fresh(prompt)
                    continue
                if report == "dispatch" and self.data.get("phase") == "building":
                    prompt = self.decide(dispatched_prompt(self.run_tasks(block.get("tasks") or [])))
                    continue
                if report == "step" and self.data.get("phase") == "building":
                    prompt = self.fresh(NEXT_STEP % (block.get("handoff") or block.get("summary")
                                                     or "(no note: read the journal)"))
                    continue
                if report == "replan" and self.data.get("phase") == "building" and self.flow2():
                    st.info("a note adds work — back to planning")
                    self.set(phase="planning", reviewed=False, approved=False, small=None,
                             revising=False)
                    prompt = REPLAN
                    continue
                if report == "planned" or report == "done" and self.data.get("phase") == "planning":
                    if self.data.get("phase") != "planning":
                        prompt = CONTINUE
                        continue
                    journal = self.read_journal()
                    problems = plan_problems(journal)
                    split = self.data.get("depth", 0) < MAX_DEPTH and os.path.exists(
                        self.goal.state.path(PARTS_FILE))
                    if split:
                        with open(self.goal.state.path(PARTS_FILE)) as f:
                            problems += parts_problems(read_parts(f.read()),
                                                       checklist(journal, "Acceptance criteria"))
                    self.set(small=small_reason(block, bool(self.data.get("parent")), split)
                             if self.flow2() else None)
                    if self.flow2() and not self.data.get("small") \
                            and not os.path.exists(self.technical_plan()):
                        problems.append("the technical plan, `%s`" % self.technical_plan())
                    if problems:
                        prompt = planning_prompt(problems)
                        continue
                    if self.flow2():
                        prompt = self.planned(block.get("summary"))
                        continue
                    if self.data.get("parent") or (split and self.data.get("reviewed")):
                        gaps, questions = [], []
                    else:
                        gaps, questions = self.review()
                        self.set(reviewed=True)
                    answers = answers_text(questions, self.ask_questions(
                        questions, "review")) if questions else None
                    if split and (gaps or answers):
                        # The parts start from the criteria: those are put right first.
                        prompt = review_prompt(gaps, answers, again=True)
                        continue
                    if split:
                        self.start_parts()
                        prompt = self.run_parts()
                        self.set(phase="building", status="working")
                        continue
                    self.set(phase="building")
                    prompt = self.fresh(review_prompt(gaps, answers))
                    continue
                if report == "done" and nt.waiting(self.goal.state.dir):
                    prompt = self.decide(NOTE_FIRST)
                    continue
                if report == "done":
                    unmet = unmet_criteria(self.read_journal())
                    if unmet:
                        st.warn("done, but %d acceptance criteria are not ticked" % len(unmet))
                        prompt = self.decide(unmet_prompt(unmet))
                        continue
                    # Checked before anything is pushed: a gap found after CI costs a
                    # second CI run.
                    fix = self.sync_part() if self.data.get("parent") else self.sync()
                    if not fix:
                        fix = self.local_ci()
                    if not fix:
                        done, gaps, questions = self.check()
                        if done and self.data.get("parent"):
                            fix = self.deliver()
                        elif done:
                            _, fix = self.sync_and_ci()
                    if fix:
                        # A fix about other failures than the last means the last one
                        # made progress: the tries count again from there.
                        signature = fix_signature(fix)
                        if signature and signature != self.data.get("fix_signature"):
                            if self.data.get("fix_signature") is not None:
                                st.info("other failures than last time — the tries start again")
                            checks = 0
                        self.set(fix_signature=signature, fix_rounds=(self.data.get("fix_rounds") or 0) + 1)
                        checks += 1
                        if checks >= MAX_CHECKS or self.data["fix_rounds"] >= MAX_FIX_ROUNDS:
                            answer = self.ask_problem(
                                "the branch still fails to sync or pass CI after %d tries"
                                % checks, fix)
                            prompt, checks = "The person says:\n\n%s\n\n%s" % (answer, fix), 0
                            self.set(fix_rounds=0)
                        else:
                            prompt = fix
                        prompt = self.decide(prompt)
                        continue
                    if done and nt.waiting(self.goal.state.dir):
                        prompt = self.decide(NOTE_FIRST)
                        continue
                    if done:
                        self.set(fix_rounds=0, fix_signature=None)
                        self.finish(block)
                        prompt = self.watch_pr() if not self.data.get("parent") else None
                        if prompt is None:
                            return 0
                        unchanged, checks = 0, 0
                        continue
                    answers = answers_text(questions, self.ask_questions(
                        questions, "check")) if questions else None
                    checks += 1
                    if checks >= MAX_CHECKS:
                        answer = self.ask_problem(
                            "the checker still finds gaps after %d tries" % checks, "\n".join(gaps))
                        prompt, checks = "The person says:\n\n%s\n\n%s" % (
                            answer, gaps_prompt(gaps, answers)), 0
                    else:
                        prompt = gaps_prompt(gaps, answers)
                    prompt = self.decide(prompt)
                    continue
                if unchanged >= STALL_ROUNDS:
                    answer = self.ask_problem("%d rounds in a row changed nothing" % unchanged)
                    prompt, unchanged = "The person says:\n\n%s\n\n%s" % (answer, CONTINUE), 0
                    continue
                prompt = self.decide(RESUME_STEP) if self.data.get("phase") == "building" else CONTINUE
        except Stopped:
            self.set(status="stopped", reason="stopped", doing="stopped")
            return 1
        except st.Failure as e:
            self.set(status="failed", reason=str(e), doing=str(e).splitlines()[0][:200])
            st.warn(str(e))
            return 1
        finally:
            self.set(pid=None)


SOURCES = """The prototype is the source of truth. It decides what is built, and how each
screen looks and behaves: its layout, its parts, their order, their text and their
states. Only two things overrule it:

1. The person's answers to questions. They overrule everything, the prototype too.
2. The ask, where it says explicitly that it replaces the prototype, such as "X
   instead of the prototype" or "not as in the prototype: X". The ask is what the
   person wrote and the description of each ticket or subtask in it. Only such
   words count. When the ask describes something differently from the prototype,
   but does not say that it replaces the prototype, the prototype wins. That is not
   a question for the person.

Do not use one-pagers, PRDs or product specs, and do not open the product
repository (such as `humanus-product`), even when the ask links to them. They
decide nothing. Other references, such as design records, attachments, branches and
other tickets, give context only. They never overrule the prototype.

When the ask wants something that the prototype does not show, or the prototype
does not answer a question, the person decides. That is a question for them. When
the ask has no prototype, the ask decides what is built, and the person decides
what it leaves open.

The repository's conventions decide how the code is written, not what is built."""


def render(path, **kwargs):
    with open(path) as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


# --- command line --------------------------------------------------------------

def main(argv):
    parser = argparse.ArgumentParser(prog="cond goal", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="make a goal from a prompt")
    new.add_argument("prompt", nargs="?", default="-",
                     help="what to build, in words and links; - (the default) "
                          "reads it from stdin")
    new.add_argument("-f", "--file", action="append", default=[], dest="files",
                     help="a file or folder to give with the prompt, such as an image or a "
                          "prototype; repeat for more")
    new.add_argument("--base", help="the branch to build on and open the PR into (default: main)")
    new.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                     help="pause while any usage limit is at or over this percentage")
    new.add_argument("--model", default=DEFAULT_MODEL, help="the lead's model")
    new.add_argument("--subagent-model", default=DEFAULT_SUBAGENT_MODEL,
                     help="the default for the lead's sub-agents; it can ask for another")
    new.add_argument("--check-model", default=DEFAULT_CHECK_MODEL, help="the checker's model")
    new.add_argument("--gate", default=DEFAULT_GATE, choices=GATES,
                     help="who approves the plan: you at every level, you for the goal only, "
                          "or the reviewer agent")
    new.add_argument("--start", action="store_true", help="start it in the background")
    new.add_argument("--repo", default=".")
    run = sub.add_parser("run", help="run or resume a goal in the foreground")
    run.add_argument("id")
    run.add_argument("--repo", default=".")
    back = sub.add_parser("undo", help="take a goal's work back out: its PR, branches, worktrees "
                                       "and state")
    back.add_argument("id")
    back.add_argument("--repo", default=".")
    tidy = sub.add_parser("clean", help="remove the worktrees and branches of goals that ended "
                                        "and parts that are merged")
    tidy.add_argument("--repo", default=".")
    talk = sub.add_parser("discuss", help="talk a goal through with Claude, which writes only in a temp folder")
    talk.add_argument("id", nargs="?", help="the goal; without it, pick one from a list")
    talk.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    main_root = st.main_repo_root(os.path.abspath(args.repo))
    if args.cmd == "discuss":
        gid = args.id or pick_goal(main_root)
        if not gid:
            return 1
        argv, cwd = discuss_command(main_root, gid)
        return subprocess.call(argv, cwd=cwd)
    if args.cmd == "clean":
        for line in sweep(main_root):
            print(line)
        return 0
    if args.cmd == "undo":
        for line in undo(main_root, args.id):
            print(line)
        return 0
    if args.cmd == "new":
        prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
        try:
            gid = create(main_root, prompt, [os.path.abspath(f) for f in args.files],
                         base=args.base, threshold=args.threshold, model=args.model,
                         subagent_model=args.subagent_model, check_model=args.check_model,
                         gate=args.gate)
        except st.Failure as e:
            parser.error(str(e))
        if args.start:
            launch(main_root, gid)
        print(gid)
        return 0
    if not Goal(main_root, args.id).hold():
        print("%s is already running" % args.id)
        return 0
    return Runner(main_root, args.id).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
