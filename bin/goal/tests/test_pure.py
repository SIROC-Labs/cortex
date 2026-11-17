import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

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
        self.assertEqual(goal.check_verdict({"verdict": "done", "gaps": []}), (True, [], []))
        self.assertEqual(goal.check_verdict({"verdict": "not_done", "gaps": ["no tests"]}),
                         (False, ["no tests"], []))
        self.assertEqual(goal.check_verdict({"verdict": "done", "gaps": ["x"]}), (False, ["x"], []))
        asked = {"verdict": "done", "gaps": [], "questions": [{"q": "Six tiles or all?", "why": "w"}]}
        self.assertFalse(goal.check_verdict(asked)[0])
        self.assertEqual(goal.check_verdict(asked)[2][0]["q"], "Six tiles or all?")

    def test_no_verdict_is_not_a_gap(self):
        self.assertIsNone(goal.check_verdict(None))
        self.assertIsNone(goal.check_verdict({"status": "progress"}))
        self.assertIsNone(goal.review_verdict(None))
        self.assertEqual(goal.review_verdict({"gaps": ["no empty state (prototype: inbox)"]}),
                         (["no empty state (prototype: inbox)"], []))

    def test_the_lead_reports_the_analysis_finished(self):
        self.assertEqual(goal.lead_report({"status": "planned", "summary": "x"})[0], "planned")


JOURNAL = """# Journal

## References
- prototype: apps/frontend/src/tasks (decides the screens)

## Acceptance criteria
### Inbox
- [x] Inbox groups tasks by Late / Today / This week (prototype: inbox) — apps/inbox.tsx
- [ ] An empty Inbox says "Nothing to do" (prototype: inbox)

## Plan
1. [x] API
2. [ ] Inbox

## Decisions
- [ ] not a criterion
"""


class TestJournal(unittest.TestCase):
    def test_the_criteria_are_the_checklist_under_their_heading(self):
        self.assertEqual([t for _, t in goal.checklist(JOURNAL, "Acceptance criteria")],
                         ["Inbox groups tasks by Late / Today / This week (prototype: inbox) — apps/inbox.tsx",
                          'An empty Inbox says "Nothing to do" (prototype: inbox)'])
        self.assertEqual(goal.unmet_criteria(JOURNAL), ['An empty Inbox says "Nothing to do" (prototype: inbox)'])
        self.assertIsNone(goal.checklist(JOURNAL, "Risks"))

    def test_the_analysis_needs_references_criteria_and_a_plan(self):
        self.assertEqual(goal.plan_problems(JOURNAL), [])
        problems = goal.plan_problems("## Plan\n- [ ] build it\n")
        self.assertEqual(len(problems), 2)
        self.assertIn("References", problems[0])
        self.assertIn("Acceptance criteria", problems[1])

    def test_a_journal_without_criteria_has_none_unmet(self):
        self.assertEqual(goal.unmet_criteria("## Plan\n- [ ] x\n"), [])

    def test_gaps_go_to_the_lead_with_the_rule_that_the_prototype_wins(self):
        text = goal.gaps_prompt(["five extra tiles"], "The person was asked: …")
        self.assertIn("- five extra tiles", text)
        self.assertIn("The prototype wins", text)
        self.assertIn("Do not change what the prototype shows", text)
        self.assertIn("The person was asked", text)


