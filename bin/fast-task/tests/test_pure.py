#!/usr/bin/env python3
#
# Unit tests for fast_task.py's pure functions — the half that can be tested
# offline. Phases that shell out to claude, gh, git or Asana are validated by
# running them.
#
#   python3 tests/test_pure.py

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fast_task import (  # noqa: E402
    evaluate_gate,
    extract_external_links,
    extract_last_json_block,
    slugify,
    task_key,
)


def task(**overrides):
    base = {
        "ref": "1209876",
        "name": "Add CSV export",
        "status": "Assigned",
        "assignee": "Justin",
        "assignee_gid": "42",
        "fields": {"Estimate": "3h"},
        "board": [{"project": "ENG | Sprint 26.16", "section": "Assigned"}],
    }
    base.update(overrides)
    return base


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Add CSV export"), "add-csv-export")

    def test_strips_punctuation_and_case(self):
        self.assertEqual(slugify("Fix: Login FAILS (silently)!"),
                         "fix-login-fails-silently")

    def test_truncates_to_max_words(self):
        self.assertEqual(
            slugify("one two three four five six seven eight"),
            "one-two-three-four-five-six")

    def test_empty_and_unsluggable_fall_back(self):
        self.assertEqual(slugify(""), "task")
        self.assertEqual(slugify("!!! ???"), "task")
        self.assertEqual(slugify(None), "task")

    def test_digits_survive(self):
        self.assertEqual(slugify("Bump to v2 API"), "bump-to-v2-api")


class TestExtractExternalLinks(unittest.TestCase):
    def test_finds_and_dedupes_preserving_order(self):
        links = extract_external_links(
            "see https://figma.com/file/abc and https://notion.so/page",
            "again https://figma.com/file/abc")
        self.assertEqual(links, ["https://figma.com/file/abc",
                                 "https://notion.so/page"])

    def test_skips_asana_and_github(self):
        links = extract_external_links(
            "https://app.asana.com/0/1/2 https://github.com/o/r/pull/1 "
            "https://figma.com/x")
        self.assertEqual(links, ["https://figma.com/x"])

    def test_strips_trailing_punctuation(self):
        self.assertEqual(extract_external_links("see https://notion.so/page."),
                         ["https://notion.so/page"])

    def test_tolerates_none_and_empty(self):
        self.assertEqual(extract_external_links(None, "", 42), [])


class TestEvaluateGate(unittest.TestCase):
    def test_happy_path(self):
        verdict = evaluate_gate(task(), [], "42")
        self.assertEqual(verdict["blocking"], [])
        self.assertEqual(verdict["warnings"], [])
        self.assertFalse(verdict["self_assign"])

    def test_started_status_blocks(self):
        verdict = evaluate_gate(task(status="In Progress"), [], "42")
        self.assertEqual(len(verdict["blocking"]), 1)
        self.assertIn("not a not-yet-started state", verdict["blocking"][0])

    def test_status_match_is_case_insensitive(self):
        self.assertEqual(evaluate_gate(task(status="ASSIGNED"), [], "42")["blocking"], [])

    def test_missing_status_blocks(self):
        self.assertTrue(evaluate_gate(task(status=None), [], "42")["blocking"])

    def test_incomplete_dependency_blocks(self):
        deps = [{"name": "Build the API", "completed": False},
                {"name": "Design it", "completed": True}]
        verdict = evaluate_gate(task(), deps, "42")
        self.assertEqual(len(verdict["blocking"]), 1)
        self.assertIn("Build the API", verdict["blocking"][0])
        self.assertNotIn("Design it", verdict["blocking"][0])

    def test_completed_dependencies_pass(self):
        deps = [{"name": "Done thing", "completed": True}]
        self.assertEqual(evaluate_gate(task(), deps, "42")["blocking"], [])

    def test_unassigned_requests_self_assign_not_block(self):
        verdict = evaluate_gate(task(assignee=None, assignee_gid=None), [], "42")
        self.assertTrue(verdict["self_assign"])
        self.assertEqual(verdict["blocking"], [])

    def test_assigned_to_someone_else_blocks(self):
        verdict = evaluate_gate(task(assignee="Maria", assignee_gid="99"), [], "42")
        self.assertIn("Maria", verdict["blocking"][0])

    def test_missing_estimate_warns_by_default(self):
        verdict = evaluate_gate(task(fields={}), [], "42")
        self.assertEqual(verdict["blocking"], [])
        self.assertEqual(verdict["warnings"], ["no Estimate set"])

    def test_missing_estimate_blocks_under_strict(self):
        verdict = evaluate_gate(task(fields={}), [], "42", strict=True)
        self.assertIn("no Estimate set", verdict["blocking"])

    def test_sprint_membership_only_checked_under_strict(self):
        off_sprint = task(board=[{"project": "ENG | Backlog", "section": "New"}])
        self.assertEqual(evaluate_gate(off_sprint, [], "42")["blocking"], [])
        strict = evaluate_gate(off_sprint, [], "42", strict=True)["blocking"]
        self.assertTrue(any("sprint" in b for b in strict))

    def test_reports_every_failure_at_once(self):
        verdict = evaluate_gate(
            task(status="Done", assignee="Maria", assignee_gid="99"),
            [{"name": "Blocker", "completed": False}], "42")
        self.assertEqual(len(verdict["blocking"]), 3)


class TestExtractLastJsonBlock(unittest.TestCase):
    def test_extracts_fenced_json(self):
        text = 'Did the thing.\n\n```json\n{"summary": "ok"}\n```'
        self.assertEqual(extract_last_json_block(text), {"summary": "ok"})

    def test_takes_the_last_block(self):
        text = '```json\n{"n": 1}\n```\nthen\n```json\n{"n": 2}\n```'
        self.assertEqual(extract_last_json_block(text), {"n": 2})

    def test_skips_unparseable_trailing_block(self):
        text = '```json\n{"n": 1}\n```\n```json\nnot json\n```'
        self.assertEqual(extract_last_json_block(text), {"n": 1})

    def test_unfenced_language_tag_optional(self):
        self.assertEqual(extract_last_json_block('```\n{"n": 3}\n```'), {"n": 3})

    def test_ignores_non_object_json(self):
        self.assertIsNone(extract_last_json_block('```json\n[1, 2]\n```'))

    def test_no_block_returns_none(self):
        self.assertIsNone(extract_last_json_block("just prose"))
        self.assertIsNone(extract_last_json_block(None))


class TestTaskKey(unittest.TestCase):
    def test_prefers_human_key(self):
        self.assertEqual(task_key({"task_id": "MT251-47", "ref": "12"}), "MT251-47")

    def test_falls_back_to_gid(self):
        self.assertEqual(task_key({"ref": "12"}), "12")


if __name__ == "__main__":
    unittest.main(verbosity=2)
