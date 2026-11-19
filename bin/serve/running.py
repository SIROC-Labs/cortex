#!/usr/bin/env python3
#
# running.py — what each running agent of a goal does, in one plain line from a small
# model, asked only while someone looks at the goal; and whether its lead ever changed
# a repo file itself, which it must not: it only reads and writes its journal.

import glob
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.dirname(HERE)
for tool in ("lib", "goal"):
    if os.path.join(BIN, tool) not in sys.path:
        sys.path.insert(0, os.path.join(BIN, tool))
import goal_view as gv  # noqa: E402
from agent import opencode_cli as oc  # noqa: E402
from agent.claude_cli import parse_envelope  # noqa: E402

EVERY = 45
CLAUDE_MODEL = "haiku"
TIMEOUT = 90
WORDS = 24
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
_SUMMARIES = {}
_EDITS = {}
_PATHS = {}
_LOCK = threading.Lock()


def model_for(data, control):
    """The model that sums up a goal's agents: Haiku on Claude Code; on OpenCode the
    configured model with the lowest price, or None when no model has one."""
    if not oc.is_opencode(data.get("model")):
        return CLAUDE_MODEL
    priced = []
    for p in (control or {}).get("providers") or []:
        prices = [p.get(k) for k in ("input_price", "output_price") if isinstance(p.get(k), (int, float))]
        if p.get("id") and p.get("models") and prices:
            priced.append((sum(prices), "%s/%s" % (p["id"], p["models"][0])))
    return min(priced)[1] if priced else None


def prompt_for(role, brief, said, actions):
    return ("An agent works on a software change. In one plain sentence of at most %d words, say "
            "what it is doing right now and what for, for a person who does not read its commands: "
            "no commands, flags or file paths. Reply with the sentence only.\n\nThe agent: %s\n\n"
            "Its brief, the part that says what to do:\n%s\n\nWhat it said last:\n%s\n\n"
            "Its last actions, oldest first:\n%s"
            % (WORDS - 6, role, brief or "(none)", "\n".join(said) or "(nothing)",
               "\n".join("- " + a for a in actions) or "(none)"))


def command(model, prompt):
    if oc.is_opencode(model):
        return oc.command(model, prompt, str(uuid.uuid4()))
    return ["claude", "-p", "--output-format", "json", "--model", model, "--max-turns", "1", "--tools", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}', "--no-session-persistence",
            "--setting-sources", "", "--", prompt]


def reply(model, out):
    raw = out.decode("utf-8", "replace") if isinstance(out, bytes) else out or ""
    text, telemetry = oc.parse_events(raw) if oc.is_opencode(model) else parse_envelope(raw)
    if telemetry.get("ok") is False:
        return None
    words = " ".join((text or "").split()).split()
    return " ".join(words[:WORDS]) or None


def _ask(key, model, entry, control, runner):
    text = None
    try:
        path = entry["path"]
        actions, said = gv.recent(gv._read_tail(path, 64 * 1024))
        prompt = prompt_for(entry.get("role") or "an agent", gv.brief_of(path, 800, end=entry.get("role") == "Lead"),
                            said, actions)
        env = os.environ
        if oc.is_opencode(model):
            env = oc.environment(os.environ, oc.config(tempfile.gettempdir(), (control or {}).get("providers") or (),
                                                       readonly=True, subagents=False))
        proc = (runner or subprocess.run)(command(model, prompt), cwd=tempfile.gettempdir(), env=env,
                                           stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT)
        text = reply(model, proc.stdout)
    except Exception:  # noqa: BLE001 — no summary is shown, the page goes on
        text = None
    with _LOCK:
        cached = _SUMMARIES.setdefault(key, {})
        cached["pending"] = False
        if text:
            cached["text"] = text


