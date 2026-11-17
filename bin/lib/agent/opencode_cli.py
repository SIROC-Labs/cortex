"""OpenCode backend — `opencode run` (v2) as a subprocess, for any provider OpenCode
reaches with an API key: OpenAI, OpenRouter, any OpenAI-compatible endpoint.

A model named `provider/model` runs here; a Claude model name runs through
`claude -p`. Each run gets a private server (`--standalone`) and its whole
configuration inline (`OPENCODE_CONFIG_CONTENT`): the custom providers, the
permission rules that stand in for Claude Code's hooks, and the sub-agents' model.
Keys stay in the environment: the configuration names the variable, never the key.
"""

import json
import os
import re

PACKAGE = "@opencode/ai/providers/openai-compatible"
# No agent pushes or starts CI: the runner does, once, when the work is checked.
PUSHES = ("git push *", "gh pr ready *", "gh pr merge *", "gh pr create *", "gh workflow run *",
          "gh run rerun *")
# How the lead in the build would read code through the shell; Markdown it may read.
READS = ("cat *", "head *", "tail *", "less *", "more *", "grep *", "rg *", "sed *", "awk *", "find *")
# OpenCode's built-in sub-agents, which take the goal's sub-agent model.
SUBAGENTS = ("general", "explore")


def is_opencode(model):
    """Whether a model runs through OpenCode: it is named `provider/model`."""
    return bool(model) and "/" in model


def binary():
    return os.environ.get("COND_OPENCODE") or "opencode"


def session_id(uuid_text):
    """OpenCode's id for one of our sessions: it must start with `ses`."""
    return "ses_" + re.sub(r"[^0-9a-fA-F]", "", uuid_text or "")


def _rule(action, resource, effect):
    return {"action": action, "resource": resource, "effect": effect}


def base_rules(state_dir, extra_dirs=()):
    """Every agent of a run: the work happens in its worktree (OpenCode's location)
    and the goal's state folder; nothing outside them, no pushes, no questions."""
    rules = [_rule(a, "*", "allow") for a in ("read", "glob", "grep", "edit", "shell", "webfetch",
                                              "websearch", "skill", "subagent")]
    rules += [_rule("question", "*", "deny"), _rule("external_directory", "*", "deny")]
    for folder in (state_dir,) + tuple(extra_dirs):
        if folder:
            rules += [_rule(a, folder.rstrip("/") + "/*", "allow")
                      for a in ("external_directory", "read", "edit")]
    rules += [_rule("shell", p, "deny") for p in PUSHES]
    return rules


def role_rules(state_dir, readonly=False, lead_building=False, subagents=True):
    """The main agent's own rules, after the base ones. A read-only agent edits
    nothing; the lead in the build reads no code, edits only its journal and
    technical plan, and starts no sub-agents."""
    rules = []
    if not subagents or lead_building:
        rules.append(_rule("subagent", "*", "deny"))
    if readonly or lead_building:
        rules.append(_rule("edit", "*", "deny"))
    if lead_building:
        rules += [_rule(a, "*", "deny") for a in ("read", "glob", "grep")]
        rules += [_rule("read", "*.md", "allow"), _rule("read", state_dir.rstrip("/") + "/*", "allow"),
                  _rule("edit", state_dir.rstrip("/") + "/*", "allow")]
        rules += [_rule("shell", p, "deny") for p in READS]
    return rules


def providers_config(providers):
    """The custom providers, from the settings: [{id, base_url, key_env, models,
    input_price, output_price}] (prices in dollars per million tokens)."""
    out = {}
    for p in providers or []:
        if not (p.get("id") and p.get("base_url")):
            continue
        cost = {k: float(p[k + "_price"]) for k in ("input", "output")
                if isinstance(p.get(k + "_price"), (int, float))}
        out[p["id"]] = {"name": p.get("name") or p["id"], "package": PACKAGE,
                        "settings": {"baseURL": p["base_url"]},
                        "models": {m: ({"cost": cost} if cost else {}) for m in p.get("models") or []}}
        if p.get("key_env"):
            out[p["id"]]["env"] = [p["key_env"]]
    return out


def config(state_dir, providers=(), subagent_model=None, readonly=False, lead_building=False,
           subagents=True, extra_dirs=()):
    """The whole configuration of one run, for OPENCODE_CONFIG_CONTENT."""
    agents = {"build": {"permissions": role_rules(state_dir, readonly, lead_building, subagents)}}
    if is_opencode(subagent_model):
        agents.update({name: {"model": subagent_model} for name in SUBAGENTS})
    out = {"permissions": base_rules(state_dir, extra_dirs), "agents": agents}
    custom = providers_config(providers)
    if custom:
        out["providers"] = custom
    return out


def command(model, prompt, session):
    return [binary(), "run", "--standalone", "--format", "json", "--model", model,
            "--agent", "build", "--session", session_id(session), prompt]


def environment(base, conf):
    return dict(base, OPENCODE_CONFIG_CONTENT=json.dumps(conf))


def parse_events(raw):
    """A run's JSON lines: (its text, telemetry {ok, error, turns, stop_reason,
    usage, denied}). Text is every text part, in order; usage sums each step's
    tokens and cost. A run that reports an error, or ends with no step, failed."""
    texts, steps, denied, errors, reason = [], 0, [], [], None
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0}
    for line in (raw or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part") or {}
        kind = event.get("type")
        if kind == "text" and part.get("text"):
            texts.append(part["text"])
        elif kind == "step_finish":
            steps += 1
            reason = part.get("reason") or reason
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            usage["input"] += int(tokens.get("input") or 0)
            usage["output"] += int(tokens.get("output") or 0) + int(tokens.get("reasoning") or 0)
            usage["cache_read"] += int(cache.get("read") or 0)
            usage["cache_write"] += int(cache.get("write") or 0)
            usage["cost_usd"] += float(part.get("cost") or 0)
        elif kind == "tool_use":
            state = part.get("state") or {}
            if state.get("status") == "error" and "Permission denied" in str(state.get("error")):
                denied.append(part.get("tool") or "?")
        elif kind == "error":
            errors.append(((event.get("error") or {}).get("message") or "the run failed").strip())
    telemetry = {"turns": steps, "denied": denied,
                 "stop_reason": "complete" if reason == "stop" else reason,
                 "usage": usage if any(usage.values()) else None}
    if errors or not steps:
        telemetry["ok"] = False
        telemetry["error"] = "; ".join(errors) or "the run ended without a step"
    return "\n".join(texts), telemetry
