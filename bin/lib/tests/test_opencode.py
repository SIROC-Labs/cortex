import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import opencode_cli as oc  # noqa: E402

# What `opencode run --format json` printed against a mock endpoint, trimmed.
EVENTS = "\n".join(json.dumps(e) for e in [
    {"type": "step_start", "sessionID": "ses_1", "part": {"type": "step-start"}},
    {"type": "tool_use", "sessionID": "ses_1", "part": {"tool": "shell", "state": {
        "status": "error", "error": "Permission denied: shell"}}},
    {"type": "step_finish", "sessionID": "ses_1", "part": {"reason": "tool-calls", "cost": 0.00375, "tokens": {
        "input": 1000, "output": 50, "reasoning": 10, "cache": {"read": 200, "write": 0}}}},
    {"type": "text", "sessionID": "ses_1", "part": {"text": "Done.\n```json\n{\"status\": \"done\"}\n```"}},
    {"type": "step_finish", "sessionID": "ses_1", "part": {"reason": "stop", "cost": 0.001, "tokens": {
        "input": 500, "output": 20, "reasoning": 0, "cache": {"read": 0, "write": 0}}}},
]) + "\nnot json\n"


def effect(rules, action, resource):
    """The effect OpenCode gives: the last matching rule wins (whole-value wildcards)."""
    import fnmatch
    hit = [r["effect"] for r in rules if r["action"] == action and fnmatch.fnmatchcase(resource, r["resource"])]
    return hit[-1] if hit else "ask"


class TestModels(unittest.TestCase):
    def test_a_provider_model_runs_on_opencode_and_a_claude_one_does_not(self):
        self.assertTrue(oc.is_opencode("openrouter/qwen3-coder"))
        self.assertFalse(oc.is_opencode("claude-opus-5-5"))
        self.assertFalse(oc.is_opencode(None))

    def test_sessions_are_ours_with_opencode_s_prefix(self):
        self.assertEqual(oc.session_id("0f8e1c2a-9b7d-4e6f-8a1b-2c3d4e5f6a7b"),
                         "ses_0f8e1c2a9b7d4e6f8a1b2c3d4e5f6a7b")

    def test_the_command_runs_a_private_server_in_json_on_our_session(self):
        cmd = oc.command("mock/m", "Do it", "0f8e1c2a-9b7d-4e6f-8a1b-2c3d4e5f6a7b")
        self.assertEqual(cmd[1:], ["run", "--standalone", "--format", "json", "--model", "mock/m",
                                   "--agent", "build", "--session", "ses_0f8e1c2a9b7d4e6f8a1b2c3d4e5f6a7b",
                                   "Do it"])


class TestEvents(unittest.TestCase):
    def test_text_steps_usage_and_refusals_come_out_of_the_events(self):
        text, t = oc.parse_events(EVENTS)
        self.assertEqual(text, "Done.\n```json\n{\"status\": \"done\"}\n```")
        self.assertEqual((t["turns"], t["stop_reason"], t["denied"]), (2, "complete", ["shell"]))
        self.assertEqual(t["usage"], {"input": 1500, "output": 80, "cache_read": 200, "cache_write": 0,
                                      "cost_usd": 0.00475})
        self.assertNotIn("ok", t)

    def test_an_error_event_or_no_step_is_a_failure(self):
        _, t = oc.parse_events(json.dumps({"type": "error", "error": {"message": "Model not found"}}))
        self.assertEqual((t["ok"], t["error"]), (False, "Model not found"))
        self.assertEqual(oc.parse_events("")[1]["error"], "the run ended without a step")


class TestRules(unittest.TestCase):
    STATE = "/r/.cortex/state/goal-x"

    def rules(self, **kw):
        conf = oc.config(self.STATE, **kw)
        return conf["permissions"] + conf["agents"]["build"]["permissions"], conf

    def test_every_agent_stays_in_its_folders_and_never_pushes(self):
        rules, conf = self.rules()
        self.assertEqual(effect(rules, "shell", "npm test"), "allow")
        for push in ("git push origin x", "gh pr ready 9", "gh workflow run ci"):
            self.assertEqual(effect(rules, "shell", push), "deny", push)
        self.assertEqual(effect(rules, "external_directory", "/etc/*"), "deny")
        self.assertEqual(effect(rules, "edit", self.STATE + "/journal.md"), "allow")
        self.assertEqual(effect(rules, "question", "*"), "deny")
        self.assertEqual(effect(conf["permissions"], "edit", "src/a.ts"), "allow")

    def test_a_read_only_agent_edits_nothing(self):
        rules, _ = self.rules(readonly=True, subagents=False)
        self.assertEqual(effect(rules, "edit", "src/a.ts"), "deny")
        self.assertEqual(effect(rules, "subagent", "general"), "deny")
        self.assertEqual(effect(rules, "read", "src/a.ts"), "allow")

    def test_the_lead_in_the_build_reads_no_code_and_starts_no_agent(self):
        rules, conf = self.rules(lead_building=True)
        self.assertEqual(effect(rules, "read", "src/a.ts"), "deny")
        self.assertEqual(effect(rules, "read", "docs/TESTING.md"), "allow")
        self.assertEqual(effect(rules, "read", self.STATE + "/technical-plan.md"), "allow")
        self.assertEqual(effect(rules, "edit", self.STATE + "/journal.md"), "allow")
        self.assertEqual(effect(rules, "edit", "src/a.ts"), "deny")
        self.assertEqual(effect(rules, "shell", "cat src/a.ts"), "deny")
        self.assertEqual(effect(rules, "shell", "git log --oneline"), "allow")
        self.assertEqual(effect(rules, "subagent", "general"), "deny")
        self.assertEqual(effect(conf["permissions"], "read", "src/a.ts"), "allow")

    def test_providers_name_their_key_s_variable_never_the_key(self):
        conf = oc.config(self.STATE, providers=[
            {"id": "acme", "base_url": "https://llm.acme/v1", "key_env": "ACME_KEY", "models": ["q3"],
             "input_price": 0.5, "output_price": 2},
            {"id": "", "base_url": "x"}], subagent_model="acme/q3")
        self.assertEqual(conf["providers"], {"acme": {
            "name": "acme", "package": oc.PACKAGE, "settings": {"baseURL": "https://llm.acme/v1"},
            "env": ["ACME_KEY"], "models": {"q3": {"cost": {"input": 0.5, "output": 2.0}}}}})
        self.assertEqual(conf["agents"]["general"], {"model": "acme/q3"})
        self.assertNotIn("general", oc.config(self.STATE, subagent_model="claude-sonnet-5-5")["agents"])


if __name__ == "__main__":
    unittest.main()
