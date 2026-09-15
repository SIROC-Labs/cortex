#!/usr/bin/env python3
#
# Tests for the agent seam: the neutral types, the registry, and each backend's
# translation layer. No network and no model — the two real backends are probed
# only through their pure mapping tables and their `available()` reporting.
#
#   python3 tests/test_agent.py

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import (  # noqa: E402
    AgentRequest, AgentResult, available_backends, backend_names,
    extract_last_json_block, get_backend, tools_for,
)
from agent.base import TOOLS_EDIT, TOOLS_FULL, TOOLS_READ_ONLY  # noqa: E402
from agent.claude_cli import build_command, parse_envelope  # noqa: E402
from agent.claude_sdk import _denial_name  # noqa: E402


class TestRegistry(unittest.TestCase):
    def test_known_backends(self):
        self.assertEqual(set(backend_names()), {"claude-sdk", "claude-cli", "echo"})

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError) as ctx:
            get_backend("gpt-9")
        self.assertIn("unknown backend", str(ctx.exception))

    def test_every_backend_constructs_and_reports_availability(self):
        for name, usable, reason in available_backends():
            self.assertIsInstance(usable, bool)
            if not usable:
                self.assertTrue(reason, "%s must explain why it is unusable" % name)

    def test_backend_names_match_their_registry_key(self):
        for name in backend_names():
            self.assertEqual(get_backend(name).name, name)


class TestEchoBackend(unittest.TestCase):
    def test_returns_a_well_formed_result(self):
        result = get_backend("echo").run(AgentRequest(prompt="hi", cwd="."))
        self.assertTrue(result.ok)
        self.assertEqual(result.backend, "echo")
        self.assertIn("summary", result.structured)


class TestToolVocabulary(unittest.TestCase):
    def test_autonomy_levels_widen(self):
        self.assertEqual(tools_for("read-only"), TOOLS_READ_ONLY)
        self.assertEqual(tools_for("edit"), TOOLS_EDIT)
        self.assertEqual(tools_for("full"), TOOLS_FULL)
        self.assertLess(len(TOOLS_READ_ONLY), len(TOOLS_EDIT))
        self.assertLess(len(TOOLS_EDIT), len(TOOLS_FULL))

    def test_only_full_can_run_commands(self):
        self.assertNotIn("run_command", tools_for("edit"))
        self.assertIn("run_command", tools_for("full"))

    def test_unknown_autonomy_falls_back_to_edit(self):
        self.assertEqual(tools_for("nonsense"), TOOLS_EDIT)

    def test_every_neutral_tool_maps_in_both_real_backends(self):
        from agent.claude_cli import TOOL_MAP as CLI_MAP
        from agent.claude_sdk import TOOL_MAP as SDK_MAP
        for tool in TOOLS_FULL:
            self.assertIn(tool, SDK_MAP)
            self.assertIn(tool, CLI_MAP)


class TestDenialNames(unittest.TestCase):
    def test_dict_denial(self):
        self.assertEqual(_denial_name({"tool_name": "Bash"}), "Bash")

    def test_object_denial(self):
        class Denial(object):
            tool_name = "Write"
        self.assertEqual(_denial_name(Denial()), "Write")

    def test_unknown_shape_still_produces_something_printable(self):
        self.assertTrue(_denial_name(["weird"]))


class TestResultSummary(unittest.TestCase):
    def test_omits_unknown_telemetry_rather_than_faking_zero(self):
        summary = AgentResult(backend="x", model="m").summary()
        self.assertNotIn("$", summary)
        self.assertNotIn("turn", summary)

    def test_includes_what_is_known(self):
        summary = AgentResult(backend="x", model="m", turns=3,
                              duration_s=1.5).summary()
        for fragment in ("x", "m", "3 turns", "1.5s"):
            self.assertIn(fragment, summary)

    def test_singular_turn(self):
        self.assertIn("1 turn ", AgentResult(backend="x", turns=1).summary() + " ")


class TestExtractLastJsonBlock(unittest.TestCase):
    def test_extracts_and_prefers_the_last(self):
        self.assertEqual(
            extract_last_json_block('```json\n{"n": 1}\n```\n```json\n{"n": 2}\n```'),
            {"n": 2})

    def test_skips_unparseable(self):
        self.assertEqual(
            extract_last_json_block('```json\n{"n": 1}\n```\n```json\nnope\n```'),
            {"n": 1})

    def test_none_when_absent(self):
        self.assertIsNone(extract_last_json_block("prose only"))
        self.assertIsNone(extract_last_json_block(None))


class TestBackendContract(unittest.TestCase):
    def test_unavailable_backend_reports_rather_than_raises(self):
        """A backend whose dependency is missing must still return a result."""
        backend = get_backend("claude-sdk")
        usable, _ = backend.available()
        if usable:
            self.skipTest("claude-agent-sdk is installed here")
        result = backend.run(AgentRequest(prompt="x", cwd="."))
        self.assertFalse(result.ok)
        self.assertIn("claude-agent-sdk", result.error)


