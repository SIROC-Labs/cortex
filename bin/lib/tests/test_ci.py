import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ci  # noqa: E402
from ci import (  # noqa: E402
    check_states,
    collect_feedback,
    render_feedback,
)
from core import mark  # noqa: E402


def run_check(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion,
            "detailsUrl": "https://ci/%s" % name}


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


class TestCheckStates(unittest.TestCase):
    def test_running_failed_and_passed_runs(self):
        pending, failing = check_states([
            run_check("verify"), run_check("e2e", status="IN_PROGRESS", conclusion=None),
            run_check("test", conclusion="FAILURE"), run_check("lint", conclusion="SKIPPED")])
        self.assertEqual(pending, ["e2e"])
        self.assertEqual(failing, [("test", "https://ci/test")])

    def test_a_cancelled_run_superseded_by_a_newer_one_does_not_count(self):
        rollup = [dict(run_check("e2e", conclusion="CANCELLED"), startedAt="2026-10-05T17:49:53Z"),
                  dict(run_check("e2e", conclusion="SUCCESS"), startedAt="2026-10-05T17:52:53Z")]
        self.assertEqual(check_states(rollup), ([], []))
        running = [rollup[0], dict(run_check("e2e", status="IN_PROGRESS", conclusion=None),
                                   startedAt="2026-10-05T17:52:53Z")]
        self.assertEqual(check_states(running), (["e2e"], []))

    def test_a_newer_failure_still_counts_and_a_lone_cancel_is_not_green(self):
        rollup = [dict(run_check("e2e", conclusion="SUCCESS"), startedAt="2026-10-05T17:00:00Z"),
                  dict(run_check("e2e", conclusion="FAILURE"), startedAt="2026-10-05T18:00:00Z")]
        self.assertEqual([n for n, _ in check_states(rollup)[1]], ["e2e"])
        self.assertEqual([n for n, _ in check_states([run_check("e2e", conclusion="CANCELLED")])[1]],
                         ["e2e"])

    def test_commit_statuses(self):
        pending, failing = check_states([
            {"__typename": "StatusContext", "context": "deploy", "state": "PENDING"},
            {"__typename": "StatusContext", "context": "sec", "state": "ERROR", "targetUrl": "u"}])
        self.assertEqual((pending, failing), (["deploy"], [("sec", "u")]))


class TestFailureExcerpt(unittest.TestCase):
    LOG = "\n".join([
        "\ufeff2026-10-05T14:36:37.5889041Z Current runner version: '2.337.0'",
        "2026-10-05T14:40:00.0000000Z ##[group]Run npm run test:coverage",
        "2026-10-05T14:40:01.0000000Z - vitest-blob-1 (ID: 1, Size: 12, Expected Digest: sha256:abc)",
        "2026-10-05T14:40:02.0000000Z   \x1b[32m✓\x1b[39m says a write failed even when the server explained nothing",
        "2026-10-05T14:40:03.0000000Z ERROR: Coverage for functions (99.89%) does not meet threshold (100%)",
        "2026-10-05T14:40:04.0000000Z ##[error]Process completed with exit code 1.",
        "2026-10-05T14:40:05.0000000Z Post job cleanup.",
    ])

    def test_the_lines_that_say_what_failed_without_noise_or_timestamps(self):
        from ci import failure_excerpt
        self.assertEqual(failure_excerpt(self.LOG), [
            "ERROR: Coverage for functions (99.89%) does not meet threshold (100%)",
            "error: Process completed with exit code 1."])

    def test_with_nothing_telling_the_last_lines_are_used(self):
        from ci import failure_excerpt
        self.assertEqual(failure_excerpt("2026-10-05T14:40:00Z step one\n2026-10-05T14:40:01Z step two",
                                         max_lines=1), ["step two"])


class TestActionsRefused(unittest.TestCase):
    def run_(self, name, conclusion):
        return {"__typename": "CheckRun", "name": name, "status": "COMPLETED",
                "conclusion": conclusion, "completedAt": "2026-10-28T10:00:00Z",
                "detailsUrl": "https://x/job/1"}

    def test_github_refusing_to_run_the_jobs_is_read_from_their_annotations(self):
        run, seen = ci.run, []

        def gh(cmd, cwd=None):
            seen.append(cmd[2])
            return 0, ("The ubuntu-latest label will migrate\nThe job was not started because "
                       "your spending limit needs to be increased."), ""
        ci.run = gh
        self.addCleanup(setattr, ci, "run", run)
        failing = [("test", "https://github.com/o/r/actions/runs/7/job/42"), ("lint", None)]
        self.assertIn("spending limit", ci.actions_refused(failing, "."))
        self.assertEqual(seen, ["repos/o/r/check-runs/42/annotations"])
        self.assertEqual(ci.failed_runs(failing), ["7"])
        ci.run = lambda cmd, cwd=None: (0, "Process completed with exit code 1.", "")
        self.assertIsNone(ci.actions_refused(failing, "."))

    def test_a_run_that_skipped_every_check_has_not_started(self):
        rollup = [self.run_("test", "SKIPPED"), self.run_("lint", "SKIPPED")]
        self.assertEqual(ci.check_states(rollup), ([ci.CI_NOT_STARTED], []))
        self.assertEqual(ci.check_states(rollup + [self.run_("api", "SUCCESS")]), ([], []))


if __name__ == "__main__":
    unittest.main()
