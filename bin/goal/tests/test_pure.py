import datetime
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import goal  # noqa: E402

USAGE = """You are currently using your subscription to power your Claude Code usage

Current session: 61% used · resets Oct 27 at 3:30pm (Africa/Johannesburg)
Current week (all models): 22% used · resets Oct 31 at 11am (Africa/Johannesburg)
Current week (Fable): 0% used · resets Oct 31 at 11am (Africa/Johannesburg)

What's contributing to your limits usage?
Last 24h · 2081 requests · 671 sessions
  57%  Run fewer sessions at once · up to 221 at once
"""

ZONE = "Africa/Johannesburg"


def at(*parts):
    from zoneinfo import ZoneInfo
    return datetime.datetime(*parts, tzinfo=ZoneInfo(ZONE)).timestamp()


class TestUsage(unittest.TestCase):
    NOW = at(2026, 10, 27, 13, 0)

    def test_reads_each_limit_and_when_it_resets(self):
        limits = goal.parse_usage(USAGE, self.NOW)
        self.assertEqual([(l["name"], l["used"]) for l in limits],
                         [("Current session", 61), ("Current week (all models)", 22),
                          ("Current week (Fable)", 0)])
        self.assertEqual(limits[0]["resets_at"], at(2026, 10, 27, 15, 30))
        self.assertEqual(limits[1]["resets_at"], at(2026, 10, 31, 11, 0))

    def test_the_advice_lines_are_not_limits(self):
        self.assertEqual(len(goal.parse_usage(USAGE, self.NOW)), 3)

    def test_a_reset_with_only_a_time_is_the_next_one(self):
        self.assertEqual(goal.parse_reset("9:10pm (%s)" % ZONE, self.NOW), at(2026, 10, 27, 21, 10))
        self.assertEqual(goal.parse_reset("11am (%s)" % ZONE, self.NOW), at(2026, 10, 28, 11, 0))

    def test_a_reset_early_next_year(self):
        now = at(2026, 12, 30, 12, 0)
        self.assertEqual(goal.parse_reset("Jan 2 at 11am (%s)" % ZONE, now), at(2027, 1, 2, 11, 0))

    def test_under_the_threshold_is_nothing(self):
        self.assertIsNone(goal.over_threshold(goal.parse_usage(USAGE, self.NOW), 75))

    def test_over_it_the_pause_outlasts_the_last_to_reset(self):
        limits = [{"name": "session", "used": 80, "resets_at": 100},
                  {"name": "week", "used": 90, "resets_at": 900},
                  {"name": "other", "used": 10, "resets_at": 5000}]
        self.assertEqual(goal.over_threshold(limits, 75)["name"], "week")


class TestReports(unittest.TestCase):
    def test_the_lead_reports(self):
        self.assertEqual(goal.lead_report({"status": "done", "summary": "x"})[0], "done")
        self.assertEqual(goal.lead_report({"status": "progress"})[0], "progress")
        self.assertEqual(goal.lead_report(None)[0], "progress")
        asked = {"status": "question", "questions": [{"q": "Which?", "why": "it matters"}]}
        self.assertEqual(goal.lead_report(asked)[0], "question")

    def test_a_question_with_no_questions_is_progress(self):
        self.assertEqual(goal.lead_report({"status": "question", "questions": []})[0], "progress")

    def test_the_checker_verdict(self):
        self.assertEqual(goal.check_verdict({"verdict": "done", "gaps": []}), (True, []))
        self.assertEqual(goal.check_verdict({"verdict": "not_done", "gaps": ["no tests"]}),
                         (False, ["no tests"]))
        self.assertEqual(goal.check_verdict({"verdict": "done", "gaps": ["x"]}), (False, ["x"]))
        self.assertFalse(goal.check_verdict(None)[0])


class TestGoals(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_a_new_goal_is_listed_and_not_running(self):
        gid = goal.create(self.root, "123", "HRT1-519", "Recruiter's queue, first cut", base="feature/x")
        self.assertEqual(gid, "goal-hrt1-519-recruiter-s-queue-first")
        [listed] = goal.list_goals(self.root)
        self.assertEqual((listed["id"], listed["status"], listed["alive"]), (gid, "new", False))
        self.assertEqual((listed["base"], listed["url"]), ("feature/x", "https://app.asana.com/0/0/123"))
        self.assertEqual(goal.find_goal(self.root, "123")["id"], gid)
        self.assertIsNone(goal.find_goal(self.root, "456"))

    def test_the_same_ticket_again_gets_its_own_id(self):
        first = goal.create(self.root, "123", "A-1", "Thing")
        goal.Goal(self.root, first).update(cleared=True)
        self.assertEqual(goal.create(self.root, "123", "A-1", "Thing"), first + "-2")

    def test_the_title_is_the_key_and_the_name(self):
        self.assertEqual(goal.title_of({"key": "A-1", "name": "Do the thing"}), "A-1 Do the thing")
        self.assertEqual(len(goal.title_of({"name": "x" * 200})), 70)


class TestTheAsk(unittest.TestCase):
    def test_the_ask_is_the_ticket_and_what_hangs_off_it(self):
        task = {"ref": "1", "task_id": "A-1", "name": "Queue", "description": "Build the queue."}
        subtasks = [{"ref": "2", "task_id": "A-2", "name": "List", "description": "Show it."},
                    {"ref": "3", "name": "Done one", "completed": True}]
        comments = [{"author": "Sam", "text": "Use the new table."},
                    {"author": "bot", "text": goal.st.BOT_MARK + " started"}]
        attachments = [{"path": "/s/attachments/spec.md", "inline": "# Spec"}]
        ask = goal.ask_from_ticket(task, "https://x/1", subtasks, comments, attachments)
        self.assertTrue(ask.startswith("# A-1: Queue\nhttps://x/1\n\nBuild the queue.\n"))
        self.assertIn("### A-2: List\n\nShow it.", ask)
        self.assertNotIn("Done one", ask)
        self.assertIn("- Sam: Use the new table.", ask)
        self.assertNotIn("started", ask)
        self.assertIn("- `/s/attachments/spec.md`\n\n```\n# Spec\n```", ask)

    def test_a_bare_ticket_is_just_its_name(self):
        self.assertEqual(goal.ask_from_ticket({"ref": "1", "name": "Queue"}, "u"), "# 1: Queue\nu\n")

if __name__ == "__main__":
    unittest.main()
