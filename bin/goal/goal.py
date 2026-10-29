#!/usr/bin/env python3
#
# goal.py — an Asana ticket, implemented autonomously on one branch, into one PR.
#
# The ask is the ticket: its description, its subtasks, its comments and its
# attachments, read once when the goal starts. Nothing is written back to Asana.
# A lead agent gets the ask and nothing else. It first reads every reference the
# ask names and writes the acceptance criteria and the plan into its journal; the
# checker's model reviews those criteria against the references before anything
# is built. Then the lead builds, starting its own sub-agents, and keeps the
# journal so it can always pick the thread back up. This program is the harness
# around it. It calls the lead in rounds on the same session, hands the person's
# answers back when the lead has a question only they can answer, and pushes the
# branch only when the lead reports done, because every push runs CI. It waits
# for that CI, has an independent checker confirm "done" against the ask, and
# pauses while the Claude subscription is at or over its usage threshold. It never
# merges anything.
#
#   cortex goal new <task URL or gid> [--base feature/x] [--start]   # prints the goal's id
#   cortex goal run <id>                                              # run or resume it
#
# A goal's state is `.cortex/state/<id>/` — `goal.json`, the journal, its
# questions and answers — the same place a task's run keeps its own, so the TUI
# answers both the same way.

import argparse
import datetime
import fcntl
import glob
import html.parser
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
START_TASK_DIR = os.path.join(os.path.dirname(HERE), "start-task")
sys.path.insert(0, START_TASK_DIR)
import start_task as st  # noqa: E402
from agent.base import extract_last_json_block, usage_from  # noqa: E402
from agent.claude_cli import parse_envelope  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "run-milestone"))
from engine import CI_NOT_STARTED, actions_refused, check_states, failed_runs, failure_excerpt  # noqa: E402

HOOK = os.path.join(HERE, "hook.py")

PROMPTS = os.path.join(HERE, "prompts")
GOAL_FILE = "goal.json"
JOURNAL_FILE = "journal.md"
LOG_FILE = "goal.log"
CALLS_FILE = "calls.json"
REPORT_FILE = "usage.txt"

DEFAULT_MODEL = "claude-opus-5-5"
# The lead's sub-agents mostly do narrow, well-briefed parts of the work. The lead
# can still ask for a stronger model for one that needs it.
DEFAULT_SUBAGENT_MODEL = "claude-sonnet-5-5"
# The checker only verifies and reports, and runs only when the lead says it is
# done: the one place where the strongest model costs little and catches most.
DEFAULT_CHECK_MODEL = "claude-fable-5-1"
DEFAULT_CHECK_EFFORT = "xhigh"
DEFAULT_THRESHOLD = 75
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
# Checks in a row that find gaps before the person is asked.
MAX_CHECKS = 4
ANSWER_CHECK = 2
# How often CI is read while its checks run, how long a PR may go without any
# check reporting before it counts as having no CI, and how long CI may take.
CI_CHECK = 60
CI_START = 600
CI_TIMEOUT = 2 * 3600
# Tries a cheap fixer gets at failing CI before the lead takes it on.
CI_FIXES = 2
ROLES = {"lead": "lead", "check": "checker", "ci-fix": "CI fixes"}

# A large goal is split into parts, each a goal of its own on a branch off the
# goal's, merged back into it when done. A part does not split again.
PARTS_FILE = "parts.json"
MAX_DEPTH = 1
PARALLEL_PARTS = 2
PARTS_CHECK = 30
MAX_PARTS = 8
PLANNING = ("This first round is the analysis: steps 1 to 4 of How to work. Do not "
            "change code yet. When the journal has the references, the acceptance criteria "
            "and the plan, end with the `planned` block.")
BUILDING = ("The analysis is finished: the journal has the references, the acceptance "
            "criteria and the plan. Build the work.")
SPLIT = """   When the work is large, split it into parts: do not build it alone. Large is
   several areas of the product, such as separate screens, or an API and the
   screens on it, or more than about 25 acceptance criteria. Each part is built by
   its own lead, with its own sub-agents, journal and checker, on its own branch,
   and merged into yours. Write the parts to `{{parts_file}}` as JSON:

   ```json
   {"parts": [{"name": "Tasks API and data model", "after": [], "brief": "…", "criteria": ["…"]}]}
   ```

   - `criteria`: the acceptance criteria the part must meet, copied word for word
     from your list. Each criterion goes to one part at most. Keep the criteria
     about how the parts fit together for yourself.
   - `after`: the names of the parts it builds on. Put the shared layers first,
     such as the data model and the API contracts, and the parts that use them
     after. Parts with nothing between them run at the same time, so give them
     work that does not touch the same files.
   - `brief`: what the part builds, and what it must not touch; the references
     and their sections that cover it, such as the prototype's functions; and the
     contracts it must follow: the names, types, endpoints and files that other
     parts depend on. Decide those contracts yourself, before the parts start. A
     part's lead gets its brief, its criteria and the whole ask, and nothing else
     from you.

   Two to %d parts is usual. For small work, do not split, and do not write the
   file. When every part is merged into your branch, you integrate: check that the
   parts fit together, build what no part covers, and tick the criteria.""" % MAX_PARTS
