#!/usr/bin/env python3
#
# asked.py — what a goal asked the person and what they answered. The service keeps
# each answer it hands over; an earlier one is read back from the lead's sessions,
# where the runner passed it on. Read-only, apart from the answers the service keeps.

import calendar
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.dirname(HERE)
for tool in ("lib", "goal"):
    if os.path.join(BIN, tool) not in sys.path:
        sys.path.insert(0, os.path.join(BIN, tool))
import core as st  # noqa: E402
import goal as gl  # noqa: E402
import goal_view as gv  # noqa: E402

FILE = "answers.json"
TAILS = (gl.CONTINUE, "Correct the criteria, the plan and the parts first", "Then build the work, as the plan says",
         "Before you fix a gap", "The goal's lead answered:")
_SCANS = {}
_LOCK = threading.Lock()


def epoch(asked_at):
    """An `asked_at` time, 2026-11-17T15:14:15.676Z, in seconds; None when it is not one."""
    try:
        return calendar.timegm(time.strptime(str(asked_at)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def record(goal, awaiting, text, answers=None, note=None):
    """Keep an answer the service hands to the goal, with what it answers."""
    kept = goal.state.read(FILE) or []
    kept.append({"asked_at": awaiting.get("asked_at"), "kind": awaiting.get("kind"),
                 "questions": [q.get("q", "") for q in awaiting.get("questions") or []],
                 "headline": awaiting.get("headline"), "split": awaiting.get("split"),
                 "text": text, "answers": answers, "note": note, "at": time.time()})
    goal.state.write(FILE, kept)


def split_answers(text, n):
    """The answers to `n` questions in a text of numbered answers, "1. …" each on the
    line it starts, and what follows the last after a blank line: (answers, note), or
    (None, text) when it is not numbered so."""
    lines = (text or "").strip().splitlines()
    starts, want = [], 1
    for k, line in enumerate(lines):
        if want <= n and re.match(r"^%d\.\s" % want, line):
            starts.append(k)
            want += 1
    if not n or len(starts) != n or starts[0] != 0:
        return None, text
    answers = []
    for k, s in enumerate(starts):
        chunk = "\n".join(lines[s:starts[k + 1] if k + 1 < n else len(lines)])
        answers.append(re.sub(r"^\d+\.\s*", "", chunk).strip())
    last, _, note = answers[-1].partition("\n\n")
    answers[-1] = last.strip()
    return answers, note.strip() or None


def shown(kind, questions, text, answers=None, note=None):
    """An answer as the page shows it: {kind, items: [{q, a}], note, text, approved}."""
    out = {"kind": kind, "text": text, "note": note, "items": None,
           "approved": kind == "plan" and gl.approves(text)}
    if questions:
        if not answers or len(answers) != len(questions):
            answers, note = split_answers(text, len(questions))
            out["note"] = note if answers else (text or None)
        out["items"] = [{"q": q, "a": a} for q, a in zip(questions, answers or [None] * len(questions))]
    return out


def sent(goal, awaiting):
    """The answer sent to what the goal waits on, which it has not picked up yet; None
    when there is none."""
    if not (awaiting or {}).get("asked_at"):
        return None
    handed = goal.state.read(st.ANSWER_FILE) or {}
    if handed.get("asked_at") != awaiting["asked_at"]:
        return None
    kept = next((r for r in reversed(goal.state.read(FILE) or []) if r.get("asked_at") == awaiting["asked_at"]), {})
    return shown(awaiting.get("kind"), [q.get("q", "") for q in awaiting.get("questions") or []],
                 handed.get("text") or "", kept.get("answers"), kept.get("note"))


def _message_text(row):
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else ""


def _cut(text):
    ends = [text.find("\n\n" + t) for t in TAILS]
    ends = [e for e in ends if e >= 0]
    return (text[:min(ends)] if ends else text).strip()


def answers_in_prompt(text):
    """The person's answers a runner prompt hands the lead: [{kind, questions, text}]."""
    out = []
    for m in re.finditer(r"(?:You asked the person|The person was asked):\n\n(.*?)\n\nThey answered:\n\n",
                         text, re.S):
        questions = [re.sub(r" \(options: .*\)$", "", l[2:]) for l in m.group(1).splitlines() if l.startswith("- ")]
        rest = text[m.end():]
        nxt = re.search(r"\n\n(?:You asked the person|The person was asked):\n\n", rest)
        out.append({"kind": "questions", "questions": questions, "text": _cut(rest[:nxt.start()] if nxt else rest)})
    m = re.search(r"The person reviewed your plan and asked for changes:\n\n(.*?)\n\nRevise your journal", text, re.S)
    if m:
        out.append({"kind": "plan", "questions": [], "text": m.group(1).strip()})
    return out


def scan(path):
    """The answers handed over in a session's transcript, each with when: read on from
    where the last scan stopped."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    with _LOCK:
        seen = _SCANS.setdefault(path, {"offset": 0, "found": []})
        if size < seen["offset"]:
            seen.update(offset=0, found=[])
        if size == seen["offset"]:
            return list(seen["found"])
        try:
            with open(path, "rb") as f:
                f.seek(seen["offset"])
                data = f.read()
        except (IOError, OSError):
            return list(seen["found"])
        end = data.rfind(b"\n") + 1
        for raw in data[:end].splitlines():
            if b"They answered:" not in raw and b"asked for changes:" not in raw:
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if row.get("type") != "user":
                continue
            at = epoch(row.get("timestamp"))
            seen["found"] += [dict(a, at=at) for a in answers_in_prompt(_message_text(row))]
        seen["offset"] += end
        return list(seen["found"])


def handed_over(calls, data):
    """Every answer handed to the goal's leads, oldest first, from their sessions."""
    sessions = []
    for s in [c.get("session") for c in calls or [] if c.get("label") == "lead"] + [data.get("session")]:
        if s and s not in sessions:
            sessions.append(s)
    out = []
    for s in sessions:
        path = gv.session_path(s)
        if path:
            out += scan(path)
    return sorted(out, key=lambda a: a.get("at") or 0)


def attach(cs, goal, data, calls):
    """Each step that asked the person gets `qa`: what was asked and what they
    answered. The answers the service kept come first, then those read back from
    the lead's sessions."""
    asking = [c for c in cs if c["kind"] == "you" and "answered" in c["lines"]]
    if not asking:
        return cs
    kept = [dict(r, at=epoch(r.get("asked_at")) or r.get("at")) for r in goal.state.read(FILE) or []]
    used = set()
    found = None
    for c in asking:
        questions = [l[3:] for l in c["lines"] if l.startswith("Q: ")]
        plan = "ready for your review" in c["title"]
        if plan and any("the plan is approved" in l for l in c["lines"]):
            c["qa"] = shown("plan", [], "approved")
            continue
        kind = "plan" if plan else "questions" if questions else "problem"
        later = lambda r: (r.get("at") or 0) >= c["at"] - 120 and (  # noqa: E731
            not c.get("until") or (r.get("at") or 0) <= c["until"] + 120)
        match = next((r for n, r in enumerate(kept) if ("k", n) not in used and r.get("kind") == kind and later(r)
                      and (not questions or r.get("questions") == questions)), None)
        if match:
            used.add(("k", kept.index(match)))
            c["qa"] = shown(kind, questions, match.get("text") or "", match.get("answers"), match.get("note"))
            continue
        if kind == "problem":
            continue
        if found is None:
            found = handed_over(calls, data)
        match = next((a for n, a in enumerate(found) if ("t", n) not in used and a["kind"] == kind
                      and (a.get("at") or 0) >= c["at"] - 120
                      and (not questions or all(q in a["questions"] for q in questions))), None)
        if match:
            used.add(("t", found.index(match)))
            c["qa"] = shown(kind, questions, match["text"])
        elif questions:
            c["qa"] = shown(kind, questions, "")
    return cs