def summarize(live, data, control, now=None, runner=None, spawn=None):
    """Give each running agent its `summary`: the last line a small model wrote on what
    it does. A new one is asked for in the background when the agent moved since, at
    most every EVERY seconds; an agent that did nothing new costs nothing."""
    model = model_for(data, control)
    now = now or time.time()
    for entry in live or []:
        entry["summary"] = None
        key, moved = entry.get("path"), entry.get("at")
        if not (model and key):
            continue
        with _LOCK:
            cached = _SUMMARIES.setdefault(key, {})
            ask = moved and cached.get("moved") != moved and not cached.get("pending") \
                and now - cached.get("asked", 0) >= EVERY
            if ask:
                cached.update(pending=True, asked=now, moved=moved)
        if ask:
            (spawn or (lambda f, a: threading.Thread(target=f, args=a, daemon=True).start()))(
                _ask, (key, model, dict(entry), control, runner))
        with _LOCK:
            entry["summary"] = _SUMMARIES[key].get("text")
    return live


def _inside(path, folder):
    return bool(folder) and (path == folder or path.startswith(folder.rstrip(os.sep) + os.sep))


def repo_file(path, main_root, worktree):
    """Whether an agent's file is the repo's: in the goal's worktree, or in the repo
    outside conductor's own folder, where the goal's journal and state are."""
    path = os.path.abspath(path or "")
    if _inside(path, worktree):
        return True
    return _inside(path, main_root) and not _inside(path, os.path.join(main_root, ".cortex"))


def edits_in(path, main_root, worktree):
    """The repo files a transcript's agent changed, by its edit tools that went
    through: [{file, tool, at}]. Read on from where the last read stopped."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    with _LOCK:
        seen = _EDITS.setdefault(path, {"offset": 0, "asked": {}, "edits": []})
        if size < seen["offset"]:
            seen.update(offset=0, asked={}, edits=[])
        if size == seen["offset"]:
            return list(seen["edits"])
        try:
            with open(path, "rb") as f:
                f.seek(seen["offset"])
                data = f.read()
        except (IOError, OSError):
            return list(seen["edits"])
        end = data.rfind(b"\n") + 1
        for raw in data[:end].splitlines():
            if b"tool_use" not in raw and b"tool_result" not in raw:
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            content = (row.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in EDIT_TOOLS:
                    args = block.get("input") or {}
                    file = args.get("file_path") or args.get("notebook_path")
                    if file and repo_file(file, main_root, worktree):
                        seen["asked"][block.get("id")] = {"file": file, "tool": block["name"],
                                                         "at": gv._when(row.get("timestamp"))}
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in seen["asked"]:
                    edit = seen["asked"].pop(block["tool_use_id"])
                    if not block.get("is_error"):
                        seen["edits"].append(edit)
        seen["offset"] += end
        return list(seen["edits"])


def _path(session, now):
    known = _PATHS.get(session)
    if known and known[0]:
        return known[0]
    if known and now - known[1] < 60:
        return None
    found = gv.session_path(session)
    _PATHS[session] = (found, now)
    return found


def lead_edits(main_root, data, calls, now=None):
    """Every repo file the goal's lead, or a sub-agent it started, changed itself:
    [{file, tool, at, round, by}], oldest first."""
    now = now or time.time()
    rounds, order = {}, []
    for c in calls or []:
        if c.get("label") == "lead" and c.get("session"):
            rounds.setdefault(c["session"], []).append((c.get("started") or 0, c.get("round")))
            if c["session"] not in order:
                order.append(c["session"])
    if data.get("session") and data["session"] not in order:
        order.append(data["session"])
        rounds[data["session"]] = [(0, data.get("round"))]
    worktree = data.get("worktree")
    out = []
    for session in order:
        path = _path(session, now)
        if not path:
            continue
        found = [dict(e, by="lead") for e in edits_in(path, main_root, worktree)]
        for sub in sorted(glob.glob(os.path.join(path[:-len(".jsonl")], "subagents", "agent-*.jsonl"))):
            found += [dict(e, by="a sub-agent of the lead") for e in edits_in(sub, main_root, worktree)]
        for e in found:
            started = [r for t, r in sorted(rounds[session], key=lambda x: x[0]) if t <= (e.get("at") or now) + 1]
            e["round"] = started[-1] if started else rounds[session][0][1]
            for root in (worktree, main_root):
                if _inside(e["file"], root):
                    e["file"] = os.path.relpath(e["file"], root)
                    break
        out += found
    return sorted(out, key=lambda e: e.get("at") or 0)