NO_SPLIT = ("   This is one part of a larger goal. Do not split it: build it yourself, with "
            "sub-agents.")
CONTINUE = ("Continue the work. Read your journal if you need to remind yourself where "
            "you are, and end with the result block when you stop.")

# Goals this process started, so finished ones are reaped rather than left as
# zombies that still look alive.
_CHILDREN = []

LIVE = ("setting-up", "working", "checking", "waiting", "paused", "parts")
FINISHED = ("done", "failed", "stopped")


# --- pure helpers (unit-tested) ----------------------------------------------

def goal_id(key, name):
    """A goal's id: the ticket's key, and a few words of its name."""
    return "goal-%s-%s" % (st.slugify(key, max_words=3), st.slugify(name, max_words=4))


def title_of(goal, width=70):
    """The ticket's key and name, short enough for a row."""
    line = " ".join(x for x in ((goal or {}).get("key"), (goal or {}).get("name")) if x) or "goal"
    return line if len(line) <= width else line[:width - 1].rstrip() + "…"


def ask_from_ticket(task, url, subtasks=(), comments=(), attachments=()):
    """The ask, as the lead reads it: the ticket and everything hanging off it.
    `subtasks` are full tickets too; `attachments` are download entries with an
    absolute `path`."""
    out = ["# %s: %s" % (st.task_key(task), task.get("name") or ""), url, ""]
    if (task.get("description") or "").strip():
        out += [task["description"].strip(), ""]
    open_subtasks = [t for t in subtasks if not t.get("completed")]
    if open_subtasks:
        out += ["## Subtasks", "", "All of them are part of the ask.", ""]
        for t in open_subtasks:
            out += ["### %s: %s" % (st.task_key(t), t.get("name") or ""), ""]
            if (t.get("description") or "").strip():
                out += [t["description"].strip(), ""]
    said = [c for c in comments
            if (c.get("text") or "").strip() and not c["text"].startswith(st.BOT_MARK)]
    if said:
        out += ["## Comments", ""]
        out += ["- %s: %s" % (c.get("author") or "someone", c["text"].strip()) for c in said]
        out.append("")
    if attachments:
        out += ["## Attachments", ""]
        for a in attachments:
            out.append("- `%s`" % a["path"])
            inline = a.get("inline")
            if inline and a["path"].lower().endswith((".html", ".htm")):
                out += ["", "Its text is below, without the markup, styles and scripts. The file "
                        "itself holds the prototype: read it for how each screen looks and "
                        "behaves."]
                inline = html_text(inline)
            if inline:
                out += ["", "```", inline.rstrip(), "```", ""]
        out.append("")
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
    """What the lead's result block says: ("progress" | "planned" | "done" |
    "question", block). A missing or unreadable block is progress — the lead
    stopped, not finished."""
    if not isinstance(structured, dict):
        return "progress", {}
    status = structured.get("status")
    if status == "question" and st.parse_agent_questions(structured):
        return "question", structured
    if status in ("done", "planned"):
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


def plan_problems(journal):
    """What the journal still lacks after the analysis: [] when it has references,
    acceptance criteria and a plan."""
    problems = []
    if not section_text(journal, "References"):
        problems.append("a `## References` section that lists every reference the ask names")
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
        parts += ["Before you build, a reviewer compared your acceptance criteria with the "
                  "references the ask names, and found these problems:", ""]
        parts += ["- %s" % g for g in gaps] + [""]
        parts += ["Check each one against the references. Correct the criteria where it is "
                  "right. Where it is wrong, write why in the journal. The prototype wins, "
                  "then the one-pager.", ""]
    if answers:
        parts += [answers, ""]
    if again:
        parts += ["Correct the criteria and the parts first: each part starts from them. "
                  "Then report planned again, and the parts start."]
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
        for a in p["after"]:
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
    left, out = {p["name"]: set(p["after"]) for p in parts}, []
    while left:
        ready = [n for n, after in left.items() if after <= set(out)]
        if not ready:
            return None
        for n in sorted(ready, key=[p["name"] for p in parts].index):
            out.append(n)
            del left[n]
    return out


