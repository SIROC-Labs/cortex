#!/usr/bin/env python3
#
# discuss.py — talk one question, or a goal's technical plan, through with an agent
# before answering it. Each thread is a session of its own, apart from the goal's:
# it gets only the context its topic needs, reads but changes nothing, and runs in
# the background so the page stays live. The answer stays the person's.

import json
import os
import re
import subprocess
import threading
import time
import uuid

import actions as ac

gl, st, oc = ac.gl, ac.st, ac.oc

DIR = "discussions"
TOPIC = re.compile(r"^(plan|q([1-9][0-9]?))$")
ASK_MAX = 12000
SECTION_MAX = 12000
PLAN_MAX = 60000
REPLY_TIMEOUT = 15 * 60
MAX_TURNS = 30
READ_TOOLS = "Read,Grep,Glob"
NO_TOOLS = "Edit,Write,NotebookEdit,Bash,Agent,Task,WebFetch,WebSearch"
_LOCK = threading.Lock()
_RUNNING = set()

INTRO = """You help a person think one thing through before they decide it. It belongs to a
conductor goal: an autonomous run that builds what the person asked for. The goal
waits on the person's decision. You are not the goal's agent, and nothing you say
reaches it: the person decides and answers it themselves.

- Answer what the person asks, and only that. Be short and concrete.
- When they ask for your view, give it, with the reasons, and say what each choice
  means for what gets built.
- Say where a fact comes from: the ask, a file, the code. Say so when you do not know.
- You read, never change anything. The goal's branch is your working directory. %s

%s"""