class TestCLIEnvelope(unittest.TestCase):
    """The CLI backend's own wire format. Nothing else covers it, and getting the
    unwrapping wrong yields a successful run whose result block is silently lost."""

    def test_unwraps_envelope_then_finds_block(self):
        envelope = json.dumps({
            "type": "result",
            "result": 'Done.\n```json\n{"summary": "shipped"}\n```',
        })
        text, _ = parse_envelope(envelope)
        self.assertIn("Done.", text)
        self.assertEqual(extract_last_json_block(text), {"summary": "shipped"})

    def test_falls_back_to_raw_text_when_not_an_envelope(self):
        raw = 'Done.\n```json\n{"summary": "shipped"}\n```'
        text, telemetry = parse_envelope(raw)
        self.assertEqual(text, raw)
        self.assertEqual(telemetry, {})
        self.assertEqual(extract_last_json_block(text), {"summary": "shipped"})

    def test_no_block_yields_none_result_but_keeps_text(self):
        envelope = json.dumps({"result": "I could not do it."})
        text, _ = parse_envelope(envelope)
        self.assertEqual(text, "I could not do it.")
        self.assertIsNone(extract_last_json_block(text))

    def test_reads_the_turn_count_from_the_envelope(self):
        _, telemetry = parse_envelope(
            json.dumps({"result": "done", "num_turns": 7}))
        self.assertEqual(telemetry["turns"], 7)

    def test_absent_turn_count_is_left_absent_not_zeroed(self):
        _, telemetry = parse_envelope(json.dumps({"result": "done"}))
        self.assertIsNone(telemetry["turns"])


class TestCLIStopReason(unittest.TestCase):
    """A run stopped by the turn ceiling is an intermission, not a failure, and
    not a success either. Swallowing it yields a run that looks finished and has
    no result block to show for it."""

    def test_max_turns_is_reported_as_a_stop_reason_not_an_error(self):
        _, telemetry = parse_envelope(json.dumps({
            "type": "result", "subtype": "error_max_turns", "is_error": True,
            "num_turns": 61, "session_id": "abc123",
            "errors": ["Reached maximum number of turns (60)"],
        }))
        self.assertEqual(telemetry["stop_reason"], "max_turns")
        self.assertEqual(telemetry["resume_token"], "abc123")
        self.assertNotIn("ok", telemetry)

    def test_a_real_error_still_fails_with_its_own_message(self):
        _, telemetry = parse_envelope(json.dumps({
            "type": "result", "subtype": "error_during_execution",
            "is_error": True, "errors": ["the sky fell"],
        }))
        self.assertIs(telemetry["ok"], False)
        self.assertIn("the sky fell", telemetry["error"])

    def test_a_finished_run_reports_complete(self):
        _, telemetry = parse_envelope(json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "result": "done", "session_id": "s1",
        }))
        self.assertEqual(telemetry["stop_reason"], "complete")
        self.assertEqual(telemetry["resume_token"], "s1")

    def test_an_unrecognised_subtype_is_left_unknown_rather_than_guessed(self):
        _, telemetry = parse_envelope(json.dumps({
            "type": "result", "subtype": "error_something_new", "is_error": True,
        }))
        self.assertIsNone(telemetry["stop_reason"])
        self.assertIs(telemetry["ok"], False)


class TestCLICommand(unittest.TestCase):
    """The flag mapping. Resuming needs the session on disk, so the one flag that
    would prevent it must not come back."""

    def test_a_fresh_call_carries_the_prompt_flags(self):
        cmd, unsupported = build_command(AgentRequest(prompt="x", cwd="/tmp"))
        self.assertIn("-p", cmd)
        self.assertNotIn("--resume", cmd)
        self.assertEqual(unsupported, [])

    def test_session_persistence_is_not_disabled(self):
        cmd, _ = build_command(AgentRequest(prompt="x", cwd="/tmp"))
        self.assertNotIn("--no-session-persistence", cmd)

    def test_resume_passes_the_token(self):
        cmd, _ = build_command(AgentRequest(prompt="x", cwd="/tmp", resume="abc123"))
        self.assertEqual(cmd[cmd.index("--resume") + 1], "abc123")

    def test_argv_override_reports_resume_as_superseded(self):
        _, unsupported = build_command(
            AgentRequest(prompt="x", cwd="/tmp", resume="abc123",
                         extra={"argv": "claude -p"}))
        self.assertTrue(any("resume" in u for u in unsupported))


class TestResumeCommand(unittest.TestCase):
    """The way back into a session is the provider's own, so the backend owns it.
    One that has no interactive form must offer nothing rather than a command that
    does not work."""

    def test_claude_cli_hands_over_the_session(self):
        cmd = get_backend("claude-cli").resume_command("abc123", "/tmp/wt")
        self.assertIn("--resume", cmd)
        self.assertIn("abc123", cmd)
        self.assertIn("/tmp/wt", cmd)

    def test_paths_and_tokens_are_quoted(self):
        cmd = get_backend("claude-cli").resume_command("a b", "/tmp/my worktree")
        self.assertIn("'/tmp/my worktree'", cmd)
        self.assertIn("'a b'", cmd)

    def test_a_backend_with_no_interactive_form_offers_none(self):
        self.assertIsNone(get_backend("echo").resume_command("abc123", "/tmp"))


class TestAgentCmdOverride(unittest.TestCase):
    """`extra["argv"]` is the escape hatch. A backend with no command line to
    override must say so rather than appear to have honoured it."""

    def test_sdk_reports_argv_as_unsupported(self):
        backend = get_backend("claude-sdk")
        if not backend.available()[0]:
            self.skipTest("claude-agent-sdk is not installed here")
        result = backend.run(AgentRequest(prompt="x", cwd=".",
                                          extra={"argv": "claude -p"}))
        self.assertTrue(any("argv" in u for u in result.unsupported))

    def test_echo_reports_argv_as_unsupported(self):
        result = get_backend("echo").run(
            AgentRequest(prompt="x", cwd=".", extra={"argv": "claude -p"}))
        self.assertTrue(any("argv" in u for u in result.unsupported))

    def test_echo_reports_nothing_unsupported_without_argv(self):
        result = get_backend("echo").run(AgentRequest(prompt="x", cwd="."))
        self.assertEqual(result.unsupported, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