def part_ask(parent, part, built):
    """A part's ask: its brief and criteria, what was built before it, and the
    whole goal's ask for context."""
    out = ["# %s part: %s" % (parent.get("key") or "", part["name"]), "",
           "This is one part of a larger goal. The goal's lead split the work into parts, "
           "and this part is yours. Other leads build the other parts: build only this one, "
           "and follow the contracts in its brief.", "", "## This part", "", part["brief"], "",
           "## Its acceptance criteria", ""]
    out += ["- %s" % c for c in part["criteria"]] + [""]
    if built:
        out += ["## Built before it", "", "These parts are done, and their work is on your "
                "branch already:", ""]
        out += ["- %s: %s" % (b["name"], b.get("summary") or "done") for b in built] + [""]
    out += ["## The whole goal's ask, for context", "", parent.get("ask") or ""]
    return "\n".join(out).rstrip() + "\n"


def part_id(parent_id, name):
    return "%s--%s" % (parent_id, st.slugify(name, max_words=4))


def parts_done_prompt(parts):
    lines = ["Every part is built, passed its own checker, and is merged into your branch:", ""]
    lines += ["- %s: %s" % (p["name"], p.get("summary") or "done") for p in parts]
    lines += ["", "Now integrate. Read what each part did. Check that the parts fit together: "
              "the contracts, the data flowing between them, and the screens end to end. Build "
              "what no part covers. Tick each acceptance criterion the branch meets, with the "
              "file that meets it. Then report done.", "", CONTINUE]
    return "\n".join(lines)


def gaps_prompt(gaps, answers=None):
    parts = ["An independent checker compared the branch with the ask and its references, "
             "and found that it is not finished:", ""]
    parts += ["- %s" % g for g in gaps] + [""]
    if answers:
        parts += [answers, ""]
    parts += ["Before you fix a gap, check it against the references. The prototype wins, "
              "then the one-pager. Do not change what the prototype shows to satisfy a gap. "
              "If a gap is wrong, do not fix it: write why in the journal and say so in your "
              "summary, and the checker reads that. If the prototype and the one-pager do "
              "not settle a gap, ask the person. Then report done again."]
    return "\n".join(parts)


def answers_text(questions, answer):
    """The person's answer to questions a reviewer or checker raised, for the lead."""
    lines = ["The person was asked:", ""] + ["- %s" % q["q"] for q in questions]
    lines += ["", "They answered:", "", answer.strip()]
    return "\n".join(lines)


def conflict_prompt(base, files):
    return ("You reported done. The runner merged `%s` into your branch to sync "
            "it, and the merge conflicts in:\n\n%s\n\nThe merge is still in progress. "
            "Resolve the conflicts, commit the merge, then report done again."
            % (base, "\n".join("- `%s`" % f for f in files)))


def ci_fix_prompt(branch, failures):
    """The cheap fixer's whole brief: the failing checks, and the rules."""
    return ("You fix failing CI checks on branch `%s`, in this worktree. Another agent "
            "built the work; only make these checks pass.\n\n%s\n\nRules:\n"
            "- Fix the cause in the code or the tests. Never weaken a check, skip a test, "
            "raise a budget, or add a baseline entry.\n"
            "- Change only what the failures need. Do not refactor or add features.\n"
            "- Read why it fails from CI, not by running it here: `gh run view <run-id> "
            "--log-failed` gives the whole log of a failed job (the run id is in its URL).\n"
            "- This machine runs many agents at once. Run only single test files by their "
            "path, and a linter or type check on the files you change. Never run a whole "
            "suite (`npx vitest run`, `pytest` with no paths, `npm test`), coverage, "
            "`make verify`, `npm run verify*`, a build, or e2e tests. CI runs those after "
            "your fix.\n"
            "- Commit with a clear message, then stop. Do not push, rebase, or merge: the "
            "runner pushes, and CI checks the fix.\n"
            "- Do not run skills or slash commands, and do not start sub-agents."
            % (branch, failures))


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


def checks_text(base, checks):
    """Step 3 of the checker's prompt: what CI already checked."""
    if not checks:
        return ("The runner merged `%s` into the branch. The PR has no CI checks. Judge the "
                "code, not test results." % base)
    return ("The runner merged `%s` into the branch, and CI passed on it: %s. Judge the "
            "code, not test results." % (base, ", ".join("`%s`" % c for c in checks)))


