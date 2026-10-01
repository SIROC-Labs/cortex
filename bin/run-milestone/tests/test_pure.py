#!/usr/bin/env python3
#
# Unit tests for run_milestone.py's pure functions — readiness over the
# dependency graph, outcome parsing, feedback selection and restart
# reconciliation. The loop itself shells out to Asana, gh and start-task, and
# is validated by running it.
#
#   python3 tests/test_pure.py

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_milestone import (  # noqa: E402
    blockers,
    collect_feedback,
    describe,
    outcome_phase,
    parse_milestone_url,
    parse_pr_url,
    ready_tasks,
    reconcile,
    render_feedback,
    sprint_pattern_for,
)
from start_task import EXIT_AWAITING, EXIT_FAILED, EXIT_OK, mark  # noqa: E402

ME = "42"


def t(name, deps=(), completed=False, status="Unassigned", assignee_gid=None):
    return {"name": name, "key": name, "completed": completed, "status": status,
            "assignee_gid": assignee_gid, "assignee": "Someone" if assignee_gid else None,
            "deps": [{"ref": ref, "name": ref, "completed": done} for ref, done in deps]}


class TestParseMilestoneUrl(unittest.TestCase):
    def test_project_task_form(self):
        self.assertEqual(parse_milestone_url(
            "https://app.asana.com/1/1202999775780036/project/1219020319579527/task/"
            "1219043367529094?focus=true"),
            ("1219020319579527", "1219043367529094"))

    def test_zero_form(self):
        self.assertEqual(parse_milestone_url("https://app.asana.com/0/111/222/f"),
                         ("111", "222"))

    def test_a_project_url_alone_is_not_a_milestone(self):
        self.assertEqual(parse_milestone_url(
            "https://app.asana.com/1/1202999775780036/project/1219020319579527/list"),
            (None, None))


class TestParsePrUrl(unittest.TestCase):
    def test_parses(self):
        self.assertEqual(parse_pr_url("https://github.com/SIROC-Labs/cortex/pull/60"),
                         ("SIROC-Labs", "cortex", 60))

    def test_rejects_other_urls(self):
        self.assertIsNone(parse_pr_url("https://github.com/SIROC-Labs/cortex"))
        self.assertIsNone(parse_pr_url(None))


class TestSprintPattern(unittest.TestCase):
    def test_team_prefix_selects_that_teams_sprint(self):
        import re
        pattern = sprint_pattern_for("Humanus | Candidate Intake")
        self.assertTrue(re.search(pattern, "Humanus | Sprint 26/2"))
        self.assertFalse(re.search(pattern, "ENG | Sprint 26.16"))
        self.assertFalse(re.search(pattern, "Humanus | Candidate Intake"))

    def test_no_separator_falls_back_to_defaults(self):
        self.assertIsNone(sprint_pattern_for("Roadmap"))
        self.assertIsNone(sprint_pattern_for(None))


