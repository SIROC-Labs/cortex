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
    auto_merge_due,
    blockers,
    check_states,
    merge_method,
    merge_step,
    render_ci_fix,
    collect_feedback,
    describe,
    has_value,
    kill_tree,
    merge_refresh,
    phase_note,
    run_header,
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
                         "merged — 03:15 of run time")

    def test_merged_shows_tokens_too(self):
        g = {"1": t("a", completed=True)}
        rec = {"phase": "merged", "actual_hours": 0.5,
               "usage": {"input": 1000, "output": 200000, "cache_read": 1000000, "cache_write": 39000,
                         "cost_usd": 3.4}}
        self.assertEqual(describe("1", g, {"1": rec}, ME),
                         "merged — 00:30 of run time · 1.24M tokens · ≈$3.40")

    def test_hhmm(self):
        from engine import hhmm
        self.assertEqual(hhmm(0.46), "00:28")
        self.assertEqual(hhmm(2.69), "02:41")
        self.assertEqual(hhmm(0), "00:00")
        self.assertEqual(hhmm(12.5), "12:30")


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

    def test_a_stopped_child_is_reaped_not_left_a_zombie(self):
        import subprocess
        import time as _time
        import engine
        e = engine.Engine.__new__(engine.Engine)
        e.data = {"tasks": {}, "records": {}}
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        e.children = {"1": proc}
        e.kill("1")
        for _ in range(50):
            if proc.poll() is not None:
                break
            _time.sleep(0.05)
        self.assertIsNotNone(proc.returncode)
        with self.assertRaises(ProcessLookupError):
            os.kill(proc.pid, 0)

    def test_nothing_to_stop(self):
        self.assertFalse(kill_tree(2 ** 22 + 12345))


def run_check(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion,
            "detailsUrl": "https://ci/%s" % name}


class TestCheckStates(unittest.TestCase):
    def test_running_failed_and_passed_runs(self):
        pending, failing = check_states([
            run_check("verify"), run_check("e2e", status="IN_PROGRESS", conclusion=None),
            run_check("test", conclusion="FAILURE"), run_check("lint", conclusion="SKIPPED")])
        self.assertEqual(pending, ["e2e"])
        self.assertEqual(failing, [("test", "https://ci/test")])

    def test_commit_statuses(self):
        pending, failing = check_states([
            {"__typename": "StatusContext", "context": "deploy", "state": "PENDING"},
            {"__typename": "StatusContext", "context": "sec", "state": "ERROR", "targetUrl": "u"}])
        self.assertEqual((pending, failing), (["deploy"], [("sec", "u")]))


