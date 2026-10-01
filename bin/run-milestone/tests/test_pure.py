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

from engine import (  # noqa: E402
    actual_hours,
    blockers,
    collect_feedback,
    describe,
    has_value,
    kill_tree,
    outcome_phase,
    parse_pr_url,
    parse_project_ref,
    ready_tasks,
    reconcile,
    render_feedback,
    render_resolve,
    resolve_request,
)
from run_milestone import match_milestones  # noqa: E402
from start_task import EXIT_AWAITING, EXIT_FAILED, EXIT_OK, mark  # noqa: E402

ME = "42"


def t(name, deps=(), completed=False, status="Unassigned", assignee_gid=None):
    return {"name": name, "key": name, "completed": completed, "status": status,
            "assignee_gid": assignee_gid, "assignee": "Someone" if assignee_gid else None,
            "deps": [{"ref": ref, "name": ref, "completed": done} for ref, done in deps]}


class TestParseProjectRef(unittest.TestCase):
    def test_list_url(self):
        self.assertEqual(parse_project_ref(
            "https://app.asana.com/1/1202999775780036/project/1219020319579527/list"),
            "1219020319579527")

    def test_zero_form_and_bare_gid(self):
        self.assertEqual(parse_project_ref("https://app.asana.com/0/1218562510042382/list"),
                         "1218562510042382")
        self.assertEqual(parse_project_ref("1218562510042382"), "1218562510042382")

    def test_rejects_other_input(self):
        self.assertIsNone(parse_project_ref("https://github.com/o/r"))
        self.assertIsNone(parse_project_ref(None))


class TestMatchMilestones(unittest.TestCase):
    LISTING = [
        {"name": "Untitled section", "ref": "100"},
        {"name": "M1 :: Built and working locally", "ref": "101"},
        {"name": "M2 :: Running in dev", "ref": "102"},
        {"name": "M10 :: Later", "ref": "110"},
    ]

    def refs(self, wanted):
        return [m["ref"] for m in match_milestones(wanted, self.LISTING)]

    def test_short_name_full_name_gid_and_url(self):
        self.assertEqual(self.refs(["M1"]), ["101"])
        self.assertEqual(self.refs(["m2 :: running in dev"]), ["102"])
        self.assertEqual(self.refs(["110"]), ["110"])
        self.assertEqual(self.refs(
            ["https://app.asana.com/1/1/project/5/task/102"]), ["102"])

    def test_short_name_does_not_prefix_match(self):
        self.assertEqual(self.refs(["M1", "M10"]), ["101", "110"])

    def test_several_in_order_without_duplicates(self):
        self.assertEqual(self.refs(["M2", "M1", "101"]), ["102", "101"])

    def test_unknown_names_say_what_the_board_has(self):
        with self.assertRaises(ValueError) as ctx:
            match_milestones(["M7"], self.LISTING)
        self.assertIn("M1 :: Built and working locally", str(ctx.exception))


class TestParsePrUrl(unittest.TestCase):
    def test_parses(self):
        self.assertEqual(parse_pr_url("https://github.com/SIROC-Labs/cortex/pull/60"),
                         ("SIROC-Labs", "cortex", 60))

    def test_rejects_other_urls(self):
        self.assertIsNone(parse_pr_url("https://github.com/SIROC-Labs/cortex"))
        self.assertIsNone(parse_pr_url(None))


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
        for phase in ("running", "awaiting", "revising", "pr_open", "conflict",
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
        self.assertIn("not in this run", blockers("1", g, {}, ME)[0])
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
        self.assertIn("please resolve", describe("1", g, {"1": {"phase": "conflict"}}, ME))
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

    def test_render_carries_every_item(self):
        text = render_feedback([("comment:1", "Comment by @j", "rename it"),
                                ("inline:2", "`a.py` — @j", "typo")])
        self.assertIn("### Comment by @j", text)
        self.assertIn("typo", text)


class TestResolveRequest(unittest.TestCase):
    def test_finds_the_request_case_insensitively(self):
        items = [("comment:1", "h", "looks fine"), ("comment:2", "h", "Please resolve, thanks")]
        self.assertEqual(resolve_request(items)[0], "comment:2")

    def test_other_comments_are_not_a_request(self):
        self.assertIsNone(resolve_request([("comment:1", "h", "resolved the thread")]))
        self.assertIsNone(resolve_request([]))

    def test_the_resolve_brief_says_merge_not_rebase(self):
        text = render_resolve(("comment:2", "Comment by @j", "please resolve"))
        self.assertIn("Merge the base into the branch", text)


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


class TestActualTime(unittest.TestCase):
    def test_run_time_in_hours_at_two_places(self):
        self.assertEqual(actual_hours(3 * 3600 + 900), 3.25)
        self.assertEqual(actual_hours(61), 0.02)

    def test_no_recorded_run_time_gives_nothing(self):
        for none in (None, 0, -5):
            self.assertIsNone(actual_hours(none))

    def test_a_value_someone_entered_is_kept_an_empty_or_zero_one_is_not(self):
        self.assertTrue(has_value("1.38"))
        for empty in (None, "", "0", "0.00"):
            self.assertFalse(has_value(empty), empty)

    def test_merged_shows_the_hours(self):
        g = {"1": t("a", completed=True)}
        self.assertEqual(describe("1", g, {"1": {"phase": "merged", "actual_hours": 3.25}}, ME),
                         "merged — 3.25h of run time")


class TestKillTree(unittest.TestCase):
    """Stopping a run must stop what it started: the agent outliving the run is
    how work carries on that nobody can see."""

    def test_a_run_in_its_own_group_takes_its_children_with_it(self):
        import subprocess
        import time as _time
        proc = subprocess.Popen(["sh", "-c", "sleep 30 & echo $!; wait"],
                                stdout=subprocess.PIPE, start_new_session=True)
        child = int(proc.stdout.readline())
        self.assertTrue(kill_tree(proc.pid))
        proc.wait(timeout=5)
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            _time.sleep(0.05)
        else:
            os.kill(child, 9)
            self.fail("the run's child outlived it")

    def test_nothing_to_stop(self):
        self.assertFalse(kill_tree(2 ** 22 + 12345))


if __name__ == "__main__":
    unittest.main(verbosity=2)