def _clip(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n\n[cut here: read the rest from its file]"


def _section(journal, heading):
    lines = gl.section_text(journal, heading)
    return "\n".join(lines) if lines else ""


def key_of(topic, awaiting):
    """The thread's key: a topic of the question or plan waiting now starts a new
    thread each time the goal asks again."""
    asked = re.sub(r"[^0-9A-Za-z]", "", str((awaiting or {}).get("asked_at") or "")) or "now"
    return "%s-%s" % (topic, asked)


def context(goal, data, topic, awaiting):
    """What the thread's agent starts from: the ask, then the question or the plan."""
    journal = ""
    try:
        with open(goal.journal) as f:
            journal = f.read()
    except (IOError, OSError):
        pass
    files = goal.state.path(gl.INPUTS_DIR)
    where = ("The files given with the ask are in `%s`; read them only as far as the "
             "question needs." % files) if os.path.isdir(files) else ""
    parts = ["## The ask", "", _clip(data.get("ask") or data.get("prompt"), ASK_MAX), ""]
    if topic == "plan":
        plan = ""
        try:
            with open(goal.state.path(gl.TECHNICAL_FILE)) as f:
                plan = f.read()
        except (IOError, OSError):
            pass
        parts += ["## The plan the person reviews", "",
                  "### Steps", "", _section(journal, "Plan") or "(none)", "",
                  "### Acceptance criteria", "", _clip(_section(journal, "Acceptance criteria"), SECTION_MAX)
                  or "(none)", "",
                  "### Technical plan", "", _clip(plan, PLAN_MAX) or "(none)", ""]
        task = ("The person reviews this plan before anything is built. They will approve it, "
                "or say what to change.")
    else:
        n = int(topic[1:])
        questions = (awaiting or {}).get("questions") or []
        if not 1 <= n <= len(questions):
            raise ac.Problem(404, "no question %d waits" % n)
        q = questions[n - 1]
        lines = ["## The question", "", q.get("q", "")]
        if q.get("why"):
            lines += ["", "Why it is asked: " + q["why"]]
        for o in q.get("options") or []:
            lines += ["", "- %s%s" % (o.get("label", ""), " → " + o["means"] if o.get("means") else "")]
            lines += ["  %d. %s" % (i, f) for i, f in enumerate(o.get("flow") or [], 1)]
        if q.get("recommend"):
            lines += ["", "The goal suggests: " + q["recommend"]]
        parts += lines + ["", "## From the goal's journal", "",
                          "### References", "", _clip(_section(journal, "References"), SECTION_MAX) or "(none)", "",
                          "### Decisions", "", _clip(_section(journal, "Decisions"), SECTION_MAX) or "(none)", ""]
        task = ("The person answers this question: with one of its options, or in their own "
                "words.")
    return INTRO % (where, task + "\n\n" + "\n".join(parts))


def thread_path(goal, key):
    return goal.state.path(os.path.join(DIR, key + ".json"))


def read(main_root, gid, topic):
    """The thread on `topic` for what the goal waits on now: {key, messages, pending, error}."""
    if not TOPIC.match(topic or ""):
        raise ac.Problem(404, "no topic %s" % topic)
    goal, _ = ac.the_goal(main_root, gid)
    key = key_of(topic, goal.state.read("awaiting.json"))
    thread = goal.state.read(os.path.join(DIR, key + ".json")) or {"messages": []}
    return {"key": key, "messages": thread.get("messages") or [],
            "pending": (main_root, gid, key) in _RUNNING, "error": thread.get("error")}


def model_of(data):
    """The thread's model: the goal's lead model, so the advice is as good as the plan."""
    return data.get("model") or gl.DEFAULT_MODEL


def command(model, session, prompt, resume, cwd, state_dir):
    if oc.is_opencode(model):
        return oc.command(model, prompt, session)
    cmd = ["claude", "-p", "--output-format", "json", "--model", model, "--permission-mode", "dontAsk",
           "--max-turns", str(MAX_TURNS), "--allowedTools", READ_TOOLS, "--disallowedTools", NO_TOOLS,
           "--add-dir", state_dir, "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}']
    cmd += ["--resume", session] if resume else ["--session-id", session]
    return cmd + ["--", prompt]


def reply_text(model, out):
    raw = out.decode("utf-8", "replace")
    if oc.is_opencode(model):
        text, telemetry = oc.parse_events(raw)
    else:
        text, telemetry = gl.parse_envelope(raw)
    if telemetry.get("ok") is False or not text.strip():
        raise RuntimeError(telemetry.get("error") or "no reply")
    return text.strip()


def say(main_root, gid, topic, text, runner=None):
    """Add the person's message to the thread and start the agent's reply in the
    background. Returns the thread as `read` gives it."""
    if not TOPIC.match(topic or ""):
        raise ac.Problem(404, "no topic %s" % topic)
    if not (text or "").strip():
        raise ac.Problem(400, "an empty message")
    goal, data = ac.the_goal(main_root, gid)
    awaiting = goal.state.read("awaiting.json")
    key = key_of(topic, awaiting)
    name = os.path.join(DIR, key + ".json")
    with _LOCK:
        if (main_root, gid, key) in _RUNNING:
            raise ac.Problem(409, "the last message is still being answered")
        thread = goal.state.read(name) or {"topic": topic, "messages": []}
        first = not thread.get("session")
        prompt = (context(goal, data, topic, awaiting) + "\n\n## The person asks\n\n" + text.strip()) \
            if first else text.strip()
        thread.setdefault("session", str(uuid.uuid4()))
        thread["messages"] = (thread.get("messages") or []) + [{"role": "person", "text": text.strip(), "at": time.time()}]
        thread["error"] = None
        os.makedirs(goal.state.path(DIR), exist_ok=True)
        goal.state.write(name, thread)
        _RUNNING.add((main_root, gid, key))
    model = model_of(data)
    cwd = data.get("worktree") if data.get("worktree") and os.path.isdir(data["worktree"]) else goal.state.dir
    cmd = command(model, thread["session"], prompt, not first, cwd, goal.state.dir)
    env = os.environ
    if oc.is_opencode(model):
        env = oc.environment(os.environ, oc.config(goal.state.dir, readonly=True, subagents=False))

    def work():
        error, answer = None, None
        try:
            proc = (runner or subprocess.run)(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                              capture_output=True, timeout=REPLY_TIMEOUT)
            answer = reply_text(model, proc.stdout)
        except Exception as e:  # noqa: BLE001 — the thread says what went wrong
            error = str(e)[:500] or type(e).__name__
        with _LOCK:
            current = goal.state.read(name) or thread
            if answer:
                current["messages"] = (current.get("messages") or []) + [
                    {"role": "agent", "text": answer, "at": time.time()}]
            current["error"] = error
            goal.state.write(name, current)
            _RUNNING.discard((main_root, gid, key))
    if runner:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()
    return read(main_root, gid, topic)


def clear(main_root, gid, topic):
    """Put the thread on `topic` away, so the talk starts over. Returns the new, empty
    thread as `read` gives it."""
    if not TOPIC.match(topic or ""):
        raise ac.Problem(404, "no topic %s" % topic)
    goal, _ = ac.the_goal(main_root, gid)
    key = key_of(topic, goal.state.read("awaiting.json"))
    with _LOCK:
        if (main_root, gid, key) in _RUNNING:
            raise ac.Problem(409, "the last message is still being answered")
        ac.retire_discussions(goal, key + ".")
    return read(main_root, gid, topic)