class TestMergeStep(unittest.TestCase):
    def view(self, status, mergeable="MERGEABLE", checks=(), draft=False):
        return {"mergeStateStatus": status, "mergeable": mergeable,
                "statusCheckRollup": list(checks), "isDraft": draft}

    def test_clean_merges(self):
        self.assertEqual(merge_step(self.view("CLEAN"), {}), ("merge", None))
        self.assertEqual(merge_step(self.view("CLEAN", checks=[run_check("e2e")]), {}),
                         ("merge", None))

    def test_a_branch_with_no_rules_still_waits_for_every_check(self):
        running = [run_check("e2e", status="IN_PROGRESS", conclusion=None)]
        self.assertEqual(merge_step(self.view("CLEAN", checks=running), {})[0], "wait")
        self.assertEqual(merge_step(self.view("UNSTABLE", checks=running), {})[0], "wait")

    def test_failing_checks_are_fixed_even_when_github_would_merge(self):
        failed = [run_check("e2e", conclusion="FAILURE")]
        self.assertEqual(merge_step(self.view("UNSTABLE", checks=failed), {})[0], "fix_ci")
        self.assertEqual(merge_step(self.view("CLEAN", checks=failed), {"ci": 2})[0], "blocked")

    def test_skipped_and_neutral_checks_do_not_hold_a_merge(self):
        quiet = [run_check("terraform", conclusion="SKIPPED"), run_check("x", conclusion="NEUTRAL")]
        self.assertEqual(merge_step(self.view("CLEAN", checks=quiet), {}), ("merge", None))

    def test_conflicts_are_resolved_until_the_limit(self):
        dirty = self.view("DIRTY", "CONFLICTING")
        self.assertEqual(merge_step(dirty, {"resolve": 2}), ("resolve", None))
        action, why = merge_step(dirty, {"resolve": 3})
        self.assertEqual(action, "blocked")
        self.assertIn("3 resolve", why)

    def test_running_checks_are_waited_on(self):
        action, why = merge_step(self.view("BLOCKED", checks=[
            run_check("e2e", status="QUEUED", conclusion=None)]), {})
        self.assertEqual(action, "wait")
        self.assertIn("e2e", why)

    def test_failed_checks_are_fixed_until_the_limit(self):
        failed = self.view("BLOCKED", checks=[run_check("verify", conclusion="FAILURE")])
        self.assertEqual(merge_step(failed, {})[0], "fix_ci")
        self.assertEqual(merge_step(failed, {})[1], [("verify", "https://ci/verify")])
        self.assertEqual(merge_step(failed, {"ci": 2})[0], "blocked")

    def test_blocked_with_green_checks_needs_a_person(self):
        self.assertEqual(merge_step(self.view("BLOCKED", checks=[run_check("v")]), {})[0],
                         "held")

    def test_a_required_check_that_has_not_reported_yet_is_waited_for(self):
        just_pushed = self.view("BLOCKED", checks=[run_check("changes")])
        action, why = merge_step(just_pushed, {}, required=["e2e", "verify"])
        self.assertEqual(action, "wait")
        self.assertEqual(why, "waiting for checks to start: e2e, verify")
        all_in = self.view("CLEAN", checks=[run_check("e2e"), run_check("verify")])
        self.assertEqual(merge_step(all_in, {}, required=["e2e", "verify"]), ("merge", None))

    def test_drafts_behind_and_unknown(self):
        self.assertEqual(merge_step(self.view("CLEAN", draft=True), {})[0], "ready")
        self.assertEqual(merge_step(self.view("BEHIND"), {})[0], "update")
        self.assertEqual(merge_step(self.view("UNKNOWN", "UNKNOWN"), {})[0], "wait")

    def test_the_ci_brief_names_the_failures_and_how_to_look(self):
        text = render_ci_fix([("verify", "https://ci/verify")])
        self.assertIn("verify — https://ci/verify", text)
        self.assertIn("--log-failed", text)


class TestMergeHolds(unittest.TestCase):
    """GitHub holds a PR it was just pushed to before CI registers its checks,
    and says nothing about why. That must be waited out, and a block must clear
    by itself once GitHub will merge."""

    def setUp(self):
        import tempfile
        import shutil
        import engine
        self.engine = engine
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        e = engine.Engine.__new__(engine.Engine)
        e.dir, e.busy, e.children = root, {}, {}
        e.data = {"tasks": {"1": {"key": "T-1"}}, "records": {}}
        e.rules_cache = {"o/r@feature/x": {"method": "squash", "required": []}}
        self.views, self.merged_calls = [], []
        e.gh_json = lambda args: self.views.pop(0)
        self.saved_run = engine.run
        engine.run = lambda cmd, cwd=None: (self.merged_calls.append(cmd) or (0, "", ""))
        self.addCleanup(setattr, engine, "run", self.saved_run)
        e.repo = root
        self.e = e
        self.record = e.records.setdefault("1", {"phase": "pr_open", "pr_url": "u",
                                                 "merge": {"attempts": {}, "blocked": None}})

    def step(self, status, now):
        self.views.append({"state": "OPEN", "mergeStateStatus": status, "mergeable": "MERGEABLE",
                           "baseRefName": "feature/x", "statusCheckRollup": [run_check("e2e")]})
        saved = self.engine.time.time
        self.engine.time.time = lambda: now
        try:
            self.e.merge_step_once("1", "o", "r", self.record, self.record["merge"], "u")
        finally:
            self.engine.time.time = saved
        return self.record["merge"]

    def test_a_hold_is_waited_on_then_called_a_block_then_clears_by_itself(self):
        merge = self.step("BLOCKED", 1000)
        self.assertIsNone(merge["blocked"])
        self.assertIn("holding it", merge["stage"])
        merge = self.step("BLOCKED", 1000 + self.engine.HOLD_GRACE - 1)
        self.assertIsNone(merge["blocked"])
        merge = self.step("BLOCKED", 1000 + self.engine.HOLD_GRACE + 1)
        self.assertIn("will not merge it yet", merge["blocked"])
        self.assertEqual(self.record["next_poll"], 1000 + self.engine.HOLD_GRACE + 1
                         + self.engine.BLOCKED_POLL)
        merge = self.step("CLEAN", 2000)
        self.assertIsNone(merge["blocked"])
        self.assertTrue(any(cmd[:3] == ["gh", "pr", "merge"] for cmd in self.merged_calls))