def checks_section(checks):
    """The PR comment's Checks section: what CI passed on the final branch."""
    if not checks:
        return "## Checks\n\nThe PR has no CI checks."
    return "## Checks\n\nCI passed: %s." % ", ".join("`%s`" % c for c in checks)


def hook_settings(flag, subagent=None, fence=()):
    """Claude Code settings whose hooks reach the call and its sub-agents alike.
    While `flag` exists the call winds down: a new sub-agent is refused, and every
    other tool call says to stop at the next safe point. A push, a CI run and a
    change to the PR are always refused: only the runner pushes. A sub-agent
    started without a model gets `subagent`. A tool call that names one of the
    `fence` texts is refused."""
    check = "test -f %s && { printf '%%s\\n' %s >&2; exit 2; }; exit 0" % (
        shlex.quote(flag), shlex.quote(WIND_DOWN))
    hook = [{"type": "command", "command": check}]

    def guard(*args):
        return {"type": "command", "command": " ".join(
            shlex.quote(a) for a in (sys.executable, HOOK) + args)}
    agent = hook + ([guard("agent", subagent)] if subagent else [])
    pre = [{"matcher": "Agent|Task", "hooks": agent}, {"matcher": "Bash", "hooks": [guard("bash")]}]
    if fence:
        pre.append({"matcher": "*", "hooks": [guard("fence", *fence)]})
    return {"hooks": {"PreToolUse": pre,
                      "PostToolUse": [{"matcher": "*", "hooks": hook}]}}


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
    lines += ["- %s" % q["q"] for q in questions or []]
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
    for role in ("lead", "sub-agents", "CI fixes", "checker"):
        if role in roles:
            r = roles[role]
            entry = dict(r, model="/".join(sorted(r["models"])))
            out.append(_line("%s (%d)" % (role, r["count"]), entry))
    for call in calls:
        out += ["", "%s · %s%s · %s · %s" % (
            {"lead": "Round %s", "check": "Check %s"}.get(call["label"], "CI fix %s") % call["round"],
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
        data = self.read()
        data.update(fields)
        data["updated"] = time.time()
        self.state.write(GOAL_FILE, data)
        return data

    @property
    def journal(self):
        return self.state.path(JOURNAL_FILE)

    @property
    def log(self):
        return self.state.path(LOG_FILE)


def task_url(gid, board=None):
    return "https://app.asana.com/0/%s/%s" % (board or 0, gid)


def settings_from(control):
    """The models a new goal uses, from the repo's control file (the TUI's Setup
    tab): {model, subagent_model, check_model, check_effort}."""
    models = (control or {}).get("models") or {}
    return {"model": models.get("lead") or DEFAULT_MODEL,
            "subagent_model": models.get("subagent") or DEFAULT_SUBAGENT_MODEL,
            "check_model": models.get("check") or DEFAULT_CHECK_MODEL,
            "check_effort": models.get("check_effort") or DEFAULT_CHECK_EFFORT,
            "threshold": (control or {}).get("usage_threshold") or DEFAULT_THRESHOLD}


def create(main_root, ref, key, name, url=None, base=None, threshold=DEFAULT_THRESHOLD,
           model=DEFAULT_MODEL, subagent_model=DEFAULT_SUBAGENT_MODEL,
           check_model=DEFAULT_CHECK_MODEL, check_effort=DEFAULT_CHECK_EFFORT, now=None):
    """Write a new goal for the ticket `ref`. Returns its id; nothing runs yet, and the
    ticket itself is read when it starts."""
    gid, n = goal_id(key, name), 1
    while os.path.isdir(Goal(main_root, gid).state.dir):
        n += 1
        gid = "%s-%d" % (goal_id(key, name), n)
    goal = Goal(main_root, gid)
    goal.state.ensure()
    goal.update(id=gid, ref=ref, key=key, name=name, url=url or task_url(ref), base=base,
                threshold=threshold, model=model, subagent_model=subagent_model,
                check_model=check_model or model, check_effort=check_effort,
                created=now or time.time(), status="new",
                round=0, phase="planning")
    return gid


def find_goal(main_root, ref):
    """The goal on the list for the ticket `ref`, if there is one."""
    return next((g for g in list_goals(main_root) if g.get("ref") == ref and not g.get("parent")),
                None)


def create_part(main_root, parent, part, index, built):
    """Write the goal for one part of `parent`, unless it is written already.
    Returns its id; nothing runs yet."""
    gid = part_id(parent["id"], part["name"])
    goal = Goal(main_root, gid)
    if goal.read():
        return gid
    goal.state.ensure()
    goal.update(id=gid, parent=parent["id"], part=part["name"], part_index=index,
                depth=parent.get("depth", 0) + 1, ref=parent.get("ref"), key=parent.get("key"),
                name="part: %s" % part["name"], url=parent.get("url"), base=parent["branch"],
                ask=part_ask(parent, part, built), threshold=parent.get("threshold"),
                model=parent.get("model"), subagent_model=parent.get("subagent_model"),
                check_model=parent.get("check_model"), check_effort=parent.get("check_effort"),
                fence=parent.get("fence"), created=time.time(), status="new", round=0,
                phase="planning")
    return gid


def launch(main_root, gid):
    """Run a goal in its own session, so closing the TUI leaves it going. Returns
    its pid."""
    goal = Goal(main_root, gid)
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
        self.cut_off = None
        signal.signal(signal.SIGTERM, self.on_term)

    def on_term(self, *_):
        if self.child and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
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

    # setup

    def read_ticket(self):
        """The ask, from the ticket as it is now. Read once, when the goal starts."""
        st.step("Reading the ticket")
        ref = self.data["ref"]
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
        st.info("%d subtask(s) · %d comment(s) · %d attachment(s)"
                % (len(subtasks), len(comments), len(attachments)))
        self.set(ask=ask_from_ticket(task, self.data["url"], subtasks, comments, attachments),
                 name=task.get("name") or self.data.get("name"))

    def set_up(self):
        if not self.data.get("ask"):
            os.makedirs(self.goal.state.path("attachments"), exist_ok=True)
            self.read_ticket()
        if self.data.get("worktree") and os.path.isdir(self.data["worktree"]):
            return
        st.step("Setting up")
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
        key, name = self.data["key"], self.data["name"]
        base = st.resolve_base(self.main_root, self.data.get("base"))
        branch = "%s/goal-%s" % (key, st.slugify(name))
        worktree = st.worktree_path(self.main_root, self.goal.id)
        with st.repo_lock(self.main_root):
            st.git(["fetch", "origin"], cwd=self.main_root, check=False)
            st.git(["worktree", "add", worktree, "-b", branch, base], cwd=self.main_root)
        st.git(["commit", "--allow-empty", "-m", "%s :: start the goal" % key], cwd=worktree)
        st.git(["push", "-u", "origin", branch], cwd=worktree)
        st.info("created %s off %s in %s" % (branch, base, worktree))
        pr_url, error = st.create_draft_pr(key, name, self.data["url"], base, branch, worktree)
        if pr_url:
            st.info("draft PR: %s" % pr_url)
        else:
            st.warn("could not open the draft PR: %s" % error)
        self.set(base=base.replace("origin/", "", 1), branch=branch, worktree=worktree,
                 pr_url=pr_url)

    # usage

    def threshold(self):
        """The usage limit to pause at: the TUI's Setup tab's, read each time so a
        change reaches a goal already running, else the goal's own."""
        try:
            with open(os.path.join(self.main_root, st.CORTEX_DIRNAME, "queue", "control.json")) as f:
                value = json.load(f).get("usage_threshold")
        except (IOError, OSError, ValueError):
            value = None
        return value if isinstance(value, int) else self.data.get("threshold", DEFAULT_THRESHOLD)

    def usage(self):
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
                return
            until = worst["resets_at"] or time.time() + PAUSE_CHECK
            what = "%s at %d%%" % (worst["name"], worst["used"])
            if self.data.get("status") != "paused":
                st.step("Paused — %s" % what)
                st.info("resumes at %s" % time.strftime("%a %H:%M", time.localtime(until)))
            self.set(status="paused", doing="paused — %s, until %s"
                     % (what, time.strftime("%a %H:%M", time.localtime(until))))
            time.sleep(max(60, min(until - time.time() + 60, PAUSE_CHECK)))

    # agent calls

    def call(self, prompt, session, resume, label, model=None, effort=None):
        """One `claude -p` call. Returns (structured, stop_reason, error). A call
        cut off because the usage crossed the threshold returns stop_reason
        "usage"; its session carries on afterwards."""
        model = model or self.data["model"]
        flag = self.goal.state.path(WIND_FILE)
        if os.path.exists(flag):
            os.remove(flag)
        self.goal.state.write(SETTINGS_FILE, hook_settings(flag, short_model(
            self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL), self.data.get("fence") or ()))
        cmd = ["claude", "-p", "--output-format", "json", "--model", model,
               "--permission-mode", "bypassPermissions", "--max-turns", str(MAX_TURNS),
               "--add-dir", self.goal.state.dir, "--settings", self.goal.state.path(SETTINGS_FILE)]
        cmd += ["--effort", effort] if effort else []
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

    def record_call(self, label, model, effort, session, started, out=b""):
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
        calls.append({"v": 2, "label": label, "round": rounds, "model": model, "effort": effort,
                      "started": started, "session": session, "cost": cost,
                      "main": dict(main, seconds=time.time() - started), "subagents": agents})
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
            block, stop, error = self.call(prompt, session, resume, "lead")
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
                                           self.data.get("check_model"), self.data.get("check_effort"))
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

    def review(self):
        """The acceptance criteria, reviewed against the references before anything
        is built: (gaps, questions)."""
        self.set(status="checking", doing="reviewing the acceptance criteria")
        st.step("Reviewing the acceptance criteria")
        gaps, questions = self.judge("review", "review.md", review_verdict)
        st.info("review: %d problem(s), %d question(s)" % (len(gaps), len(questions)))
        for gap in gaps:
            st.info("- %s" % gap)
        return gaps, questions

    def check(self):
        """An independent check of the branch against the ask: (done, gaps, questions)."""
        self.set(status="checking", doing="checking the branch against the ask")
        st.step("Checking against the ask")
        done, gaps, questions = self.judge("check", "check.md", check_verdict)
        st.info("verdict: %s" % ("done" if done else "%d gap(s), %d question(s)"
                                 % (len(gaps), len(questions))))
        for gap in gaps:
            st.info("- %s" % gap)
        return done, gaps, questions

    def gate(self):
        """Sync the branch with its base, push it, mark the PR ready, and wait for
        its CI. Returns (None, None) when CI passes, else ("merge" | "ci", what failed)."""
        worktree, base = self.data["worktree"], self.data["base"]
        self.set(status="checking", doing="syncing with %s" % base)
        st.step("Syncing with %s" % base)
        st.git(["fetch", "origin", base], cwd=worktree, check=False)
        code, out, err = st.git(["merge", "--no-edit", "origin/%s" % base], cwd=worktree,
                                check=False)
        if code != 0:
            _, files, _ = st.git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree,
                                 check=False)
            if not files.strip():
                return "merge", ("You reported done, but the runner could not merge `origin/%s` into "
                        "your branch:\n\n```\n%s\n```\n\nCommit or remove what is in the "
                        "way, then report done again." % (base, (err or out).strip()[-2000:]))
            st.warn("the merge conflicts — back to the lead")
            return "merge", conflict_prompt("origin/%s" % base, files.split())
        self.push()
        pr_url = self.data.get("pr_url")
        if not pr_url:
            st.warn("no PR, so no CI to wait for")
            self.set(checks=[])
            return None, None
        if not self.data.get("ready"):
            # CI may run only on PRs ready for review; it stays ready from here on.
            st.run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
            self.set(ready=True)
            st.info("PR marked ready for review: %s" % pr_url)
        return self.wait_for_ci(pr_url)

    def wait_for_ci(self, pr_url):
        st.step("Waiting for CI")
        worktree = self.data["worktree"]
        _, head, _ = st.git(["rev-parse", "HEAD"], cwd=worktree, check=False)
        started = time.time()
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
                if (not rollup or pending == [CI_NOT_STARTED]) and waited >= CI_START:
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
            model = self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL
            prompt = ci_fix_prompt(self.data["branch"], fix.split("\n", 2)[2])
            _, before, _ = st.git(["rev-parse", "HEAD"], cwd=self.data["worktree"], check=False)
            while True:
                st.step("Fixing CI (%d/%d) on %s" % (attempt, CI_FIXES, short_model(model)))
                self.wait_for_usage()
                self.set(status="checking", doing="fixing CI, try %d" % attempt)
                _, stop, error = self.call(prompt, str(uuid.uuid4()), False, "ci-fix", model)
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
        st.step("Syncing with %s" % base)
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
            done = [p for p in parts if goals[p["name"]].get("status") == "done"]
            if len(done) == len(parts):
                st.info("every part is done")
                return parts_done_prompt([dict(p, summary=goals[p["name"]].get("summary"))
                                          for p in parts])
            running, ready = [], []
            for p in parts:
                g = goals[p["name"]]
                if g.get("status") == "done":
                    continue
                if g.get("pid") and st._pid_alive(g["pid"]):
                    running.append(p["name"])
                elif not g or g.get("status") == "new" or first:
                    ready.append(p)
                else:
                    reason = g.get("reason") if g.get("status") == "failed" else g.get("status")
                    self.ask_problem("part \"%s\" %s" % (p["name"], "failed" if g.get(
                        "status") == "failed" else "stopped"), reason)
                    ready.append(p)
            names = {p["name"] for p in done}
            built = [{"name": p["name"], "summary": goals[p["name"]].get("summary")} for p in done]
            for p in ready:
                if len(running) >= PARALLEL_PARTS:
                    break
                if set(p["after"]) <= names:
                    gid = create_part(self.main_root, self.data, p,
                                      [x["name"] for x in parts].index(p["name"]), built)
                    st.info("part \"%s\": starting" % p["name"])
                    launch(self.main_root, gid)
                    running.append(p["name"])
            self.set(status="parts", doing="parts: %d of %d done%s" % (
                len(done), len(parts), " · building %s" % ", ".join(running) if running else ""))
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
            st.git(["commit", "-m", "%s :: work before the parts" % self.data["key"]],
                   cwd=self.data["worktree"], check=False)
        st.step("Splitting into %d parts" % len(parts))
        for p in parts:
            st.info("- %s%s" % (p["name"], " (after %s)" % ", ".join(p["after"]) if p["after"] else ""))
        self.set(parts=parts, phase="parts")
        return parts

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
                 else SPLIT.replace("{{parts_file}}", self.goal.state.path(PARTS_FILE)))
        return {"ask": self.data["ask"], "branch": self.data["branch"],
                "where": where, "delivery": delivery, "split": split,
                "parts_file": self.goal.state.path(PARTS_FILE),
                "phase": PLANNING if self.data.get("phase") == "planning" else BUILDING,
                "base": self.data["base"], "journal": self.goal.journal,
                "checks": ("This part has run no CI: CI runs once, when the whole goal is "
                           "done. Judge the code, not test results." if part else
                           checks_text(self.data["base"], self.data.get("checks"))),
                "subagent_model": self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL,
                "subagent_alias": short_model(self.data.get("subagent_model") or DEFAULT_SUBAGENT_MODEL)}

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
        """Leave a question for the person and wait for their answer from the TUI."""
        asked_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        pending = self.goal.state.read("awaiting.json") or {}
        if pending.get("asked_at") and pending.get("kind") == record["kind"]:
            asked_at = pending["asked_at"]
        else:
            self.goal.state.write("awaiting.json", dict(record, asked_at=asked_at))
        self.set(status="waiting", doing="waiting on you")
        st.info("waiting on you — the question is on the TUI's Runs tab")
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
        st.step("Asking the goal's lead")
        parent = Goal(self.main_root, self.data["parent"])
        try:
            with open(parent.journal) as f:
                journal = f.read()
        except (IOError, OSError):
            journal = ""
        prompt = render(os.path.join(PROMPTS, "consult.md"), ask=parent.read().get("ask") or "",
                        journal=journal or "(empty)", part=self.data["part"],
                        questions="\n".join("- %s (%s)" % (q["q"], q.get("why") or "")
                                             for q in questions))
        for _ in range(3):
            self.wait_for_usage()
            block, stop, error = self.call(prompt, str(uuid.uuid4()), False, "consult",
                                           (parent.read() or {}).get("model"))
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
        st.step("Asking you")
        for q in questions:
            st.info("Q: %s" % q["q"])
        return self.wait_for_answer({"kind": "questions", "label": label, "questions": questions})

    def ask_problem(self, headline, detail=None):
        st.step("Stopped — %s" % headline)
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
        st.step("Finishing")
        if self.data.get("parent"):
            self.set(status="done", doing=block.get("summary") or "done",
                     summary=block.get("summary"), finished=time.time())
            return
        worktree, pr_url = self.data["worktree"], self.data.get("pr_url")
        self.push()
        if pr_url:
            body = "## Task\n%s\n\n%s\n" % (self.data["url"], block.get("summary") or "")
            st.run(["gh", "pr", "edit", pr_url, "--body", body], cwd=worktree, check=False)
            comment = (block.get("walkthrough") or "").strip()
            comment += "\n\n" + checks_section(self.data.get("checks"))
            if comment.strip():
                st.run(["gh", "pr", "comment", pr_url, "--body", st.mark(comment.strip())],
                       cwd=worktree, check=False)
            st.run(["gh", "pr", "ready", pr_url], cwd=worktree, check=False)
            st.info("PR ready: %s" % pr_url)
        self.set(status="done", doing=block.get("summary") or "done", finished=time.time())

    # the loop

    def run(self):
        try:
            self.set(pid=os.getpid(), status="setting-up", reason=None)
            self.set_up()
            pending = self.goal.state.read("awaiting.json") or {}
            if pending.get("kind") == "questions":
                prompt = answer_prompt(pending.get("questions"),
                                       self.wait_for_answer(pending))
            elif pending.get("kind") == "problem":
                prompt = "The person says:\n\n%s\n\n%s" % (self.wait_for_answer(pending), CONTINUE)
            elif self.data.get("phase") == "parts":
                prompt = self.run_parts()
                self.set(phase="building", status="working")
            else:
                prompt = self.first_prompt() if not self.data.get("session_used") else CONTINUE
            unchanged, checks, before = 0, 0, self.head()
            while True:
                self.set(round=self.data.get("round", 0) + 1)
                st.step("Round %d" % self.data["round"])
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
                    if problems:
                        prompt = planning_prompt(problems)
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
                    prompt = review_prompt(gaps, answers)
                    continue
                if report == "done":
                    unmet = unmet_criteria(self.read_journal())
                    if unmet:
                        st.warn("done, but %d acceptance criteria are not ticked" % len(unmet))
                        prompt = unmet_prompt(unmet)
                        continue
                    if self.data.get("parent"):
                        fix = self.sync_part()
                    else:
                        _, fix = self.sync_and_ci()
                    if fix:
                        checks += 1
                        if checks >= MAX_CHECKS:
                            answer = self.ask_problem(
                                "the branch still fails to sync or pass CI after %d tries"
                                % checks, fix)
                            prompt, checks = "The person says:\n\n%s\n\n%s" % (answer, fix), 0
                        else:
                            prompt = fix
                        continue
                    done, gaps, questions = self.check()
                    if done and self.data.get("parent"):
                        prompt = self.deliver()
                        if prompt:
                            continue
                    if done:
                        self.finish(block)
                        return 0
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
                    continue
                if unchanged >= STALL_ROUNDS:
                    answer = self.ask_problem("%d rounds in a row changed nothing" % unchanged)
                    prompt, unchanged = "The person says:\n\n%s\n\n%s" % (answer, CONTINUE), 0
                    continue
                prompt = CONTINUE
        except Stopped:
            self.set(status="stopped", reason="stopped", doing="stopped")
            return 1
        except st.Failure as e:
            self.set(status="failed", reason=str(e), doing=str(e).splitlines()[0][:200])
            st.warn(str(e))
            return 1
        finally:
            self.set(pid=None)