class TestReadiness(unittest.TestCase):
    def graph(self):
        return {
            "1": t("CI1"),
            "2": t("CI2", deps=[("1", False)]),
            "3": t("CI3", deps=[("1", False)]),
            "4": t("CI4", deps=[("2", False), ("3", False)]),
        }

    def test_only_the_root_is_ready_at_first(self):
        self.assertEqual(ready_tasks(self.graph(), {}, ME), ["1"])

    def test_completing_a_root_readies_every_independent_dependent_at_once(self):
        g = self.graph()
        g["1"]["completed"] = True
        for gid in ("2", "3"):
            g[gid]["deps"][0]["completed"] = True
        self.assertEqual(ready_tasks(g, {"1": {"phase": "merged"}}, ME), ["2", "3"])

    def test_a_task_with_a_record_is_not_launched_twice(self):
        for phase in ("running", "awaiting", "revising", "pr_open", "closed",
                      "merged", "failed", "stopped"):
            self.assertEqual(ready_tasks(self.graph(), {"1": {"phase": phase}}, ME), [])

    def test_a_record_reset_for_relaunch_is_ready_again(self):
        self.assertEqual(ready_tasks(self.graph(), {"1": {"phase": None}}, ME), ["1"])

    def test_completed_and_started_tasks_are_not_ready(self):
        g = {"1": t("a", completed=True), "2": t("b", status="In Progress")}
        self.assertEqual(ready_tasks(g, {}, ME), [])

    def test_someone_elses_task_is_not_taken(self):
        g = {"1": t("a", assignee_gid="99"), "2": t("b", assignee_gid=ME)}
        self.assertEqual(ready_tasks(g, {}, ME), ["2"])

    def test_a_dependency_outside_the_milestone_gates_until_completed(self):
        g = {"1": t("a", deps=[("elsewhere", False)])}
        self.assertEqual(ready_tasks(g, {}, ME), [])
        self.assertIn("outside the milestone", blockers("1", g, {}, ME)[0])
        g["1"]["deps"][0]["completed"] = True
        self.assertEqual(ready_tasks(g, {}, ME), ["1"])

    def test_a_failed_dependency_is_named_as_the_blocker(self):
        g = self.graph()
        self.assertIn("(failed)", blockers("2", g, {"1": {"phase": "failed"}}, ME)[0])

    def test_canceled_is_its_own_reason(self):
        self.assertEqual(blockers("1", {"1": t("a", status="Canceled")}, {}, ME),
                         ["canceled"])


class TestDescribe(unittest.TestCase):
    def test_states(self):
        g = {"1": t("a"), "2": t("b", deps=[("1", False)])}
        self.assertEqual(describe("1", g, {}, ME), "ready")
        self.assertEqual(describe("2", g, {}, ME), "waits on 1")
        self.assertEqual(describe("1", g, {"1": {"phase": "awaiting"}}, ME), "awaiting Justin")
        self.assertIn("conflicts", describe(
            "1", g, {"1": {"phase": "pr_open", "conflict_notified": True}}, ME))
        self.assertEqual(describe("1", g, {"1": {"phase": "failed", "reason": "QA\nmore"}}, ME),
                         "failed: QA")


class TestOutcomePhase(unittest.TestCase):
    def test_shipped_and_revised_mean_a_pr_to_watch(self):
        self.assertEqual(outcome_phase(EXIT_OK, {"status": "shipped"}), ("pr_open", None))
        self.assertEqual(outcome_phase(EXIT_OK, {"status": "revised"}), ("pr_open", None))

    def test_a_clean_exit_without_an_outcome_is_not_trusted(self):
        self.assertEqual(outcome_phase(EXIT_OK, None)[0], "failed")

    def test_failure_carries_the_reason(self):
        self.assertEqual(outcome_phase(EXIT_FAILED, {"status": "failed", "reason": "boom"}),
                         ("failed", "boom"))

    def test_a_crash_says_how_it_exited(self):
        phase, reason = outcome_phase(-9, None)
        self.assertEqual(phase, "failed")
        self.assertIn("-9", reason)

    def test_awaiting(self):
        self.assertEqual(outcome_phase(EXIT_AWAITING, {"reason": "q"}), ("awaiting", "q"))