class TestMergeMethod(unittest.TestCase):
    def test_squash_first_within_what_the_rules_allow(self):
        everything = {"squashMergeAllowed": True, "mergeCommitAllowed": True,
                      "rebaseMergeAllowed": True}
        self.assertEqual(merge_method(everything, []), "squash")
        self.assertEqual(merge_method(everything, ["rebase"]), "rebase")
        self.assertEqual(merge_method(dict(everything, squashMergeAllowed=False), []), "merge")
        self.assertIsNone(merge_method(everything, ["octopus"]))


class TestDescribeMerge(unittest.TestCase):
    def test_merging_and_blocked(self):
        g = {"1": t("a")}
        self.assertEqual(describe("1", g, {"1": {"phase": "pr_open", "merge": {
            "stage": "checks running: e2e"}}}, ME), "merging — checks running: e2e")
        self.assertEqual(describe("1", g, {"1": {"phase": "pr_open", "merge": {
            "blocked": "needs a review"}}}, ME), "merge blocked: needs a review")


class TestMergeRefresh(unittest.TestCase):
    """A background re-read can start before a merge the loop then makes; folding
    it in must not undo that merge."""

    def test_a_task_merged_meanwhile_stays_done_and_frees_its_dependents(self):
        local = {"1": {"completed": True, "deps": []},
                 "2": {"completed": False, "deps": [{"ref": "1", "completed": True}]}}
        fetched = {"1": {"completed": False, "deps": []},
                   "2": {"completed": False, "deps": [{"ref": "1", "completed": False}]}}
        out = merge_refresh(local, fetched)
        self.assertTrue(out["1"]["completed"])
        self.assertTrue(out["2"]["deps"][0]["completed"])

    def test_newer_facts_from_asana_still_land(self):
        local = {"1": {"completed": False, "deps": [{"ref": "x", "completed": False}]}}
        fetched = {"1": {"completed": False, "deps": [{"ref": "x", "completed": True}],
                         "status": "Canceled"},
                   "3": {"completed": False, "deps": []}}
        out = merge_refresh(local, fetched)
        self.assertTrue(out["1"]["deps"][0]["completed"])
        self.assertEqual(out["1"]["status"], "Canceled")
        self.assertIn("3", out)


class TestTaskLogNotes(unittest.TestCase):
    def test_each_phase_says_what_is_happening(self):
        self.assertIn("watching", phase_note("pr_open", {}))
        self.assertIsNone(phase_note("pr_open", {"merge": {}}))  # the merge notes its own steps
        self.assertEqual(phase_note("failed", {"reason": "QA red\nmore"}), "Failed: QA red")
        self.assertIn("parked", phase_note("conflict", {}))

    def test_runs_write_their_own_account(self):
        for phase in ("running", "revising", "merged", None):
            self.assertIsNone(phase_note(phase, {}))

    def test_the_run_header_says_why(self):
        line = run_header("revise: resolving conflicts with main, to merge", at=0)
        self.assertTrue(line.strip().startswith("━━ "))
        self.assertIn("revise: resolving conflicts with main, to merge", line)


class TestAutoMerge(unittest.TestCase):
    SHIPPED = {"phase": "pr_open"}

    def test_by_default_a_pr_off_the_default_branch_merges_by_itself(self):
        self.assertTrue(auto_merge_due("branches", self.SHIPPED, "milestone/m1", "main"))
        self.assertFalse(auto_merge_due("branches", self.SHIPPED, "main", "main"))

    def test_an_unknown_base_or_default_is_never_assumed_safe(self):
        self.assertFalse(auto_merge_due("branches", self.SHIPPED, None, "main"))
        self.assertFalse(auto_merge_due("branches", self.SHIPPED, "milestone/m1", None))

    def test_always_includes_the_default_branch(self):
        self.assertTrue(auto_merge_due("always", self.SHIPPED, "main", "main"))
        self.assertTrue(auto_merge_due("always", {"phase": "conflict"}, "main", "main"))

    def test_only_when_asked_merges_nothing_by_itself(self):
        self.assertFalse(auto_merge_due("asked", self.SHIPPED, "milestone/m1", "main"))

    def test_once_merging_or_called_off_or_not_shipped_it_is_left_alone(self):
        for record in ({"phase": "pr_open", "merge": {}},
                       {"phase": "pr_open", "merge_declined": True}, {"phase": "running"}):
            self.assertFalse(auto_merge_due("always", record, "x", "main"), record)


if __name__ == "__main__":
    unittest.main(verbosity=2)
