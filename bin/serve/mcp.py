#!/usr/bin/env python3
#
# mcp.py — the service's actions as MCP tools, over JSON-RPC: what `POST /mcp`
# answers. Streamable HTTP without streams: every reply is one JSON body.

import json

import actions as ac

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "conductor", "version": "1"}

REPO = {"type": "string", "description": "the repo's id, from list_repos"}
GOAL = {"type": "string", "description": "the goal's id, from list_goals"}


def _tool(name, description, props=None, required=()):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": props or {},
                            "required": list(required), "additionalProperties": False}}


TOOLS = [
    _tool("list_repos", "The repositories conductor runs goals in."),
    _tool("add_repo", "Register a repository, by any folder in it.",
          {"path": {"type": "string"}}, ["path"]),
    _tool("list_goals", "The goals, newest first, with what each is doing, whether it waits on "
                        "the person, its cost and its PR. Without a repo, every repo's.",
          {"repo": REPO}),
    _tool("get_goal", "One goal in full: its state, what it waits on, its journal (references, "
                      "acceptance criteria, plan), its technical plan, its tasks and its parts.",
          {"repo": REPO, "goal": GOAL}, ["repo", "goal"]),
    _tool("goal_log", "The goal's log, what its runner did. Without `from`, its last 20 KB.",
          {"repo": REPO, "goal": GOAL, "from": {"type": "integer"}}, ["repo", "goal"]),
    _tool("start_goal", "Start a goal: what to build, in words and links, with "
                        "local files such as screenshots. The PR goes into the repo's Queue into "
                        "branch, else main, unless base names another.",
          {"repo": REPO, "prompt": {"type": "string"},
           "files": {"type": "array", "items": {"type": "string"},
                     "description": "local paths of files or folders, such as a prototype's folder"},
           "base": {"type": "string"}}, ["repo", "prompt"]),
    _tool("answer_goal", "Answer what a goal waits on the person for. Only when the person "
                         "gave the answer.",
          {"repo": REPO, "goal": GOAL, "text": {"type": "string"}}, ["repo", "goal", "text"]),
    _tool("tell_goal", "Send the person's note to a goal while it runs, to steer it: it "
                       "reaches the lead at once. `stop` stops its running coding tasks first. "
                       "Only with the person's words.",
          {"repo": REPO, "goal": GOAL, "text": {"type": "string"}, "stop": {"type": "boolean"}},
          ["repo", "goal", "text"]),
    _tool("approve_plan", "Approve the plan a goal waits on. Only when the person approved it.",
          {"repo": REPO, "goal": GOAL}, ["repo", "goal"]),
    _tool("stop_goal", "Stop a running goal; resume_goal carries it on later.",
          {"repo": REPO, "goal": GOAL}, ["repo", "goal"]),
    _tool("resume_goal", "Carry a stopped goal on from where it stopped.",
          {"repo": REPO, "goal": GOAL}, ["repo", "goal"]),
    _tool("get_settings", "The repo's settings: the branch goals go into, the usage limit, who "
                          "approves plans, and the models.", {"repo": REPO}, ["repo"]),
    _tool("set_settings", "Change some of the repo's settings.",
          {"repo": REPO, "settings": {"type": "object"}}, ["repo", "settings"]),
]


def call(name, args):
    """Run a tool. Returns its result as a JSON-able value."""
    args = args or {}
    if name == "list_repos":
        return ac.repos()
    if name == "add_repo":
        return ac.add_repo(args["path"])
    if name == "list_goals":
        if args.get("repo"):
            return ac.goals(ac.repo(args["repo"])["path"])
        return ac.all_goals()
    root = ac.repo(args["repo"])["path"]
    if name == "get_goal":
        return ac.detail(root, args["goal"])
    if name == "goal_log":
        return ac.log(root, args["goal"], args.get("from", -20000))
    if name == "start_goal":
        return {"goal": ac.start(root, args["prompt"], args.get("files") or [], args.get("base"))}
    if name == "answer_goal":
        return ac.answer(root, args["goal"], args["text"])
    if name == "tell_goal":
        return ac.tell(root, args["goal"], args["text"], bool(args.get("stop")))
    if name == "approve_plan":
        return ac.approve(root, args["goal"])
    if name == "stop_goal":
        return ac.stop(root, args["goal"])
    if name == "resume_goal":
        return ac.resume(root, args["goal"])
    if name == "get_settings":
        return ac.settings(root)
    if name == "set_settings":
        return ac.set_settings(root, args["settings"])
    raise ac.Problem(404, "no tool %s" % name)


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_one(msg):
    """One JSON-RPC message: its reply, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
    rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                  "capabilities": {"tools": {}}, "serverInfo": SERVER,
                  "instructions": "Conductor runs goals: a prompt implemented autonomously on one "
                                  "branch, into one PR. Start goals, follow them, and answer or "
                                  "approve only with the person's own words."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        if not any(t["name"] == name for t in TOOLS):
            return _error(rid, -32602, "no tool %s" % name)
        try:
            value = call(name, params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(value, indent=1, default=str)}],
                      "isError": False}
        except (ac.Problem, KeyError) as e:
            text = str(e) if isinstance(e, ac.Problem) else "missing argument %s" % e
            result = {"content": [{"type": "text", "text": text}], "isError": True}
    else:
        return _error(rid, -32601, "no method %s" % method)
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def handle(body):
    """A POST to /mcp: (status, reply or None). A batch gets a list back."""
    try:
        msg = json.loads(body or b"null")
    except ValueError:
        return 400, _error(None, -32700, "parse error")
    if isinstance(msg, list):
        replies = [r for r in (handle_one(m) for m in msg) if r]
        return (200, replies) if replies else (202, None)
    reply = handle_one(msg)
    return (200, reply) if reply else (202, None)