class TestGoals(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_a_new_goal_is_listed_and_not_running(self):
        gid = goal.create(self.root, "Recruiter's queue, first cut\n\nMore detail.", base="feature/x")
        self.assertEqual(gid, "goal-recruiter-s-queue-first-cut")
        [listed] = goal.list_goals(self.root)
        self.assertEqual((listed["id"], listed["status"], listed["alive"]), (gid, "new", False))
        self.assertEqual((listed["base"], listed["name"], listed["key"]),
                         ("feature/x", "Recruiter's queue, first cut", None))
        self.assertEqual(listed["prompt"], "Recruiter's queue, first cut\n\nMore detail.")

    def test_a_ticket_s_key_comes_into_the_id(self):
        gid = goal.create(self.root, "Recruiter's queue", key="HRT1-519")
        self.assertEqual(gid, "goal-hrt1-519-recruiter-s-queue")

    def test_the_name_is_the_first_line_with_words_links_left_out(self):
        self.assertEqual(goal.prompt_name("\n## https://app.asana.com/0/1/2 Fix the badge\nmore"),
                         "Fix the badge")
        self.assertIsNone(goal.prompt_name("https://app.asana.com/0/1/2\n"))
        self.assertEqual(len(goal.prompt_name("word " * 40)), goal.NAME_WIDTH)

    def test_asana_links_are_found_once_each(self):
        self.assertEqual(goal.asana_urls("See https://app.asana.com/0/1/2. And (https://app.asana.com/0/1/3) "
                                         "and https://app.asana.com/0/1/2 again"),
                         ["https://app.asana.com/0/1/2", "https://app.asana.com/0/1/3"])

    def test_the_same_ticket_again_gets_its_own_id(self):
        first = goal.create(self.root, "Thing", key="A-1", name="Thing")
        goal.Goal(self.root, first).update(cleared=True)
        self.assertEqual(goal.create(self.root, "Thing", key="A-1", name="Thing"), first + "-2")

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

    def test_an_html_attachment_is_its_text_and_points_to_the_file(self):
        page = ("<html><head><style>.a{color:red}</style><script>var x = 1;</script></head>"
                "<body><h2>The rules</h2><table><tr><td>Due</td><td>A day</td></tr></table>"
                "<ul><li>Tasks</li><li>Notes</li></ul></body></html>")
        ask = goal.ask_from_ticket({"ref": "1", "name": "Q"}, "u", (), (),
                                   [{"path": "/s/attachments/Plan.html", "inline": page}])
        self.assertIn("The file itself holds the prototype", ask)
        self.assertIn("## The rules", ask)
        self.assertIn("| Due | A day", ask)
        self.assertIn("- Tasks", ask)
        self.assertNotIn("color:red", ask)
        self.assertNotIn("var x", ask)

    def test_an_attached_one_pager_is_named_but_not_read(self):
        ask = goal.ask_from_ticket({"ref": "1", "name": "Q"}, "u", (), (),
                                   [{"path": "/s/attachments/Guided-call-one-pager.md", "inline": "Scope: X"}])
        self.assertIn("a one-pager. It is not used", ask)
        self.assertNotIn("Scope: X", ask)

    def test_every_prompt_that_judges_the_work_gets_the_same_source_rule(self):
        for name in ("lead.md", "check.md", "review.md", "consult.md"):
            text = goal.render(os.path.join(goal.PROMPTS, name), sources=goal.SOURCES)
            self.assertIn("explicitly", text, name)
            self.assertNotIn("{{sources}}", text, name)
            self.assertNotIn("the one-pager or spec does", text, name)

    def test_a_bare_ticket_is_just_its_name(self):
        self.assertEqual(goal.ask_from_ticket({"ref": "1", "name": "Queue"}, "u"), "# 1: Queue\nu\n")

    def test_the_ask_is_the_prompt_its_files_and_its_tickets(self):
        files = [{"path": "/s/inputs/shot.png", "is_image": True},
                 {"path": "/s/inputs/notes.md", "inline": "- keep it short"}]
        ask = goal.ask_from_prompt("Fix the badge.\nhttps://app.asana.com/0/1/2\n", files,
                                   ["# A-1: Badge\nhttps://app.asana.com/0/1/2\n"])
        self.assertTrue(ask.startswith("# The ask\n\nFix the badge.\nhttps://app.asana.com/0/1/2\n\n"
                                       "## Files given with it\n\n- `/s/inputs/shot.png` (an image)\n"))
        self.assertIn("- `/s/inputs/notes.md`\n\n```\n- keep it short\n```", ask)
        self.assertTrue(ask.endswith("\n# A-1: Badge\nhttps://app.asana.com/0/1/2\n"))

    def test_a_given_file_says_whether_it_is_an_image_and_inlines_small_text(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        for name, body in (("a.PNG", b"\x89PNG"), ("b.txt", b"hello"), ("c.bin", b"\xff\xfe")):
            with open(os.path.join(d, name), "wb") as f:
                f.write(body)
        self.assertEqual(goal.file_entry(os.path.join(d, "a.PNG"), "inputs/a.PNG"),
                         {"path": os.path.join(d, "a.PNG"), "is_image": True})
        self.assertEqual(goal.file_entry(os.path.join(d, "b.txt"), "inputs/b.txt")["inline"], "hello")
        self.assertNotIn("inline", goal.file_entry(os.path.join(d, "c.bin"), "inputs/c.bin"))

def msg(at, mid, model, out, cache_read=0):
    import json
    return json.dumps({"timestamp": at, "message": {"id": mid, "model": model, "usage": {
        "input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": 0}}})


class TestBreakdown(unittest.TestCase):
    def test_each_message_counts_once_and_only_since_the_call_began(self):
        lines = [msg("2026-10-28T10:00:00Z", "a", "m", 1),
                 msg("2026-10-28T11:00:00Z", "b", "m", 5),
                 msg("2026-10-28T11:00:03Z", "b", "m", 5),
                 msg("2026-10-28T11:01:00Z", "c", "m", 7, cache_read=100)]
        since = goal._when("2026-10-28T10:30:00Z")
        use = goal.transcript_usage(lines, since)
        self.assertEqual(use["tokens"], {"input": 20, "output": 12, "cache_read": 100, "cache_write": 0})
        self.assertEqual(use["last"] - use["first"], 60)
        self.assertIsNone(goal.transcript_usage(lines, goal._when("2026-10-29T00:00:00Z")))

    def test_a_model_s_cost_is_shared_by_weighted_tokens(self):
        costs = goal.unit_costs({"m": {"inputTokens": 100, "outputTokens": 100, "costUSD": 6.0}})
        self.assertAlmostEqual(costs["m"], 0.01)
        entry = goal.priced({"model": "m", "tokens": {"input": 0, "output": 20, "cache_read": 0,
                                                      "cache_write": 0}}, costs)
        self.assertAlmostEqual(entry["cost"], 1.0)
        self.assertIsNone(goal.priced({"model": "x", "tokens": entry["tokens"]}, costs)["cost"])

    def test_the_report_has_totals_by_role_then_each_call(self):
        tokens = {"input": 1000, "output": 2000, "cache_read": 0, "cache_write": 0}
        calls = [{"label": "lead", "round": 1, "model": "claude-opus-5-5", "effort": None,
                  "started": 0, "cost": 3.0,
                  "main": {"model": "claude-opus-5-5", "tokens": tokens, "seconds": 600, "cost": 2.0},
                  "subagents": [{"description": "Build the exporter", "model": "claude-sonnet-5-5",
                                 "tokens": tokens, "seconds": 300, "cost": 1.0}]},
                 {"label": "check", "round": 1, "model": "claude-fable-5-1", "effort": "xhigh",
                  "started": 0, "cost": 4.0,
                  "main": {"model": "claude-fable-5-1", "tokens": tokens, "seconds": 120, "cost": 4.0},
                  "subagents": []}]
        report = goal.usage_report(calls)
        self.assertIn("All calls: 12m 00s · 9k · ≈ $7.00", report)
        for line in ("lead (1)", "sub-agents (1)", "checker (1)", "Round 1 · opus", "Check 1 · fable xhigh effort",
                     "Build the exporter"):
            self.assertIn(line, report)


class TestGate(unittest.TestCase):
    def git(self, *args, cwd=None):
        import subprocess
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                              cwd=cwd or self.work, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        import json, subprocess
        self.dir = tempfile.mkdtemp()
        origin, self.work = os.path.join(self.dir, "origin.git"), os.path.join(self.dir, "work")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
        subprocess.run(["git", "clone", "-q", origin, self.work], check=True, capture_output=True)
        self.git("checkout", "-q", "-b", "main")
        self.commit("shared.txt", "base\n", "base")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "-b", "A-1/goal-x")
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        goal.Goal(self.dir, gid).update(worktree=self.work, branch="A-1/goal-x", pr_url="https://gh/pr/1")
        self.runner = goal.Runner(self.dir, gid)
        self.runner.wait_for_usage = lambda: None
        self.gh, self.rollup = [], []
        run, sleep = goal.st.run, goal.time.sleep

        def fake(cmd, cwd=None, check=True):
            if cmd[0] != "gh":
                return run(cmd, cwd=cwd, check=check)
            self.gh.append(cmd[1:3])
            if cmd[1:3] == ["pr", "view"]:
                head = self.git("rev-parse", "HEAD").strip()
                return 0, json.dumps({"headRefOid": head, "statusCheckRollup": self.rollup}), ""
            if cmd[1] == "api":
                return 0, "2026-10-28T10:00:00.0000000Z FAILED tests/test_x.py::test_y\n", ""
            return 0, "", ""
        goal.st.run = fake
        goal.time.sleep = lambda _: None
        self.addCleanup(setattr, goal.st, "run", run)
        self.addCleanup(setattr, goal.time, "sleep", sleep)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def commit(self, path, text, message):
        with open(os.path.join(self.work, path), "w") as f:
            f.write(text)
        self.git("add", path)
        self.git("commit", "-q", "-m", message)

    def check(self, name, conclusion):
        return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": conclusion,
                "detailsUrl": "https://github.com/o/r/actions/runs/1/job/2"}

    def test_failing_ci_goes_back_to_the_lead_with_its_log(self):
        self.commit("app.py", "x", "work")
        self.rollup = [self.check("test", "FAILURE"), self.check("lint", "SUCCESS")]
        kind, fix = self.runner.gate()
        self.assertEqual(kind, "ci")
        self.assertIn("- `test` (https://github.com/o/r/actions/runs/1/job/2)", fix)
        self.assertIn("FAILED tests/test_x.py::test_y", fix)
        self.assertIn(["pr", "ready"], self.gh)
        self.assertEqual(self.git("rev-parse", "origin/A-1/goal-x"), self.git("rev-parse", "HEAD"))

    def test_passing_ci_is_recorded_and_the_pr_is_marked_ready_once(self):
        self.rollup = [self.check("test", "SUCCESS"), self.check("lint", "SUCCESS")]
        self.assertEqual(self.runner.gate(), (None, None))
        self.assertEqual(self.runner.gate(), (None, None))
        self.assertEqual(self.runner.data["checks"], ["lint", "test"])
        self.assertEqual(self.gh.count(["pr", "ready"]), 1)
        self.assertIn("CI passed: `lint`, `test`", goal.checks_section(self.runner.data["checks"]))

    def test_a_run_that_skipped_everything_is_not_a_pass(self):
        skipped = dict(self.check("test", "SKIPPED"), startedAt="2026-10-28T12:07:28Z")
        real = dict(self.check("test", "FAILURE"), startedAt="2026-10-28T12:11:43Z")
        polls = [[skipped], [skipped], [skipped, real]]
        run = goal.st.run

        def view(cmd, cwd=None, check=True):
            if cmd[1:3] == ["pr", "view"] and polls:
                self.rollup = polls.pop(0)
            return run(cmd, cwd=cwd, check=check)
        goal.st.run = view
        kind, fix = self.runner.gate()
        self.assertEqual(kind, "ci")
        self.assertIn("- `test`", fix)

    def test_the_pr_is_ready_before_the_push_and_an_all_skipped_run_is_started_again(self):
        order = []
        push = self.runner.push
        self.runner.push = lambda: (order.append("push"), push())
        run = goal.st.run

        def watch(cmd, cwd=None, check=True):
            if cmd[:3] == ["gh", "pr", "ready"]:
                order.append(" ".join(cmd[1:4]))
                if "--undo" not in cmd and order.count("pr ready https://gh/pr/1") > 1:
                    self.rollup = [self.check("test", "SUCCESS")]
            return run(cmd, cwd=cwd, check=check)
        goal.st.run = watch
        self.rollup = [self.check("test", "SKIPPED")]
        nudge, goal.CI_NUDGE = goal.CI_NUDGE, 0
        self.addCleanup(setattr, goal, "CI_NUDGE", nudge)
        self.assertEqual(self.runner.gate(), (None, None))
        self.assertEqual(order[:2], ["pr ready https://gh/pr/1", "push"])
        self.assertIn("pr ready --undo", order)
        self.assertEqual(self.runner.data["checks"], ["test"])

    def test_a_pr_with_no_checks_at_all_counts_as_having_no_ci(self):
        start, goal.CI_START = goal.CI_START, 0
        self.addCleanup(setattr, goal, "CI_START", start)
        self.assertEqual(self.runner.gate(), (None, None))
        self.assertEqual(self.runner.data["checks"], [])

    def test_work_merged_into_the_goal_s_branch_on_github_is_merged_in_before_the_push(self):
        self.git("push", "-q", "origin", "A-1/goal-x")
        self.commit("from-a-pr.txt", "x\n", "a PR merged into the goal's branch")
        self.git("push", "-q", "origin", "A-1/goal-x")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.commit("goal.txt", "x\n", "the goal's own work")
        self.rollup = [self.check("test", "SUCCESS")]
        self.assertEqual(self.runner.gate(), (None, None))
        self.assertTrue(os.path.exists(os.path.join(self.work, "from-a-pr.txt")))
        self.assertEqual(self.git("rev-parse", "origin/A-1/goal-x"), self.git("rev-parse", "HEAD"))

    def test_the_base_is_merged_in_and_a_conflict_goes_back_to_the_lead(self):
        self.commit("shared.txt", "goal\n", "work")
        self.git("checkout", "-q", "main")
        self.commit("shared.txt", "main\n", "elsewhere")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "A-1/goal-x")
        kind, fix = self.runner.gate()
        self.assertEqual(kind, "merge")
        self.assertIn("conflicts in:\n\n- `shared.txt`", fix)
        self.assertNotIn(["pr", "ready"], self.gh)

    def test_failing_ci_goes_to_the_fixer_on_the_lead_s_model_first(self):
        self.rollup = [self.check("test", "FAILURE")]
        calls = []

        def call(prompt, session, resume, label, model=None, effort=None):
            calls.append((label, model, prompt))
            self.commit("fix.py", "fixed", "fix")
            self.rollup = [self.check("test", "SUCCESS")]
            return None, None, None
        self.runner.call = call
        self.assertEqual(self.runner.sync_and_ci(), (None, None))
        [(label, model, prompt)] = calls
        self.assertEqual((label, model), ("ci-fix", self.runner.data["model"]))
        self.assertIn("Do not explore", prompt)
        self.assertIn("- `test` (https://github.com/o/r/actions/runs/1/job/2)", prompt)
        self.assertIn("Never weaken a check", prompt)

    def test_a_fix_cut_off_by_the_usage_limit_is_not_a_try(self):
        self.rollup = [self.check("test", "FAILURE")]
        calls = []

        def call(prompt, session, resume, label, model=None, effort=None):
            calls.append(label)
            if len(calls) == 1:
                return None, "usage", None
            self.commit("fix.py", "fixed", "fix")
            self.rollup = [self.check("test", "SUCCESS")]
            return None, None, None
        self.runner.call = call
        self.assertEqual(self.runner.sync_and_ci(), (None, None))
        self.assertEqual(calls, ["ci-fix", "ci-fix"])

    def test_ci_that_the_fixer_cannot_fix_goes_to_the_lead(self):
        self.rollup = [self.check("test", "FAILURE")]
        calls = []

        def call(*a, **k):
            calls.append(a)
            self.commit("fix.py", "try %d" % len(calls), "fix")
            return None, None, None
        self.runner.call = call
        kind, fix = self.runner.sync_and_ci()
        self.assertEqual((kind, len(calls)), ("ci", goal.CI_FIXES))
        self.assertIn("You reported done. CI ran on the PR", fix)

    def test_a_fixer_that_commits_nothing_hands_over_without_another_ci_run(self):
        self.rollup = [self.check("test", "FAILURE")]
        calls = []
        self.runner.call = lambda *a, **k: calls.append(a) or (None, None, None)
        kind, _ = self.runner.sync_and_ci()
        self.assertEqual((kind, len(calls)), ("ci", 1))
        self.assertEqual(self.gh.count(["pr", "view"]), 1)

    def test_ci_is_judged_only_once_the_whole_run_is_over(self):
        running = {"__typename": "CheckRun", "name": "e2e", "status": "IN_PROGRESS"}
        polls = [[self.check("test", "FAILURE"), running], [self.check("test", "FAILURE"), running],
                 [self.check("test", "FAILURE"), self.check("e2e", "FAILURE")]]
        run = goal.st.run

        def view(cmd, cwd=None, check=True):
            if cmd[1:3] == ["pr", "view"] and polls:
                self.rollup = polls.pop(0)
            return run(cmd, cwd=cwd, check=check)
        goal.st.run = view
        kind, fix = self.runner.gate()
        self.assertEqual((kind, polls), ("ci", []))
        self.assertIn("- `e2e`", fix)
        self.assertIn("- `test`", fix)

    def test_ci_github_refused_to_run_goes_to_the_person_and_is_re_run(self):
        self.rollup = [self.check("test", "FAILURE")]
        asked, refused = [], goal.actions_refused
        goal.actions_refused = lambda failing, cwd: "The job was not started because of billing"
        self.addCleanup(setattr, goal, "actions_refused", refused)

        def ask(headline, detail=None):
            asked.append(headline)
            self.rollup = [self.check("test", "SUCCESS")]
            return "fixed"
        self.runner.ask_problem = ask
        self.runner.call = lambda *a, **k: self.fail("no fixer for a billing problem")
        self.assertEqual(self.runner.sync_and_ci(), (None, None))
        self.assertIn("GitHub did not run CI", asked[0])
        self.assertIn(["run", "rerun"], self.gh)

    def test_the_checker_is_told_what_ci_passed(self):
        self.assertIn("CI runs once this check is clean", goal.checks_text("main"))

class TestScopedCheck(unittest.TestCase):
    git, commit, tearDown = TestGate.git, TestGate.commit, TestGate.tearDown

    def setUp(self):
        TestGate.setUp(self)
        self.runner.set(ask="# A-1: x")

    def judged(self):
        prompts = []

        def judge(label, template, read):
            prompts.append(goal.render(os.path.join(goal.PROMPTS, template), **self.runner.fields()))
            return self.verdicts.pop(0)
        self.runner.judge = judge
        return prompts

    def test_a_check_after_a_check_covers_only_its_gaps_and_what_changed(self):
        self.verdicts = [(False, ["The inbox has no empty state (prototype: inbox)"], []),
                         (True, [], [])]
        prompts = self.judged()
        self.runner.check()
        first = self.git("rev-parse", "HEAD").strip()
        self.commit("inbox.ts", "empty\n", "empty state")
        self.runner.check()
        self.assertNotIn("What this check covers", prompts[0])
        self.assertIn("at commit `%s`, found these gaps" % first, prompts[1])
        self.assertIn("- The inbox has no empty state", prompts[1])
        self.assertIn("git log -p --first-parent --no-merges %s..HEAD" % first, prompts[1])
        self.assertEqual(self.runner.data["last_gaps"], [])

    def test_a_revision_is_checked_against_its_review_comments(self):
        self.verdicts = [(True, [], []), (True, [], [])]
        prompts = self.judged()
        self.runner.check()
        self.runner.set(revision_ask="### Comment by @j\n\nRename the button.")
        self.commit("button.ts", "renamed\n", "rename")
        self.runner.check()
        self.assertIn("found the work done", prompts[1])
        self.assertIn("Rename the button.", prompts[1])
        self.assertIn("Each review comment", prompts[1])
        self.assertIsNone(self.runner.data["revision_ask"])

    def test_a_split_goal_checks_how_its_parts_meet(self):
        self.verdicts = [(True, [], [])]
        prompts = self.judged()
        merged = self.git("rev-parse", "HEAD").strip()
        self.runner.set(parts_merged_head=merged)
        self.commit("glue.ts", "x\n", "integrate")
        self.runner.check()
        self.assertIn("Do not check the parts' criteria again", prompts[0])
        self.assertIn("%s..HEAD" % merged, prompts[0])

    def test_a_rewritten_branch_is_checked_whole(self):
        self.verdicts = [(True, [], [])]
        prompts = self.judged()
        self.runner.set(checked_head="0" * 40)
        self.runner.check()
        self.assertNotIn("What this check covers", prompts[0])


