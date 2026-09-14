#!/usr/bin/env python3
#
# Tests for the agent seam: the neutral types, the registry, and each backend's
# translation layer. No network and no model — the two real backends are probed
# only through their pure mapping tables and their `available()` reporting.
#
#   python3 tests/test_agent.py

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import (  # noqa: E402
    AgentRequest, AgentResult, available_backends, backend_names,
    extract_last_json_block, get_backend, tools_for,
)
from agent.base import TOOLS_EDIT, TOOLS_FULL, TOOLS_READ_ONLY  # noqa: E402
from agent.claude_sdk import _denial_name, _usage  # noqa: E402


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
        self.assertEqual(result.cost_usd, 0.0)


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


class TestUsageReading(unittest.TestCase):
    """The SDK hands back `usage` as a plain dict even though its docs describe a
    dataclass. Reading it with getattr silently yields None and blanks the cost
    telemetry — the whole point of this experiment. Both shapes must work."""

    def test_reads_a_dict(self):
        self.assertEqual(_usage({"input_tokens": 12}, "input_tokens"), 12)

    def test_reads_an_object(self):
        class Usage(object):
            input_tokens = 12
        self.assertEqual(_usage(Usage(), "input_tokens"), 12)

    def test_none_usage_is_none_not_an_error(self):
        self.assertIsNone(_usage(None, "input_tokens"))

    def test_missing_key_is_none(self):
        self.assertIsNone(_usage({}, "input_tokens"))


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
        summary = AgentResult(backend="x", model="m", turns=3, cost_usd=0.5,
                              input_tokens=10, output_tokens=20,
                              duration_s=1.5).summary()
        for fragment in ("x", "m", "3 turns", "10 in / 20 out", "$0.5000", "1.5s"):
            self.assertIn(fragment, summary)

    def test_singular_turn(self):
        self.assertIn("1 turn ", AgentResult(backend="x", turns=1).summary() + " ")

    def test_partial_token_counts_are_marked_unknown(self):
        self.assertIn("? in / 20 out",
                      AgentResult(backend="x", output_tokens=20).summary())


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