def render(path, **kwargs):
    with open(path) as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


# --- command line --------------------------------------------------------------

def main(argv):
    parser = argparse.ArgumentParser(prog="cortex goal", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="make a goal from an Asana ticket")
    new.add_argument("task", help="the ticket: its URL or gid")
    new.add_argument("--base", help="the branch to build on and open the PR into")
    new.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                     help="pause while any usage limit is at or over this percentage")
    new.add_argument("--model", default=DEFAULT_MODEL, help="the lead's model")
    new.add_argument("--subagent-model", default=DEFAULT_SUBAGENT_MODEL,
                     help="the default for the lead's sub-agents; it can ask for another")
    new.add_argument("--check-model", default=DEFAULT_CHECK_MODEL, help="the checker's model")
    new.add_argument("--check-effort", default=DEFAULT_CHECK_EFFORT,
                     choices=("low", "medium", "high", "xhigh", "max"), help="the checker's effort")
    new.add_argument("--start", action="store_true", help="start it in the background")
    new.add_argument("--repo", default=".")
    run = sub.add_parser("run", help="run or resume a goal in the foreground")
    run.add_argument("id")
    run.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    main_root = st.main_repo_root(os.path.abspath(args.repo))
    if args.cmd == "new":
        ref = st.asana(["ref", "parse", args.task], cwd=main_root)
        if not ref:
            parser.error("%r is not an Asana task" % args.task)
        ref = str(ref).strip()
        existing = find_goal(main_root, ref)
        if existing:
            parser.error("the ticket is already the goal %s" % existing["id"])
        task = st.asana(["task", "get", ref], cwd=main_root)
        gid = create(main_root, ref, st.task_key(task), task.get("name"), base=args.base,
                     threshold=args.threshold, model=args.model,
                     subagent_model=args.subagent_model, check_model=args.check_model,
                     check_effort=args.check_effort)
        if args.start:
            launch(main_root, gid)
        print(gid)
        return 0
    return Runner(main_root, args.id).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