class TestRunTasks(unittest.TestCase):
    git, commit, tearDown = TestGate.git, TestGate.commit, TestGate.tearDown

    def setUp(self):
        TestGate.setUp(self)
        self.runner.set(ask="# A-1: x", round=3)
        self.runner.usage = lambda: []
        self.runner.wait_for_usage = lambda: None
        os.makedirs(os.path.join(self.work, "app", "node_modules"))
        self.commit("app/a.ts", "a\n", "app")
        bindir = os.path.join(self.dir, "bin")
        os.makedirs(bindir)
        # A claude that writes the file its brief names, or answers a question.
        with open(os.path.join(bindir, "claude"), "w") as f:
            f.write("""#!/usr/bin/env python3
import json, os, subprocess, sys
prompt = sys.argv[-1]
if "You answer one question" in prompt:
    block = {"status": "done", "answer": "it is in app/a.ts"}
else:
    name = prompt.split("WRITE:")[1].split()[0]
    if os.environ.get("TASK_LOG"):
        with open(os.environ["TASK_LOG"], "a") as f:
            f.write("start %s\\n" % name)
    if "SLOW" in prompt:
        import time
        time.sleep(3)
    with open(name, "w") as f:
        f.write(os.getcwd() + "\\n")
    assert os.path.islink("app/node_modules")
    if "FAIL" in prompt:
        sys.exit(1)
    if "COMMIT" in prompt:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name], check=True)
    block = {"status": "done", "summary": "wrote " + name, "files": [name]}
print(json.dumps({"type": "result", "subtype": "success", "result": "```json\\n" + json.dumps(block) + "\\n```"}))
""")
        os.chmod(os.path.join(bindir, "claude"), 0o755)
        self.addCleanup(os.environ.__setitem__, "PATH", os.environ["PATH"])
        os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

    def test_tasks_run_in_their_own_worktrees_and_merge_back(self):
        os.makedirs(os.path.join(self.work, "app"), exist_ok=True)
        reports = self.runner.run_tasks([
            {"name": "One", "kind": "code", "brief": "WRITE: one.txt COMMIT"},
            {"name": "Two", "kind": "code", "brief": "WRITE: two.txt"},
            {"name": "Clash", "kind": "code", "brief": "WRITE: shared.txt COMMIT"},
            {"name": "Where", "kind": "explore", "brief": "Where is a?"}])
        self.assertEqual([r["merge"] for r in reports[:3]], ["merged", "merged", "merged"])
        self.assertEqual(reports[3]["answer"], "it is in app/a.ts")
        for name in ("one.txt", "two.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.work, name)))
        self.assertNotIn("node_modules", self.git("ls-files"))
        self.assertEqual(self.git("worktree", "list").count("\n"), 1)
        self.assertNotIn("--r3-", self.git("branch"))
        prompt = goal.dispatched_prompt(reports)
        self.assertIn("### One (coding task): done", prompt)
        self.assertIn("- Answer: it is in app/a.ts", prompt)

    def test_a_free_slot_starts_the_next_task_without_waiting_for_the_slowest(self):
        log = os.path.join(self.dir, "tasks.log")
        self.addCleanup(os.environ.pop, "TASK_LOG", None)
        os.environ["TASK_LOG"] = log
        parallel, goal.PARALLEL_TASKS = goal.PARALLEL_TASKS, 2
        self.addCleanup(setattr, goal, "PARALLEL_TASKS", parallel)
        slow_done = []
        end = self.runner.end_task

        def ended(run):
            if run["name"] == "Slow":
                with open(log) as f:
                    slow_done.append(f.read())
            return end(run)
        self.runner.end_task = ended
        reports = self.runner.run_tasks([
            {"name": "Slow", "kind": "code", "brief": "WRITE: slow.txt SLOW"},
            {"name": "Quick", "kind": "code", "brief": "WRITE: quick.txt"},
            {"name": "Next", "kind": "code", "brief": "WRITE: next.txt"}])
        self.assertEqual([r["merge"] for r in reports], ["merged"] * 3)
        self.assertIn("start next.txt", slow_done[0])

    def test_a_task_that_conflicts_keeps_its_branch_for_the_lead(self):
        reports = self.runner.run_tasks([
            {"name": "A", "kind": "code", "brief": "WRITE: same.txt COMMIT"},
            {"name": "B", "kind": "code", "brief": "WRITE: same.txt COMMIT"}])
        merges = sorted(r["merge"] for r in reports)
        self.assertEqual(merges[0], "merged")
        self.assertIn("not merged", merges[1])
        self.assertIn("`same.txt`", merges[1])
        self.assertEqual(self.git("status", "--porcelain").strip(), "")

    def test_a_task_that_fails_is_not_merged(self):
        reports = self.runner.run_tasks([{"name": "Broken", "kind": "code", "brief": "WRITE: half.txt FAIL"}])
        self.assertEqual(reports[0]["status"], "failed")
        self.assertIn("did not finish", reports[0]["merge"])
        self.assertIn("A-1/goal-x--r3-1", self.git("branch"))


class TestQuestionOptions(unittest.TestCase):
    def test_a_question_s_options_reach_the_lead(self):
        qs = goal.st.parse_agent_questions({"questions": [{
            "title": "Quality review: who reviews a junior?", "q": "Who reviews a junior's call?",
            "options": [{"label": "A. As in the prototype", "flow": ["Anna reaches the review step.",
                                                                    "Tom clicks Accepted."],
                         "means": "Drops the extra routing."}, {"label": ""}, "junk"],
            "recommend": "A: the prototype decides the UI.", "why": "The references disagree."}]})
        self.assertEqual([o["label"] for o in qs[0]["options"]], ["A. As in the prototype"])
        self.assertIn("(options: A. As in the prototype)", goal.answer_prompt(qs, "A"))


class TestLocalCI(unittest.TestCase):
    git, commit, tearDown = TestGate.git, TestGate.commit, TestGate.tearDown

    def setUp(self):
        TestGate.setUp(self)
        self.runner.set(ask="# A-1: x")
        self.commit("Makefile", "ci-verify:\n\t@echo ok\n", "make")
        os.makedirs(os.path.join(self.work, "apps", "web"))
        self.commit("apps/web/package.json", json.dumps({"scripts": {"ci-verify": "x"}}), "web")
        self.commit("apps/other.json", "{}", "other")

    def test_ci_s_own_static_checks_are_found_as_steps(self):
        self.assertEqual(goal.ci_commands(self.work), [
            ("make ci-verify", "make ci-verify", None),
            ("apps/web: x", "x", "apps/web")])

    def test_each_step_of_a_chain_is_its_own_step(self):
        scripts = {"ci-verify": "npm audit && npm run verify:static && tools/x.sh",
                   "verify:static": "tsc -b && npm run lint && npm run fmt",
                   "lint": "NODE_OPTIONS=--max-old-space-size=4096 eslint .",
                   "fmt": "prettier --check . || true"}
        self.assertEqual(goal.script_steps(scripts, "ci-verify"), [
            "npm audit", "tsc -b", "NODE_OPTIONS=--max-old-space-size=4096 eslint .",
            "npm run fmt", "tools/x.sh"])

    def test_a_make_target_s_prerequisites_are_steps(self):
        self.commit("Makefile", "ci-verify: lint typecheck ## static\n\t@echo ok\n", "make")
        self.assertEqual(goal.ci_commands(self.work)[:2], [
            ("make lint", "make lint", None), ("make typecheck", "make typecheck", None)])

    def test_every_step_runs_past_a_failure(self):
        steps = [("one", "echo first; exit 1", None), ("two", "echo fine", None),
                 ("three", "echo third >&2; exit 2", None)]
        failures = goal.run_ci_steps(steps, self.work)
        self.assertEqual([(f[0], f[2].strip()) for f in failures], [("one", "first"), ("three", "third")])

    def test_every_failure_goes_to_the_fixer_at_once_then_to_the_lead(self):
        results = [[("apps/web: x", "x", "2 errors"), ("make ci-verify", "make ci-verify", "a.ts")]] * 3
        goal.run_ci_steps, run = (lambda steps, worktree: results.pop(0) if results else []), goal.run_ci_steps
        self.addCleanup(setattr, goal, "run_ci_steps", run)
        fixes = []

        def call(prompt, session, resume, label, model=None, effort=None):
            fixes.append((prompt, model))
            self.commit("fix%d.txt" % len(fixes), "x\n", "fix")
            return None, None, None
        self.runner.call = call
        fix = self.runner.local_ci()
        self.assertEqual(len(fixes), 2)
        prompt, model = fixes[0]
        self.assertEqual(model, self.runner.data["model"])
        self.assertIn("2 errors", prompt)
        self.assertIn("a.ts", prompt)
        self.assertIn("  - `x` in `apps/web`\n  - `make ci-verify`\n", prompt)
        self.assertIn("Do not explore", prompt)
        self.assertIn("these fail", fix)
        self.assertEqual(goal.fix_signature(fix), ["apps/web: x", "make ci-verify"])

    def test_passing_checks_go_on(self):
        goal.run_ci_steps, run = (lambda steps, worktree: []), goal.run_ci_steps
        self.addCleanup(setattr, goal, "run_ci_steps", run)
        self.assertIsNone(self.runner.local_ci())


class TestPause(unittest.TestCase):
    def test_a_goal_goes_back_to_what_it_was_doing_after_a_pause(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        gid = goal.create(d, "x", key="A-1", name="x", base="main")
        runner = goal.Runner(d, gid)
        runner.set(status="checking", doing="checking the branch against the ask")
        readings = [[{"name": "Current session", "used": 80, "resets_at": time.time()}], []]
        runner.usage = lambda: readings.pop(0)
        runner.threshold = lambda: 75
        sleep, goal.time.sleep = goal.time.sleep, lambda _: None
        self.addCleanup(setattr, goal.time, "sleep", sleep)
        runner.wait_for_usage()
        self.assertEqual((runner.data["status"], runner.data["doing"]),
                         ("checking", "checking the branch against the ask"))


class TestFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        goal.Goal(self.dir, gid).update(worktree=self.dir, branch="A-1/goal-x", ask="# A-1: x",
                                        session="s", session_used=True, flow=None)
        self.runner = goal.Runner(self.dir, gid)
        self.runner.set_up = lambda: None
        self.runner.head = lambda: "same"
        self.events = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def journal(self, text):
        with open(self.runner.goal.journal, "w") as f:
            f.write(text)

    def test_older_flow_analysis_then_review_then_build_then_one_push_and_a_check(self):
        rounds = [
            ("planned", lambda: self.journal("## Plan\n- [ ] x\n")),
            ("planned", lambda: self.journal(JOURNAL)),
            ("done", lambda: None),
            ("done", lambda: self.journal(JOURNAL.replace("- [ ] An empty", "- [x] An empty"))),
        ]
        prompts = []

        def lead(prompt):
            prompts.append(prompt)
            report, write = rounds.pop(0)
            write()
            self.events.append("lead %s (%s)" % (report, self.runner.data["phase"]))
            return report, {"summary": "s"}
        self.runner.lead = lead
        self.runner.review = lambda: self.events.append("review") or (["no error state"], [])
        self.runner.sync = lambda: self.events.append("sync") or None
        self.runner.sync_and_ci = lambda: self.events.append("push and CI") or (None, None)
        self.runner.check = lambda: self.events.append("check") or (True, [], [])
        self.runner.finish = lambda block: self.events.append("finish")
        self.runner.push = lambda: self.fail("nothing is pushed outside the gate")
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(self.events, ["lead planned (planning)", "lead planned (planning)", "review",
                                       "lead done (building)", "lead done (building)",
                                       "sync", "check", "push and CI", "finish"])
        self.assertIn("References", prompts[1])
        self.assertIn("- no error state", prompts[2])
        self.assertIn("not ticked", prompts[3])

    def test_each_step_and_each_fix_of_the_build_starts_a_new_session(self):
        self.journal(JOURNAL.replace("- [ ] An empty", "- [x] An empty"))
        self.runner.set(phase="building", reviewed=True)
        reports = [("step", {"summary": "API done", "handoff": "The tasks API returns due days."}),
                   ("done", {"summary": "s"}), ("done", {"summary": "s"})]
        calls = []

        def lead(prompt):
            calls.append((self.runner.data.get("session"), prompt))
            self.runner.set(session="used", session_used=True)
            return reports.pop(0)
        self.runner.lead = lead
        verdicts = [(False, ["a gap"], []), (True, [], [])]
        self.runner.sync = lambda: None
        self.runner.check = lambda: verdicts.pop(0)
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.finish = lambda block: None
        self.runner.watch_pr = lambda: None
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(len(calls), 3)
        self.assertIsNone(calls[1][0])
        self.assertIn("The tasks API returns due days.", calls[1][1])
        self.assertIn("This is a new session", calls[1][1])
        self.assertIsNone(calls[2][0])
        self.assertIn("a gap", calls[2][1])

    def test_the_lead_hands_tasks_to_the_runner_and_gets_their_reports_in_a_new_session(self):
        self.journal(JOURNAL.replace("- [ ] An empty", "- [x] An empty"))
        self.runner.set(phase="building", reviewed=True)
        tasks = [{"name": "Inbox", "kind": "code", "brief": "Build the inbox."}]
        reports = [("dispatch", {"status": "dispatch", "tasks": tasks}), ("done", {"summary": "s"})]
        calls, ran = [], []

        def lead(prompt):
            calls.append((self.runner.data.get("session"), prompt))
            self.runner.set(session="used", session_used=True)
            return reports.pop(0)
        self.runner.lead = lead
        self.runner.run_tasks = lambda t: ran.append(t) or [
            {"name": "Inbox", "kind": "code", "status": "done", "summary": "Built it.", "merge": "merged"}]
        self.runner.sync = lambda: None
        self.runner.check = lambda: (True, [], [])
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.finish = lambda block: None
        self.runner.watch_pr = lambda: None
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(ran, [tasks])
        self.assertIsNone(calls[1][0])
        self.assertIn("### Inbox (coding task): done", calls[1][1])
        self.assertIn("- Did: Built it.", calls[1][1])
        self.assertEqual(goal.lead_report({"status": "dispatch", "tasks": []})[0], "progress")

    def test_a_gap_goes_back_to_the_lead_before_anything_is_pushed(self):
        done = JOURNAL.replace("- [ ] An empty", "- [x] An empty")
        self.journal(done)
        self.runner.set(phase="building", reviewed=True)
        self.runner.lead = lambda prompt: self.events.append("lead") or ("done", {"summary": "s"})
        verdicts = [(False, ["a gap"], []), (True, [], [])]
        self.runner.sync = lambda: self.events.append("sync") or None
        self.runner.check = lambda: self.events.append("check") or verdicts.pop(0)
        self.runner.sync_and_ci = lambda: self.events.append("push and CI") or (None, None)
        self.runner.finish = lambda block: self.events.append("finish")
        self.runner.watch_pr = lambda: None
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(self.events, ["lead", "sync", "check", "lead", "sync", "check",
                                       "push and CI", "finish"])


    def test_a_fix_that_makes_progress_does_not_count_towards_asking_the_person(self):
        done = JOURNAL.replace("- [ ] An empty", "- [x] An empty")
        self.journal(done)
        self.runner.set(phase="building", reviewed=True)
        self.runner.lead = lambda prompt: ("done", {"summary": "s"})
        self.runner.decide = lambda prompt: prompt
        fails = ["- `make lint`, run here", "- `a: tsc -b`, run here", "- `a: prettier`, run here",
                 "- `a: test import`, run here", "- `a: bundle size`, run here", None]
        self.runner.sync = lambda: None
        self.runner.local_ci = lambda: fails.pop(0)
        self.runner.check = lambda: (True, [], [])
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.finish = lambda block: self.events.append("finish")
        self.runner.watch_pr = lambda: None
        self.runner.ask_problem = lambda *a: self.fail("progress is not a reason to ask")
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(self.events, ["finish"])

    def test_the_same_failure_again_and_again_goes_to_the_person(self):
        done = JOURNAL.replace("- [ ] An empty", "- [x] An empty")
        self.journal(done)
        self.runner.set(phase="building", reviewed=True)
        self.runner.lead = lambda prompt: ("done", {"summary": "s"})
        self.runner.decide = lambda prompt: prompt
        fails = ["- `a: bundle size`, run here"] * goal.MAX_CHECKS + [None]
        asked = []
        self.runner.sync = lambda: None
        self.runner.local_ci = lambda: fails.pop(0)
        self.runner.check = lambda: (True, [], [])
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.finish = lambda block: None
        self.runner.watch_pr = lambda: None
        self.runner.ask_problem = lambda headline, detail: asked.append(headline) or "go on"
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(len(asked), 1)


PARTS = {"parts": [
    {"name": "API", "after": [], "brief": "The tasks API.", "criteria": ["A task has a due day (one-pager §2)"]},
    {"name": "Inbox", "after": ["API"], "brief": "The inbox screen.",
     "criteria": ['An empty Inbox says "Nothing to do" (prototype: inbox)']},
    {"name": "Dashboard", "after": ["API"], "brief": "The dashboard.", "criteria": ["Shows my tasks (prototype: dashboard)"]}]}
CRITERIA = [(False, "A task has a due day (one-pager §2)"),
            (False, 'An empty Inbox says "Nothing to do" (prototype: inbox)'),
            (False, "Shows my tasks (prototype: dashboard)"), (False, "The parts fit together")]


class TestParts(unittest.TestCase):
    def test_a_good_split_and_its_order(self):
        import json
        parts = goal.read_parts(json.dumps(PARTS))
        self.assertEqual(goal.parts_problems(parts, CRITERIA), [])
        self.assertEqual(goal.part_order(parts), ["API", "Inbox", "Dashboard"])

    def test_what_is_wrong_with_a_split(self):
        import json
        self.assertTrue(goal.parts_problems(goal.read_parts("not json"), CRITERIA))
        bad = json.loads(json.dumps(PARTS))
        bad["parts"][1]["criteria"].append("Something nobody listed")
        bad["parts"][2]["criteria"] = bad["parts"][0]["criteria"][:]
        bad["parts"][2]["after"] = ["Billing"]
        problems = " | ".join(goal.parts_problems(goal.read_parts(json.dumps(bad)), CRITERIA))
        self.assertIn("not in your list", problems)
        self.assertIn('is in both "API" and "Dashboard"', problems)
        self.assertIn('after "Billing", which is not a part', problems)
        loop = json.loads(json.dumps(PARTS))
        loop["parts"][0]["after"] = ["Inbox"]
        self.assertIn("circle", " ".join(goal.parts_problems(goal.read_parts(json.dumps(loop)), CRITERIA)))
        one = {"parts": PARTS["parts"][:1]}
        self.assertIn("two parts", " ".join(goal.parts_problems(goal.read_parts(json.dumps(one)), CRITERIA)))

    def test_a_part_s_ask(self):
        parent = {"key": "A-1", "ask": "# A-1: Tasks\nThe whole thing."}
        ask = goal.part_ask(parent, PARTS["parts"][1], [{"name": "API", "summary": "Tasks have an API."}])
        self.assertTrue(ask.startswith("# A-1 part: Inbox"))
        self.assertIn("The inbox screen.", ask)
        self.assertIn('- An empty Inbox says "Nothing to do" (prototype: inbox)', ask)
        self.assertIn("- API: Tasks have an API.", ask)
        self.assertIn("The whole thing.", ask)

    def test_only_a_goal_splits_and_a_part_does_not(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        gid = goal.create(d, "x", key="A-1", name="x", base="main")
        g = goal.Goal(d, gid)
        g.update(worktree=d, branch="A-1/goal-x", ask="# A-1")
        self.assertIn("Split only when", goal.Runner(d, gid).fields()["split"])
        self.assertIn(g.state.path("parts.json"), goal.Runner(d, gid).fields()["split"])
        pid = goal.create_part(d, g.read(), PARTS["parts"][0], 0, [])
        goal.Goal(d, pid).update(worktree=d, branch="A-1/goal-x--api")
        fields = goal.Runner(d, pid).fields()
        self.assertIn("Do not split it", fields["split"])
        self.assertIn("no CI runs for a part", fields["delivery"])
        self.assertIn("has run no CI", fields["checks"])
        self.assertEqual([x["id"] for x in goal.list_goals(d)], [gid, pid])


class TestSplitFlow(unittest.TestCase):
    def setUp(self):
        import json
        self.dir = tempfile.mkdtemp()
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        self.goal = goal.Goal(self.dir, gid)
        self.goal.update(worktree=self.dir, branch="A-1/goal-x", ask="# A-1", session="s",
                         session_used=True, flow=None)
        with open(self.goal.state.path("parts.json"), "w") as f:
            json.dump(PARTS, f)
        with open(self.goal.journal, "w") as f:
            f.write("## References\n- prototype\n\n## Acceptance criteria\n"
                    + "".join("- [ ] %s\n" % c for _, c in CRITERIA) + "\n## Plan\n- [ ] parts\n")
        self.launched = []
        launch, sleep = goal.launch, goal.time.sleep

        def fake_launch(root, gid):
            # Each part is done by the next look; the scheduler sees what ran together.
            self.launched.append([goal.Goal(root, p["id"]).read().get("part")
                                  for p in self.runner.data["parts"]
                                  if goal.Goal(root, p["id"]).read().get("status") == "working"]
                                 + [goal.Goal(root, gid).read()["part"]])
            goal.Goal(root, gid).update(status="working", pid=None)
        goal.launch = fake_launch
        goal.time.sleep = lambda _: [goal.Goal(self.dir, p["id"]).update(status="done", summary="did " + p["name"])
                                     for p in self.runner.data["parts"]
                                     if goal.Goal(self.dir, p["id"]).read().get("status") == "working"]
        self.addCleanup(setattr, goal, "launch", launch)
        self.addCleanup(setattr, goal.time, "sleep", sleep)
        self.runner = goal.Runner(self.dir, gid)
        self.runner.set_up = lambda: None
        self.runner.head = lambda: "same"
        self.runner.wait_for_usage = lambda: None

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_older_flow_builds_its_parts_in_order_then_integrates(self):
        prompts, events = [], []
        rounds = ["planned", "planned", "done"]

        def lead(prompt):
            prompts.append(prompt)
            return rounds.pop(0), {"summary": "s"}
        self.runner.lead = lead
        self.runner.review = lambda: events.append("review") or (["no due-day rule"], [])
        read = goal.Runner.read_journal.__get__(self.runner)
        self.runner.read_journal = lambda: read().replace("- [ ]", "- [x]") if not rounds else read()
        self.runner.sync = lambda: None
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.check = lambda: (True, [], [])
        self.runner.finish = lambda block: events.append("finish")
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(events, ["review", "finish"])
        self.assertIn("Correct the criteria, the plan and the parts first", prompts[1])
        self.assertEqual(self.launched, [["API"], ["Inbox"], ["Inbox", "Dashboard"]])
        self.assertIn("- Inbox: did Inbox", prompts[2])
        self.assertIn("Now integrate", prompts[2])
        inbox = goal.Goal(self.dir, goal.part_id(self.goal.id, "Inbox")).read()
        self.assertIn("- API: did API", inbox["ask"])
        self.assertEqual((inbox["depth"], inbox["base"]), (1, "A-1/goal-x"))


class TestPartBranches(unittest.TestCase):
    def git(self, *args, cwd=None):
        import subprocess
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                              cwd=cwd, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main", cwd=self.dir)
        with open(os.path.join(self.dir, "a.txt"), "w") as f:
            f.write("base\n")
        self.git("add", "a.txt", cwd=self.dir)
        self.git("commit", "-q", "-m", "base", cwd=self.dir)
        self.goal_tree = os.path.join(self.dir, "goal-tree")
        self.git("worktree", "add", "-q", self.goal_tree, "-b", "A-1/goal-x", cwd=self.dir)
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        self.parent = goal.Goal(self.dir, gid)
        self.parent.update(worktree=self.goal_tree, branch="A-1/goal-x", ask="# A-1")
        os.environ["GIT_AUTHOR_NAME"] = os.environ["GIT_COMMITTER_NAME"] = "t"
        os.environ["GIT_AUTHOR_EMAIL"] = os.environ["GIT_COMMITTER_EMAIL"] = "t@t"

    def tearDown(self):
        shutil.rmtree(self.dir)

    def part(self, index):
        pid = goal.create_part(self.dir, self.parent.read(), PARTS["parts"][index], index, [])
        runner = goal.Runner(self.dir, pid)
        runner.set_up()
        return runner

    def commit(self, runner, name, text):
        with open(os.path.join(runner.data["worktree"], name), "w") as f:
            f.write(text)
        self.git("add", name, cwd=runner.data["worktree"])
        self.git("commit", "-q", "-m", name, cwd=runner.data["worktree"])

    def test_parts_branch_off_the_goal_and_merge_back_one_at_a_time(self):
        api, inbox = self.part(0), self.part(1)
        self.assertEqual(api.data["branch"], "A-1/goal-x--api")
        self.commit(api, "api.txt", "api\n")
        self.commit(inbox, "inbox.txt", "inbox\n")
        self.assertIsNone(api.deliver())
        self.assertIsNone(inbox.deliver())
        self.assertEqual(sorted(os.listdir(self.goal_tree)), [".git", "a.txt", "api.txt", "inbox.txt"])

    def test_a_part_that_conflicts_with_one_merged_before_goes_back_to_its_lead(self):
        api, inbox = self.part(0), self.part(1)
        self.commit(api, "a.txt", "api\n")
        self.commit(inbox, "a.txt", "inbox\n")
        self.assertIsNone(api.deliver())
        fix = inbox.deliver()
        self.assertIn("conflicts in:\n\n- `a.txt`", fix)
        self.assertIn("`A-1/goal-x`", fix)


class TestWindDown(unittest.TestCase):
    def setUp(self):
        import subprocess
        self.dir = tempfile.mkdtemp()
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        goal.Goal(self.dir, gid).update(worktree=self.dir, branch="A-1/goal-x")
        self.runner = goal.Runner(self.dir, gid)
        self.runner.record_call = lambda *a, **k: None
        self.readings, self.killed = [], []
        self.runner.usage = lambda: [{"name": "session", "used": self.readings.pop(0), "resets_at": 0}]
        test = self

        class Proc(object):
            pid, returncode = 4242, 0

            def __init__(self, cmd, **kw):
                test.cmd = cmd
                self.waits = 0

            def communicate(self, timeout=None):
                if timeout is not None and test.readings:
                    test.timeouts.append(timeout)
                    raise subprocess.TimeoutExpired("claude", timeout)
                return b'{"result": "ok", "subtype": "success"}', b""

            def poll(self):
                return 0
        self.timeouts = []
        popen, killpg = goal.subprocess.Popen, goal.os.killpg
        goal.subprocess.Popen = Proc
        goal.os.killpg = lambda pid, sig: self.killed.append(pid)
        self.addCleanup(setattr, goal.subprocess, "Popen", popen)
        self.addCleanup(setattr, goal.os, "killpg", killpg)
        self.flag = self.runner.goal.state.path(goal.WIND_FILE)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_at_the_threshold_the_call_winds_down_and_ends_by_itself(self):
        self.readings = [60, 75, 76]
        _, stop, _ = self.runner.call("go", "s", False, "lead")
        self.assertNotEqual(stop, "usage")
        self.assertEqual(self.killed, [])
        self.assertTrue(os.path.exists(self.flag))
        self.assertEqual(self.timeouts, [goal.USAGE_CHECK, goal.USAGE_CHECK, goal.WIND_CHECK])
        self.assertIn("--settings", self.cmd)
        self.assertEqual(self.cmd[self.cmd.index("--permission-mode") + 1], "auto")
        allow = self.runner.goal.state.read(goal.SETTINGS_FILE)["permissions"]["allow"]
        self.assertIn("Write(/%s/**)" % os.path.abspath(self.runner.goal.state.dir), allow)
        self.assertIn("Agent", allow)

    def test_the_limit_on_the_setup_tab_reaches_a_running_goal(self):
        import json
        self.assertEqual(self.runner.threshold(), 75)
        path = os.path.join(self.dir, goal.st.CORTEX_DIRNAME, "queue", "control.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"usage_threshold": 90}, f)
        self.assertEqual(self.runner.threshold(), 90)
        self.readings = [80, 85]
        _, stop, _ = self.runner.call("go", "s", False, "lead")
        self.assertNotEqual(stop, "usage")
        self.assertEqual((self.killed, os.path.exists(self.flag)), ([], False))

    def test_past_the_margin_it_is_cut_off(self):
        self.readings = [75, 77]
        _, stop, _ = self.runner.call("go", "s", False, "lead")
        self.assertEqual((stop, self.killed), ("usage", [4242]))
        self.assertEqual(self.runner.cut_off["session"], "s")

    def test_a_new_call_starts_without_the_flag(self):
        with open(self.flag, "w") as f:
            f.write("old")
        self.runner.call("go", "s", False, "lead")
        self.assertFalse(os.path.exists(self.flag))

    def test_the_hooks_refuse_sub_agents_and_ask_for_a_stop(self):
        hooks = goal.hook_settings("/s/wind-down")["hooks"]
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Agent|Task")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "*")
        self.assertIn("test -f /s/wind-down", hooks["PreToolUse"][0]["hooks"][0]["command"])

    def test_the_hooks_guard_pushes_and_give_sub_agents_the_cheap_model(self):
        hooks = goal.hook_settings("/s/wind-down", "sonnet")["hooks"]["PreToolUse"]
        self.assertTrue(hooks[0]["hooks"][1]["command"].endswith("hook.py agent sonnet"))
        self.assertEqual(hooks[1]["matcher"], "Bash")
        self.assertTrue(hooks[1]["hooks"][0]["command"].endswith("hook.py bash"))

    def test_the_ci_fixer_briefs_sub_agents_on_the_cheap_model_and_cannot_edit_itself(self):
        import importlib.util, io, contextlib
        spec = importlib.util.spec_from_file_location("hook", goal.HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        pre = goal.hook_settings("/f", "sonnet", readonly="/wt", force_subagent=True)["hooks"]["PreToolUse"]
        self.assertTrue(pre[0]["hooks"][1]["command"].endswith("hook.py agent sonnet force"))
        self.assertTrue(any(h["hooks"][0]["command"].endswith("hook.py readonly /wt") for h in pre))

        def run(argv, call):
            sys.stdin, out = io.StringIO(json.dumps(call)), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = hook.main(argv)
            return code, out.getvalue()
        self.addCleanup(setattr, sys, "stdin", sys.__stdin__)
        _, out = run(["agent", "sonnet", "force"], {"tool_name": "Agent", "tool_input": {"model": "opus"}})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["updatedInput"]["model"], "sonnet")
        _, out = run(["agent", "sonnet"], {"tool_name": "Agent", "tool_input": {"model": "opus"}})
        self.assertEqual(out, "")
        edit = {"tool_name": "Edit", "tool_input": {"file_path": "/wt/apps/a.ts"}}
        self.assertEqual(run(["readonly", "/wt"], edit)[0], 2)
        self.assertEqual(run(["readonly", "/wt"], dict(edit, agent_type="general-purpose"))[0], 0)
        self.assertEqual(run(["readonly", "/wt"], {"tool_name": "Bash", "tool_input": {
            "command": "git commit -qm 'fix the types'"}})[0], 0)

    def test_an_explorer_runs_one_test_but_no_suite_and_does_not_sleep(self):
        import importlib.util, io, contextlib
        spec = importlib.util.spec_from_file_location("hook", goal.HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        pre = goal.hook_settings("/f", readonly="/wt", explore=True)["hooks"]["PreToolUse"]
        self.assertTrue(pre[-1]["hooks"][0]["command"].endswith("hook.py explore"))
        self.assertFalse(any(h["hooks"][0]["command"].endswith("hook.py explore")
                             for h in goal.hook_settings("/f", readonly="/wt")["hooks"]["PreToolUse"]))

        def run(command):
            sys.stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
            with contextlib.redirect_stderr(io.StringIO()):
                return hook.main(["explore"])
        self.addCleanup(setattr, sys, "stdin", sys.__stdin__)
        for command in ("cd apps/core && pytest test/integration/x_test.py > /tmp/o.txt 2>&1 & sleep 100",
                        "while ! grep -q passed /tmp/o.txt; do sleep 5; done",
                        "npm run test", "npx --no-install vitest run", "npx tsc --noEmit"):
            self.assertEqual(run(command), 2, command)
        for command in ("cd apps/core && uv run pytest test/unit/test_sync.py -x",
                        "npx --no-install vitest run src/a.test.ts", "grep -rn sleep src"):
            self.assertEqual(run(command), 0, command)

    def test_the_bash_hook_refuses_pushes_and_ci_but_not_other_git(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("hook", goal.HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        for command in ("git push", "git push -u origin x", "cd a && git -C b push --force",
                        "gh pr ready 5", "gh pr merge 5", "gh workflow run ci", "gh run rerun 9"):
            self.assertTrue(hook.blocked(command), command)
        self.assertTrue(hook.fenced({"file_path": "/u/Coding/SIROC/cortex/bin/tui/tui.py"},
                                    ["SIROC/cortex", "cortex"]))
        self.assertTrue(hook.fenced({"command": "cd x && cortex tui --status"}, ["cortex"]))
        self.assertTrue(hook.fenced({"command": "cd x && cond tui --status"}, ["cond"]))
        self.assertFalse(hook.fenced({"command": "cd x && cond tui --status"}, ["cortex"]))
        self.assertFalse(hook.fenced({"command": "cat bin/cond/README.md"}, ["cond"]))
        self.assertFalse(hook.fenced({"pattern": "def main"}, ["SIROC/cortex", "cortex"]))
        fence = goal.hook_settings("/f", "sonnet", ["SIROC/cortex"])["hooks"]["PreToolUse"][2]
        self.assertEqual(fence["matcher"], "*")
        self.assertTrue(fence["hooks"][0]["command"].endswith("hook.py fence SIROC/cortex"))
        for command in ("git status", "git stash push -m x", "git commit -m 'push it'",
                        "gh run view 9 --log-failed", "gh pr view 5", "npm run lint"):
            self.assertFalse(hook.blocked(command), command)

    def test_in_the_build_the_lead_delegates_the_code_and_its_sub_agents_write_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("hook", goal.HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        wt = "/repo/.cortex/worktrees/g"

        def lead(tool, **tool_input):
            return hook.delegated({"tool_name": tool, "tool_input": tool_input}, wt)
        self.assertTrue(lead("Edit", file_path=wt + "/apps/a.ts"))
        self.assertTrue(lead("Write", file_path=wt + "/apps/new.ts"))
        self.assertFalse(lead("Edit", file_path="/repo/.cortex/state/g/journal.md"))
        self.assertFalse(lead("Write", file_path="/repo/.cortex/worktrees/g2/a.ts"))
        for command in ("cat > apps/a.ts <<'X'", "echo x >> a.py", "sed -i '' s/a/b/ a.ts",
                        "perl -pi -e s/a/b/ a.ts", "printf x | tee a.ts", "git apply fix.patch"):
            self.assertTrue(lead("Bash", command=command), command)
        for command in ("git status", "git commit -m 'x > y'", "ls > /dev/null",
                        "git log --oneline > /tmp/log", "cmd 2>/dev/null", "git diff --stat | grep a",
                        "cat docs/plan.md"):
            self.assertFalse(lead("Bash", command=command), command)
        for command in ("npx vitest related --run a.ts", "cd apps/frontend && npx tsc --noEmit",
                        "export PATH=x:$PATH && npm run typecheck", "uv run pytest -q test", "make verify"):
            self.assertEqual(lead("Bash", command=command), hook.CHECKS, command)
        for command in ("rg -n 'a' apps", "cat apps/a.ts", "cd apps && grep -rn x .", "sed -n 1,80p a.py"):
            self.assertEqual(lead("Bash", command=command), hook.EXPLORE, command)
        for command in ("sed -n 1,400p /Users/j/.claude/projects/x/tool-results/b0.txt | tail -c 32000",
                        "cat /repo/.cortex/state/g/goal.log | tail -40"):
            self.assertIsNone(lead("Bash", command=command), command)
        self.assertEqual(lead("Bash", command="cat %s/apps/a.ts" % wt), hook.EXPLORE)
        self.assertEqual(lead("Bash", command="grep -rn x apps/web /tmp/y"), hook.EXPLORE)
        self.assertEqual(lead("Read", file_path=wt + "/apps/a.ts"), hook.EXPLORE)
        import io, contextlib
        def bash(command, *argv, **call):
            sys.stdin = io.StringIO(json.dumps(dict({"tool_name": "Bash", "tool_input": {"command": command}}, **call)))
            with contextlib.redirect_stderr(io.StringIO()):
                return hook.main(["bash"] + list(argv))
        self.addCleanup(setattr, sys, "stdin", sys.__stdin__)
        self.assertEqual(bash("for i in $(seq 1 9); do sleep 5; done", "lead"), 2)
        self.assertEqual(bash("sleep 30", "lead"), 2)
        self.assertEqual(bash("sleep 30", "lead", agent_type="general-purpose"), 0)
        self.assertEqual(bash("sleep 30"), 0)
        self.assertEqual(bash("git log --oneline", "lead"), 0)

        tmp = os.path.realpath(tempfile.gettempdir())

        def discuss(tool, **tool_input):
            sys.stdin = io.StringIO(json.dumps({"tool_name": tool, "tool_input": tool_input}))
            with contextlib.redirect_stderr(io.StringIO()):
                return hook.main(["discuss"])
        self.assertEqual(discuss("Write", file_path=tmp + "/conductor-discuss-g/a.py", content="x"), 0)
        self.assertEqual(discuss("Write", file_path="/tmp/a.md", content="x"), 0)
        self.assertEqual(discuss("Edit", file_path=wt + "/apps/a.ts"), 2)
        for command in ("python3 %s/conductor-discuss-g/a.py > %s/out.txt" % (tmp, tmp),
                        "mkdir -p /tmp/x", "git log --oneline", "rg -n x apps", "cat apps/a.ts | head"):
            self.assertEqual(discuss("Bash", command=command), 0, command)
        for command in ("echo x > apps/a.ts", "git commit -qm x", "git checkout -b y", "rm -rf apps",
                        "sed -i '' s/a/b/ apps/a.ts", "npm install", "cp /tmp/a.ts apps/a.ts"):
            self.assertEqual(discuss("Bash", command=command), 2, command)

        def task(command):
            sys.stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
            with contextlib.redirect_stderr(io.StringIO()):
                return hook.main(["task"])
        for command in ("npx tsc -b", "cd apps/frontend && npm run typecheck", "./scripts/setup-worktree.sh",
                        "npm ci --ignore-scripts", "make lint-imports", "npm run verify:static",
                        "npx vitest run", "uv sync"):
            self.assertEqual(task(command), 2, command)
        for command in ("npx --no-install vitest related --run src/a.ts", "npx eslint src/a.ts src/b.tsx",
                        "uv run pytest -q calls/test_a.py", "uv run ruff check apps/a.py", "git commit -m 'make it'",
                        "npx tsc --noEmit src/a.ts"):
            self.assertEqual(task(command), 0, command)
        self.assertEqual(lead("Grep", pattern="x", path=wt + "/apps"), hook.EXPLORE)
        self.assertFalse(lead("Read", file_path=wt + "/docs/decisions/a.md"))
        self.assertFalse(lead("Read", file_path="/repo/.cortex/state/g/journal.md"))
        self.assertFalse(hook.delegated({"tool_name": "Read", "agent_type": "Explore",
                                         "tool_input": {"file_path": wt + "/apps/a.ts"}}, wt))
        self.assertFalse(hook.delegated({"tool_name": "Edit", "agent_type": "general-purpose",
                                         "tool_input": {"file_path": wt + "/apps/a.ts"}}, wt))
        hooks = goal.hook_settings("/f", "sonnet", delegate=wt)["hooks"]["PreToolUse"]
        self.assertTrue(hooks[-1]["hooks"][0]["command"].endswith("hook.py delegate " + wt))
        self.assertNotIn("delegate", json.dumps(goal.hook_settings("/f", "sonnet")))

    def test_after_a_cut_off_the_lead_is_told_what_was_left(self):
        text = goal.cut_off_prompt(0, ["Task panel"], ["apps/a.ts", "apps/b.ts"])
        self.assertIn("- Task panel", text)
        self.assertIn("- `apps/a.ts`", text)
        self.assertIn("finish it, or redo it", text)


class TestEstimates(unittest.TestCase):
    tokens = {"input": 0, "output": 200, "cache_read": 0, "cache_write": 0}

    def call(self, cost, sub_cost, model="claude-opus-5-5"):
        return {"label": "lead", "round": 1, "model": model, "started": 0, "cost": cost,
                "main": {"model": model, "tokens": self.tokens, "seconds": 60, "cost": sub_cost},
                "subagents": [{"description": "part", "model": "claude-sonnet-5-5",
                               "tokens": self.tokens, "seconds": 30, "cost": sub_cost}]}

    def test_rates_are_learned_from_calls_that_reported_a_cost(self):
        rates = goal.learned_rates([self.call(2.0, 1.0), self.call(None, None)])
        self.assertAlmostEqual(rates["claude-opus-5-5"], 1.0 / 1000)
        self.assertAlmostEqual(rates["claude-sonnet-5-5"], 1.0 / 1000)

    def test_a_cut_off_call_is_priced_from_its_tokens_and_says_so(self):
        rates = {"claude-opus-5-5": 0.002, "claude-sonnet-5-5": 0.001}
        [priced] = goal.estimate([self.call(None, None)], rates)
        self.assertAlmostEqual(priced["main"]["cost"], 2.0)
        self.assertAlmostEqual(priced["subagents"][0]["cost"], 1.0)
        self.assertAlmostEqual(priced["cost"], 3.0)
        self.assertTrue(priced["estimated"])
        report = goal.usage_report([priced])
        self.assertIn("≈ $3.00 (some estimated)", report)
        self.assertIn("≈ $2.00 est.", report)

    def test_a_resumed_lead_call_s_running_total_is_not_its_cost(self):
        calls = [self.call(25.0, 1.0), self.call(30.0, 1.0), self.call(38.0, 1.0),
                 dict(self.call(None, None), label="check")]
        normal = goal.normalise(calls)
        self.assertEqual(normal[0]["cost"], 25.0)
        self.assertIsNone(normal[1]["cost"])
        self.assertIsNone(normal[2]["main"]["cost"])
        self.assertEqual(normal[2]["subagents"][0]["cost"], 1.0)
        v2 = dict(self.call(2.0, 1.0), v=2)
        self.assertEqual(goal.normalise([calls[0], v2])[1]["cost"], 2.0)

    def test_a_model_never_seen_stays_unknown(self):
        [priced] = goal.estimate([self.call(None, None, model="claude-haiku-4-5")], {})
        self.assertIsNone(priced["cost"])
        self.assertIn("cost unknown", goal.usage_report([priced]))


class NoAsana(object):
    """Asana, which a goal never writes to: every call is recorded."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, cwd=None):
        self.calls.append(args)
        return {}


def fake_asana(test, fake):
    asana = goal.st.asana
    goal.st.asana = fake
    test.addCleanup(setattr, goal.st, "asana", asana)
    return fake


PLANNED = JOURNAL.replace("## Plan\n1. [x] API\n2. [ ] Inbox", "## Plan\n1. [ ] API\n2. [ ] Inbox")


class TestPlanFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.fake = fake_asana(self, NoAsana())
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        goal.Goal(self.dir, gid).update(worktree=self.dir, branch="A-1/goal-x", ask="# A-1: x",
                                        session="s", session_used=True)
        self.runner = goal.Runner(self.dir, gid)
        self.runner.set_up = lambda: None
        self.runner.head = lambda: "same"
        self.runner.sync = lambda: None
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.check = lambda: (True, [], [])
        self.runner.finish = lambda block: self.events.append("finish")
        self.events, self.prompts = [], []

    def journal(self, text):
        with open(self.runner.goal.journal, "w") as f:
            f.write(text)
        with open(self.runner.technical_plan(), "w") as f:
            f.write("# Technical plan\n")

    def run_with(self, rounds, answer):
        def lead(prompt):
            self.prompts.append(prompt)
            report, write, block = (rounds.pop(0) + ({"summary": "s"},))[:3]
            write()
            self.events.append("lead %s" % report)
            return report, block
        self.runner.lead = lead
        self.runner.review = lambda: self.events.append("review") or ([], [])

        def wait(record):
            self.events.append("waits for %s" % record["kind"])
            return answer(record)
        self.runner.wait_for_answer = wait
        self.assertEqual(self.runner.run(), 0)

    def test_nothing_is_built_until_the_person_approves_the_plan(self):
        done = PLANNED.replace("- [ ]", "- [x]").replace(". [ ]", ". [x]")
        self.run_with([("planned", lambda: self.journal(PLANNED)),
                       ("done", lambda: self.journal(done))], lambda record: "continue")
        self.assertEqual(self.events, ["lead planned", "review", "waits for plan", "lead done", "finish"])
        self.assertIn("The plan is approved", self.prompts[1])
        self.assertEqual(self.fake.calls, [])

    def test_small_work_skips_the_review_the_approval_and_the_technical_plan(self):
        def no_plan():
            self.journal(PLANNED)
            os.remove(self.runner.technical_plan())
        done = PLANNED.replace("- [ ]", "- [x]")
        self.run_with([("planned", no_plan, {"summary": "s", "small": " One button. "}),
                       ("done", lambda: self.journal(done))], lambda record: self.fail("waited"))
        self.assertEqual(self.events, ["lead planned", "lead done", "finish"])
        self.assertIn("The plan is approved", self.prompts[1])
        self.assertEqual(self.runner.data["small"], "One button.")

    def test_only_the_last_planned_report_decides_small(self):
        def no_plan_section():
            self.journal(PLANNED.replace("## Plan", "## Later"))
        done = PLANNED.replace("- [ ]", "- [x]")
        self.run_with([("planned", no_plan_section, {"summary": "s", "small": "One button."}),
                       ("planned", lambda: self.journal(PLANNED)),
                       ("done", lambda: self.journal(done))], lambda record: "continue")
        self.assertEqual(self.events, ["lead planned", "lead planned", "review", "waits for plan",
                                       "lead done", "finish"])
        self.assertIsNone(self.runner.data.get("small"))

    def test_small_is_only_taken_from_a_whole_goal_that_does_not_split(self):
        self.assertEqual(goal.small_reason({"small": " One button. "}, False, False), "One button.")
        self.assertIsNone(goal.small_reason({"small": "One button."}, True, False))
        self.assertIsNone(goal.small_reason({"small": "One button."}, False, True))
        self.assertIsNone(goal.small_reason({"small": "  "}, False, False))
        self.assertIsNone(goal.small_reason({"small": True}, False, False))
        self.assertIsNone(goal.small_reason({}, False, False))

    def test_the_build_starts_in_a_new_session(self):
        done = PLANNED.replace("- [ ]", "- [x]").replace(". [ ]", ". [x]")
        self.run_with([("planned", lambda: self.journal(PLANNED)),
                       ("done", lambda: self.journal(done))], lambda record: "continue")
        self.assertIn(goal.FRESH, self.prompts[1])
        self.assertIn("The plan is approved", self.prompts[1])
        self.assertNotIn(goal.FRESH, self.prompts[0])

    def test_a_goal_resumed_while_building_starts_a_new_session(self):
        self.runner.set(phase="building", approved=True, session_used=True)
        done = PLANNED.replace("- [ ]", "- [x]").replace(". [ ]", ". [x]")
        self.journal(PLANNED)
        self.run_with([("done", lambda: self.journal(done))], lambda record: "continue")
        self.assertIn(goal.FRESH, self.prompts[0])
        self.assertIsNone(self.runner.data.get("session"))

    def test_a_build_stopped_in_the_middle_of_a_call_starts_a_new_session(self):
        self.runner.set(phase="building", approved=True, session="stopped-call", session_used=False)
        done = PLANNED.replace("- [ ]", "- [x]").replace(". [ ]", ". [x]")
        self.journal(PLANNED)
        self.run_with([("done", lambda: self.journal(done))], lambda record: "continue")
        self.assertIn(goal.FRESH, self.prompts[0])

    def test_the_checker_s_effort_and_model_follow_the_setup_tab(self):
        self.runner.set(check_effort="xhigh", check_model="claude-fable-5-1")
        self.assertEqual(self.runner.check_effort(), goal.DEFAULT_CHECK_EFFORT)
        self.assertEqual(self.runner.check_model(), "claude-fable-5-1")
        os.makedirs(os.path.join(self.dir, ".cortex", "queue"), exist_ok=True)
        with open(os.path.join(self.dir, ".cortex", "queue", "control.json"), "w") as f:
            json.dump({"models": {"check_effort": "medium", "check": "claude-opus-5-5"}}, f)
        self.assertEqual(self.runner.check_effort(), "medium")
        self.assertEqual(self.runner.check_model(), "claude-opus-5-5")

    def test_the_lead_is_sent_back_for_a_missing_technical_plan(self):
        def no_plan():
            self.journal(PLANNED)
            os.remove(self.runner.technical_plan())
        done = PLANNED.replace("- [ ]", "- [x]").replace(". [ ]", ". [x]")
        self.run_with([("planned", no_plan), ("planned", lambda: self.journal(PLANNED)),
                       ("done", lambda: self.journal(done))], lambda record: "continue")
        self.assertIn("technical plan", self.prompts[1])

    def test_changes_to_the_plan_go_back_to_the_lead_and_to_the_person_again(self):
        answers, records = ["Support neo too.", "continue"], []

        def answer(record):
            records.append(record)
            return answers.pop(0)
        done = PLANNED.replace("- [ ]", "- [x]")
        self.run_with([("planned", lambda: self.journal(PLANNED)),
                       ("planned", lambda: None, {"summary": "Added neo."}),
                       ("done", lambda: self.journal(done))], answer)
        self.assertEqual(self.events, ["lead planned", "review", "waits for plan", "lead planned",
                                       "waits for plan", "lead done", "finish"])
        self.assertIn("Support neo too.", self.prompts[1])
        self.assertIn("Do not build yet", self.prompts[1])
        self.assertIn("The plan is approved", self.prompts[2])
        self.assertEqual(records[0]["detail"], "- API\n- Inbox")
        self.assertEqual(records[1]["detail"], "What changed: Added neo.\n\n- API\n- Inbox")

    def test_with_the_reviewer_approving_the_goal_does_not_wait(self):
        self.runner.set(gate="auto")
        done = PLANNED.replace("- [ ]", "- [x]")
        self.run_with([("planned", lambda: self.journal(PLANNED)),
                       ("done", lambda: self.journal(done))], lambda record: self.fail("waited"))
        self.assertEqual(self.events, ["lead planned", "review", "lead done", "finish"])

    def test_questions_wait_for_the_person_s_answer(self):
        self.runner.wait_for_answer = goal.Runner.wait_for_answer.__get__(self.runner)
        sleep = goal.time.sleep
        self.addCleanup(setattr, goal.time, "sleep", sleep)

        def answer(_):
            asked = self.runner.goal.state.read("awaiting.json")
            self.runner.goal.state.write(goal.st.ANSWER_FILE, {"text": "Blue.", "asked_at": asked["asked_at"]})
        goal.time.sleep = answer
        text = self.runner.ask_person([{"q": "Which colour?", "why": "They disagree."}])
        self.assertEqual(text, "Blue.")
        self.assertIsNone(self.runner.goal.state.read("awaiting.json"))
        self.assertIn("Do not read or change Asana", self.runner.first_prompt())
        self.assertIn("approves\n   the plan there", self.runner.first_prompt())
        self.assertEqual(self.fake.calls, [])


class TestPartsPlanEarly(unittest.TestCase):
    def setUp(self):
        import json
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.fake = fake_asana(self, NoAsana())
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        self.goal = goal.Goal(self.dir, gid)
        self.goal.update(worktree=self.dir, branch="A-1/goal-x", ask="# A-1", session="s",
                         session_used=True)
        parts = json.loads(json.dumps(PARTS))
        parts["parts"][2]["plan_after"] = ["Inbox"]
        with open(self.goal.state.path("parts.json"), "w") as f:
            json.dump(parts, f)
        with open(self.goal.journal, "w") as f:
            f.write("## References\n- prototype\n\n## Acceptance criteria\n"
                    + "".join("- [ ] %s\n" % c for _, c in CRITERIA) + "\n## Plan\n- [ ] parts\n")
        self.launched = []
        launch, sleep = goal.launch, goal.time.sleep

        def fake_launch(root, pid):
            self.launched.append([goal.Goal(root, pid).read()["part"]])
            goal.Goal(root, pid).update(status="working", pid=None)
        goal.launch = fake_launch
        # Between two looks, every part that was started is done.
        goal.time.sleep = lambda _: self.launched.append("look") or [
            goal.Goal(self.dir, p["id"]).update(status="done", summary="did " + p["name"])
            for p in self.runner.data["parts"]
            if goal.Goal(self.dir, p["id"]).read().get("status") == "working"]
        self.addCleanup(setattr, goal, "launch", launch)
        self.addCleanup(setattr, goal.time, "sleep", sleep)
        self.runner = goal.Runner(self.dir, gid)
        self.runner.set_up = lambda: None
        self.runner.head = lambda: "same"
        self.runner.wait_for_usage = lambda: None
        self.runner.wait_for_answer = lambda record: "continue"

    def test_parts_plan_at_once_unless_they_plan_after_another(self):
        with open(self.runner.technical_plan(), "w") as f:
            f.write("# Technical plan\n")
        rounds, calls = ["planned", "done"], []
        self.runner.data.update(session="planning", session_used=True)
        self.runner.lead = lambda prompt: (calls.append((prompt, self.runner.data.get("session"))),
                                           rounds.pop(0), {"summary": "s"})[1:]
        self.runner.review = lambda: ([], [])
        read = goal.Runner.read_journal.__get__(self.runner)
        self.runner.read_journal = lambda: read().replace("- [ ]", "- [x]") if not rounds else read()
        self.runner.sync = lambda: None
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.check = lambda: (True, [], [])
        self.runner.finish = lambda block: None
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(self.launched[:3], [["API"], ["Inbox"], "look"])
        integration, session = calls[1]
        self.assertIsNone(session)
        self.assertIn("in a new session", integration)
        self.assertIn(goal.Goal(self.dir, goal.part_id(self.goal.id, "Inbox")).journal, integration)
        self.assertIn("## The ask", integration)
        self.assertEqual(self.launched[3], ["Dashboard"])
        self.assertEqual(self.fake.calls, [])

    def test_an_approved_part_builds_after_its_parts_and_in_a_free_slot(self):
        import json
        with open(self.goal.state.path("parts.json")) as f:
            parts = goal.read_parts(f.read())
        parts = [dict(p, id=goal.part_id(self.goal.id, p["name"])) for p in parts]
        self.goal.update(parts=parts)
        ids = [goal.create_part(self.dir, self.goal.read(), p, i, []) for i, p in enumerate(parts)]
        inbox = goal.Runner(self.dir, ids[1])
        looks = []

        def look(_):
            looks.append(inbox.data["doing"])
            goal.Goal(self.dir, ids[0]).update(status="done", summary="did API")
        goal.time.sleep = look
        built = inbox.wait_to_build()
        self.assertEqual(looks, ["plan approved — builds after API"])
        self.assertEqual(built, [{"name": "API", "summary": "did API"}])
        self.assertEqual(inbox.data["phase"], "building")
        json.dumps(built)


class TestDiscuss(unittest.TestCase):
    def test_a_read_only_session_with_the_goal_and_its_parts(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        gid = goal.create(d, "x", key="A-1", name="x", base="main")
        g = goal.Goal(d, gid)
        tree = os.path.join(d, "tree")
        os.makedirs(tree)
        g.update(worktree=tree, branch="A-1/goal-x")
        with open(g.state.path("journal.md"), "w") as f:
            f.write("# x")
        pid = goal.create_part(d, g.read(), dict(PARTS["parts"][0], subtask=None), 0, [])
        part = goal.Goal(d, pid)
        with open(part.state.path("journal.md"), "w") as f:
            f.write("# the part's own")
        argv, cwd = goal.discuss_command(d, gid)
        self.assertEqual(cwd, tree)
        self.assertEqual(argv[:3], ["claude", "--permission-mode", "acceptEdits"])
        self.assertIn("hook.py discuss", argv[argv.index("--settings") + 1])
        self.assertIn(g.state.dir, argv)
        self.assertIn(goal.Goal(d, pid).state.dir, argv)
        for tool in ("AskUserQuestion", "mcp__claude_ai_Asana__update_tasks"):
            self.assertIn(tool, argv[argv.index("--disallowedTools"):])
        for tool in ("Edit", "Write"):
            self.assertNotIn(tool, argv[argv.index("--disallowedTools"):])
        prompt = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn("# x", prompt)
        self.assertIn(g.state.path("journal.md"), prompt)
        self.assertIn(part.state.path("journal.md"), prompt)
        self.assertNotIn("# the part's own", prompt)
        self.assertLess(argv.index(goal.DISCUSS_OPEN), argv.index("--disallowedTools"))
        self.assertNotIn("--", argv[argv.index("--disallowedTools"):])


class TestOneRunner(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d)
        self.gid = goal.create(self.d, "x", key="A-1", name="x", base="main")
        self.addCleanup(goal._RUN_LOCK.clear)

    def test_a_goal_has_one_runner_and_launch_leaves_it_be(self):
        g = goal.Goal(self.d, self.gid)
        self.assertFalse(g.runner_alive())
        self.assertTrue(g.hold())
        self.assertTrue(goal.Goal(self.d, self.gid).runner_alive())
        self.assertFalse(goal.Goal(self.d, self.gid).hold())
        g.update(pid=4242)
        with mock.patch.object(goal.subprocess, "Popen", side_effect=AssertionError("launched")):
            self.assertEqual(goal.launch(self.d, self.gid), 4242)
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch.object(goal.st, "main_repo_root", lambda _: self.d):
            self.assertEqual(goal.main(["run", self.gid, "--repo", self.d]), 0)
        self.assertIn("already running", out.getvalue())

    def test_an_update_keeps_the_fields_and_a_write_is_whole(self):
        g = goal.Goal(self.d, self.gid)
        g.update(round=3)
        self.assertEqual(g.read()["round"], 3)
        self.assertEqual(g.read()["key"], "A-1")
        self.assertEqual([n for n in os.listdir(g.state.dir) if n.endswith(".tmp")], [])

    def test_a_goal_without_its_id_does_not_break_the_list(self):
        g = goal.Goal(self.d, self.gid)
        g.state.write(goal.GOAL_FILE, {"pid": None, "session": "s"})
        self.assertEqual([x["id"] for x in goal.list_goals(self.d)], [self.gid])


class TestWatchPR(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d)
        gid = goal.create(self.d, "x", key="A-1", name="x", base="main")
        goal.Goal(self.d, gid).update(pr_url="https://github.com/o/r/pull/5", status="done",
                                      phase="building", finished=1000.0, doing="all built")
        self.runner = goal.Runner(self.d, gid)
        self.runner.fresh = lambda prompt: prompt
        self.state, self.calls = "OPEN", []
        self.comments = [
            {"id": 1, "body": "old, before the finish", "created_at": "1970-01-01T00:00:01Z", "user": {"login": "j"}},
            {"id": 2, "body": goal.st.mark("the runner's own"), "created_at": "2026-11-09T10:00:00Z",
             "user": {"login": "j"}},
            {"id": 3, "body": "Rename the button.", "created_at": "2026-11-09T10:00:00Z", "user": {"login": "j"}}]

        def fake(cmd, cwd=None, check=True):
            self.calls.append(cmd)
            if cmd[:3] == ["gh", "pr", "view"]:
                return 0, json.dumps({"state": self.state}), ""
            if cmd[:2] == ["gh", "api"]:
                rows = self.comments if "/issues/" in cmd[3] else []
                return 0, "\n".join(json.dumps(r) for r in rows), ""
            return 0, "", ""
        run, sleep = goal.st.run, goal.time.sleep
        goal.st.run, goal.time.sleep = fake, lambda _: None
        self.addCleanup(setattr, goal.st, "run", run)
        self.addCleanup(setattr, goal.time, "sleep", sleep)

    def test_a_finished_goal_watches_its_pr_until_the_merge(self):
        self.assertTrue(self.runner.watching())
        prompt = self.runner.watch_pr()
        self.assertIn("Rename the button.", prompt)
        self.assertNotIn("old, before the finish", prompt)
        self.assertNotIn("the runner's own", prompt)
        self.assertEqual(self.runner.data["status"], "working")
        self.assertTrue(self.runner.data["revising_pr"])
        self.state = "MERGED"
        self.assertIsNone(self.runner.watch_pr())
        self.assertEqual((self.runner.data["status"], self.runner.data["phase"]), ("done", "merged"))
        self.assertFalse(self.runner.watching())
        self.assertEqual([c for c in self.calls if c[0] == sys.executable], [])

    def test_a_pr_github_refuses_shows_as_an_error_and_clears_once_read(self):
        fake = goal.st.run
        failing = [True]

        def refusing(cmd, cwd=None, check=True):
            if failing[0] and cmd[:2] == ["gh", "api"]:
                return 1, "", "HTTP 401: Bad credentials (https://api.github.com/graphql)"
            return fake(cmd, cwd, check)
        goal.st.run = refusing
        self.assertEqual(self.runner.pr_feedback("o", "r", "5"), [])
        self.assertIn("Bad credentials", self.runner.data["pr_error"])
        failing[0] = False
        self.assertTrue(self.runner.pr_feedback("o", "r", "5"))
        self.assertIsNone(self.runner.data["pr_error"])

    def test_a_done_goal_started_again_only_watches_its_pr(self):
        tree = os.path.join(self.d, "tree")
        os.makedirs(tree)
        self.runner.set(worktree=tree, ask="x", phase="parts")
        self.runner.lead = lambda prompt: self.fail("the lead was called")
        self.runner.run_parts = lambda: self.fail("the parts ran again")
        self.state = "MERGED"
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(self.runner.data["phase"], "merged")

    def test_the_walkthrough_is_posted_once(self):
        self.runner.set(worktree=self.d, url="https://app.asana.com/0/1/77")
        self.runner.push = lambda: None
        self.runner.progress = lambda: None
        posted = lambda: [c[-1] for c in self.calls if c[:3] == ["gh", "pr", "comment"]]
        block = {"summary": "built", "walkthrough": "## Why\nthe walk"}
        self.runner.finish(block)
        self.runner.finish(block)
        self.assertEqual(len(posted()), 1)
        self.assertIn("the walk", posted()[0])
        self.runner.set(revising_pr=True)
        self.runner.finish({"summary": "renamed it", "walkthrough": "## Comments\n- Rename: renamed it"})
        self.assertIn(goal.ADDRESSED, posted()[1])
        self.assertIn("## Comments\n- Rename: renamed it", posted()[1])
        self.assertEqual(len(posted()), 2)

    def test_a_walkthrough_already_on_the_pr_is_not_posted_again(self):
        self.runner.set(worktree=self.d, url="https://app.asana.com/0/1/77")
        self.runner.push = lambda: None
        self.runner.progress = lambda: None
        run = goal.st.run

        def with_walkthrough(cmd, cwd=None, check=True):
            if cmd[:3] == ["gh", "pr", "view"] and "comments" in cmd:
                self.calls.append(cmd)
                bodies = [goal.st.mark("%s\n\nearlier" % goal.ADDRESSED), goal.st.mark("## Why\nold walk")]
                return 0, json.dumps({"comments": [{"body": b} for b in bodies]}), ""
            return run(cmd, cwd, check)
        goal.st.run = with_walkthrough
        self.runner.finish({"summary": "built", "walkthrough": "## Why\nthe walk"})
        self.assertFalse([c for c in self.calls if c[:3] == ["gh", "pr", "comment"]])
        self.assertIn(["gh", "pr", "ready", "https://github.com/o/r/pull/5"], self.calls)


class TestPickGoal(unittest.TestCase):
    def test_a_goal_is_picked_by_number_or_key_and_the_only_one_without_asking(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        said = []
        self.assertIsNone(goal.pick_goal(d, say=said.append))
        first = goal.create(d, "inbox", key="A-1", name="inbox", base="main")
        self.assertEqual(goal.pick_goal(d, ask=lambda _: self.fail("asked"), say=said.append), first)
        second = goal.create(d, "api", key="A-2", name="api", base="main")
        self.assertIn(goal.pick_goal(d, ask=lambda _: "1", say=said.append), (first, second))
        self.assertEqual(goal.pick_goal(d, ask=lambda _: "A-2", say=said.append), second)
        self.assertIsNone(goal.pick_goal(d, ask=lambda _: "9", say=said.append))
        goal.Goal(d, first).update(status="done")
        self.assertEqual(goal.pick_goal(d, ask=lambda _: self.fail("asked"), say=said.append), second)
        self.assertTrue(any("api" in line for line in said))


class TestUndo(unittest.TestCase):
    def git(self, *args, cwd=None):
        import subprocess
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                              cwd=cwd, check=True, capture_output=True, text=True).stdout

    def test_undo_takes_everything_back_out(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        self.git("init", "-q", "-b", "main", cwd=d)
        self.git("commit", "-q", "--allow-empty", "-m", "base", cwd=d)
        gid = goal.create(d, "x", key="A-1", name="x", base="main")
        g = goal.Goal(d, gid)
        tree = os.path.join(d, "tree")
        self.git("worktree", "add", "-q", tree, "-b", "A-1/goal-x", cwd=d)
        g.update(worktree=tree, branch="A-1/goal-x", pr_url="https://github.com/o/r/pull/9")
        pid = goal.create_part(d, g.read(), PARTS["parts"][0], 0, [])
        self.assertEqual(goal.undo_plan(d, gid), ["close its PR and delete its branch, on GitHub and here",
                                                  "delete its part's branch",
                                                  "remove its worktrees and saved state"])
        run = goal.st.run
        calls = []
        goal.st.run = lambda cmd, **kw: (calls.append((cmd[:3], os.path.exists(tree))) or (0, "", "")) if (
            cmd[0] == "gh" or "push" in cmd) else run(cmd, **kw)
        self.addCleanup(setattr, goal.st, "run", run)
        done = goal.undo(d, gid)
        self.assertIn("worktrees and branches removed here", done)
        self.assertFalse(os.path.exists(g.state.dir) or os.path.exists(goal.Goal(d, pid).state.dir))
        self.assertFalse(os.path.exists(tree))
        self.assertNotIn("A-1/goal-x", self.git("branch", cwd=d))
        self.assertEqual(goal.list_goals(d), [])
        # The worktree is gone before the PR closes, so its branch can go too.
        self.assertEqual(calls, [(["gh", "pr", "close"], False), (["git", "push", "origin"], False)])
        self.assertIn("PR closed", done)


BIG = ("## Status\nBuilding step 2.\n\n## Answers from the person\n- Q1: blue.\n\n"
       "## Acceptance criteria\n### UI\n- [x] The badge is blue — a.ts\n- [ ] Zero hides it\n\n"
       "## Plan\n1. [x] Badge: blue (after: none)\n2. [ ] Zero (after: 1)\n\n"
       "## Build log\n" + "- batch notes that nobody needs again\n" * 2000)
SMALL = BIG[:BIG.index("## Build log")] + "## Decisions\n- D1: blue, from Q1.\n"


class TestCompactJournal(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        gid = goal.create(self.dir, "x", key="A-1", name="x", base="main")
        goal.Goal(self.dir, gid).update(worktree=self.dir, phase="building", round=7)
        self.runner = goal.Runner(self.dir, gid)
        self.runner.wait_for_usage = lambda: None
        with open(self.runner.goal.journal, "w") as f:
            f.write(BIG)
        self.calls = []

    def rewrite(self, text):
        def call(prompt, session, resume, label, model=None, effort=None):
            self.calls.append((label, model))
            with open(self.runner.goal.state.path("journal.compact.md"), "w") as f:
                f.write(text)
            return {"status": "done"}, "complete", None
        self.runner.call = call

    def test_what_it_must_keep_is_checked(self):
        self.assertIsNone(goal.journal_lost(BIG, SMALL))
        self.assertIn("acceptance criteria", goal.journal_lost(BIG, SMALL.replace("[x] The badge", "[ ] The badge")))
        self.assertIn("plan", goal.journal_lost(BIG, SMALL.replace("2. [ ] Zero (after: 1)\n", "")))
        self.assertIn("Answers from the person", goal.journal_lost(BIG, SMALL.replace("Q1: blue", "Q1: red")))
        self.assertEqual(goal.journal_lost(BIG, ""), "it is empty")
        self.assertEqual(goal.journal_lost(SMALL, SMALL), "it is not smaller")

    def test_a_large_journal_is_compacted_by_the_sub_agent_model_and_archived(self):
        self.rewrite(SMALL)
        archived = self.runner.compact_journal()
        self.assertEqual(self.calls, [("compact", goal.DEFAULT_SUBAGENT_MODEL)])
        with open(self.runner.goal.journal) as f:
            self.assertEqual(f.read(), SMALL)
        with open(archived) as f:
            self.assertEqual(f.read(), BIG)
        self.assertTrue(archived.endswith("journal-archive/round-7.md"))

    def test_a_new_session_after_a_compaction_hears_where_the_old_journal_is(self):
        self.runner.set(branch="A-1/goal-x", base="main", ask="# The ask")
        self.rewrite(SMALL)
        prompt = self.runner.fresh("Go on.")
        self.assertIn("compacted your journal", prompt)
        self.assertIn("journal-archive/round-7.md", prompt)
        self.assertNotIn("compacted your journal", self.runner.fresh("Go on."))
        self.assertEqual(len(self.calls), 1)

    def test_a_rewrite_that_loses_a_tick_is_dropped_and_not_retried_until_it_grows(self):
        self.rewrite(SMALL.replace("[x] The badge", "[ ] The badge"))
        self.assertIsNone(self.runner.compact_journal())
        with open(self.runner.goal.journal) as f:
            self.assertEqual(f.read(), BIG)
        self.assertIsNone(self.runner.compact_journal())
        self.assertEqual(len(self.calls), 1)

    def test_a_small_journal_is_left_alone(self):
        with open(self.runner.goal.journal, "w") as f:
            f.write(SMALL)
        self.rewrite("x")
        self.assertIsNone(self.runner.compact_journal())
        self.assertEqual(self.calls, [])


class TestTestsLine(unittest.TestCase):
    def test_passed_tests_give_the_command_and_the_count(self):
        self.assertEqual(goal.tests_line({"command": "npx vitest related --run a.ts", "result": "passed",
                                          "count": 14, "failed": []}),
                         "`npx vitest related --run a.ts` passed (14)")

    def test_failed_tests_name_at_most_five(self):
        failed = ["t%d" % n for n in range(7)]
        self.assertEqual(goal.tests_line({"command": "uv run pytest x.py", "result": "failed",
                                          "count": 9, "failed": failed}),
                         "`uv run pytest x.py` failed: t0, t1, t2, t3, t4 and 2 more")

    def test_no_tests_say_why(self):
        self.assertEqual(goal.tests_line({"result": "none", "why": "No test covers the copy."}),
                         "none run: No test covers the copy.")

    def test_a_report_without_tests_adds_no_line(self):
        self.assertIsNone(goal.tests_line(None))
        self.assertIsNone(goal.tests_line("passed"))

    def test_the_lead_gets_one_tests_line_per_coding_task(self):
        prompt = goal.dispatched_prompt([
            {"name": "One", "kind": "code", "status": "done", "summary": "Did it.",
             "tests": {"command": "uv run pytest x.py", "result": "failed", "failed": ["test_a"]}},
            {"name": "Two", "kind": "explore", "status": "done", "answer": "Here."}])
        self.assertIn("- Tests: `uv run pytest x.py` failed: test_a", prompt)
        self.assertEqual(prompt.count("- Tests:"), 1)


if __name__ == "__main__":
    unittest.main()