class TestCollectFeedback(unittest.TestCase):
    def user(self, login="justin", kind="User"):
        return {"login": login, "type": kind}

    def test_reviews_inline_and_top_level_comments_all_count(self):
        items = collect_feedback(
            [{"id": 1, "state": "CHANGES_REQUESTED", "body": "rename it", "user": self.user()}],
            [{"id": 2, "path": "a.py", "line": 3, "body": "typo", "user": self.user()}],
            [{"id": 3, "body": "also add a test", "user": self.user()}],
            [])
        self.assertEqual([i[0] for i in items], ["review:1", "inline:2", "comment:3"])
        self.assertIn("a.py", items[1][1])

    def test_the_runs_own_marked_posts_are_ignored(self):
        items = collect_feedback([], [], [{"id": 3, "body": mark("Addressed review"),
                                          "user": self.user()}], [])
        self.assertEqual(items, [])

    def test_bots_pending_reviews_and_empty_bodies_are_ignored(self):
        items = collect_feedback(
            [{"id": 1, "state": "PENDING", "body": "draft", "user": self.user()},
             {"id": 2, "state": "APPROVED", "body": "", "user": self.user()}],
            [{"id": 3, "path": "a", "body": "x", "user": self.user("ci[bot]", "Bot")}],
            [{"id": 4, "body": "coverage 80%", "user": self.user("codecov", "Bot")}],
            [])
        self.assertEqual(items, [])

    def test_handled_items_are_not_fed_twice(self):
        items = collect_feedback([], [], [{"id": 3, "body": "x", "user": self.user()},
                                          {"id": 4, "body": "y", "user": self.user()}],
                                 ["comment:3"])
        self.assertEqual([i[0] for i in items], ["comment:4"])

    def test_render_mentions_a_conflict(self):
        text = render_feedback([("comment:1", "Comment by @j", "merge main")], conflicting=True)
        self.assertIn("conflicts", text)
        self.assertIn("merge main", text)


class TestReconcile(unittest.TestCase):
    def test_a_run_killed_with_the_loop_is_relaunched(self):
        self.assertIsNone(reconcile({"phase": "running", "since": 10, "pid": 5},
                                    None, None)["phase"])

    def test_a_live_run_is_adopted_not_restarted(self):
        out = reconcile({"phase": "running", "since": 10}, None, 777)
        self.assertEqual((out["phase"], out["pid"]), ("running", 777))

    def test_a_hand_run_in_progress_is_adopted(self):
        self.assertEqual(reconcile(None, None, 777)["phase"], "running")

    def test_a_run_that_shipped_while_the_loop_was_down_is_watched(self):
        out = reconcile({"phase": "running", "since": 10},
                        {"status": "shipped", "at": 20, "pr_url": "u", "branch": "b"}, None)
        self.assertEqual((out["phase"], out["pr_url"]), ("pr_open", "u"))

    def test_a_task_shipped_by_hand_is_picked_up(self):
        out = reconcile(None, {"status": "shipped", "at": 20, "pr_url": "u"}, None)
        self.assertEqual(out["phase"], "pr_open")

    def test_an_outcome_older_than_the_record_is_ignored(self):
        out = reconcile({"phase": "running", "since": 30},
                        {"status": "shipped", "at": 20, "pr_url": "u"}, None)
        self.assertIsNone(out["phase"])

    def test_a_failure_while_the_loop_was_down_is_recorded(self):
        out = reconcile({"phase": "running", "since": 10},
                        {"status": "failed", "at": 20, "reason": "boom"}, None)
        self.assertEqual((out["phase"], out["reason"]), ("failed", "boom"))

    def test_an_interrupted_revise_goes_back_to_watching_with_its_feedback_unhandled(self):
        out = reconcile({"phase": "revising", "since": 10, "handled": ["a"],
                         "inflight": ["b"]}, None, None)
        self.assertEqual(out["phase"], "pr_open")
        self.assertEqual(out["handled"], ["a"])
        self.assertNotIn("inflight", out)

    def test_a_revise_that_finished_while_down_marks_its_feedback_handled(self):
        out = reconcile({"phase": "revising", "since": 10, "handled": ["a"],
                         "inflight": ["b"], "pr_url": "u"},
                        {"status": "revised", "at": 20, "pr_url": "u"}, None)
        self.assertEqual(out["handled"], ["a", "b"])

    def test_settled_records_are_left_alone(self):
        for phase in ("merged", "pr_open", "failed", "stopped"):
            self.assertEqual(reconcile({"phase": phase, "since": 10}, None, None)["phase"],
                             phase)


if __name__ == "__main__":
    unittest.main(verbosity=2)
