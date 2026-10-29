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

    def test_a_bare_ticket_is_just_its_name(self):
        self.assertEqual(goal.ask_from_ticket({"ref": "1", "name": "Queue"}, "u"), "# 1: Queue\nu\n")

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
        gid = goal.create(self.dir, "1", "A-1", "x", base="main")
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

    def test_a_pr_with_no_checks_at_all_counts_as_having_no_ci(self):
        start, goal.CI_START = goal.CI_START, 0
        self.addCleanup(setattr, goal, "CI_START", start)
        self.assertEqual(self.runner.gate(), (None, None))
        self.assertEqual(self.runner.data["checks"], [])
        self.assertIn("The PR has no CI checks", goal.checks_text("main", []))

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

    def test_failing_ci_goes_to_a_cheap_fixer_first(self):
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
        self.assertEqual((label, model), ("ci-fix", "claude-sonnet-5-5"))
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
        self.assertIn("CI passed on it: `test`", goal.checks_text("main", ["test"]))

class TestFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        gid = goal.create(self.dir, "1", "A-1", "x", base="main")
        goal.Goal(self.dir, gid).update(worktree=self.dir, branch="A-1/goal-x", ask="# A-1: x",
                                        session="s", session_used=True)
        self.runner = goal.Runner(self.dir, gid)
        self.runner.set_up = lambda: None
        self.runner.head = lambda: "same"
        self.events = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def journal(self, text):
        with open(self.runner.goal.journal, "w") as f:
            f.write(text)

    def test_analysis_then_review_then_build_then_one_push_and_a_check(self):
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
        self.runner.sync_and_ci = lambda: self.events.append("push and CI") or (None, None)
        self.runner.check = lambda: self.events.append("check") or (True, [], [])
        self.runner.finish = lambda block: self.events.append("finish")
        self.runner.push = lambda: self.fail("nothing is pushed outside the gate")
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(self.events, ["lead planned (planning)", "lead planned (planning)", "review",
                                       "lead done (building)", "lead done (building)",
                                       "push and CI", "check", "finish"])
        self.assertIn("References", prompts[1])
        self.assertIn("- no error state", prompts[2])
        self.assertIn("not ticked", prompts[3])


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
        gid = goal.create(d, "1", "A-1", "x", base="main")
        g = goal.Goal(d, gid)
        g.update(worktree=d, branch="A-1/goal-x", ask="# A-1")
        self.assertIn("split it into parts", goal.Runner(d, gid).fields()["split"])
        self.assertIn(g.state.path("parts.json"), goal.Runner(d, gid).fields()["split"])
        pid = goal.create_part(d, g.read(), PARTS["parts"][0], 0, [])
        goal.Goal(d, pid).update(worktree=d, branch="A-1/goal-x--api")
        fields = goal.Runner(d, pid).fields()
        self.assertIn("Do not split it", fields["split"])
        self.assertIn("no CI runs for a part", fields["delivery"])
        self.assertIn("has run no CI", fields["checks"])
        self.assertEqual([x["id"] for x in goal.list_goals(d)], [gid, pid])
        self.assertEqual(goal.find_goal(d, "1")["id"], gid)


class TestSplitFlow(unittest.TestCase):
    def setUp(self):
        import json
        self.dir = tempfile.mkdtemp()
        gid = goal.create(self.dir, "1", "A-1", "x", base="main")
        self.goal = goal.Goal(self.dir, gid)
        self.goal.update(worktree=self.dir, branch="A-1/goal-x", ask="# A-1", session="s",
                         session_used=True)
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

    def test_the_goal_builds_its_parts_in_order_then_integrates(self):
        prompts, events = [], []
        rounds = ["planned", "planned", "done"]

        def lead(prompt):
            prompts.append(prompt)
            return rounds.pop(0), {"summary": "s"}
        self.runner.lead = lead
        self.runner.review = lambda: events.append("review") or (["no due-day rule"], [])
        read = goal.Runner.read_journal.__get__(self.runner)
        self.runner.read_journal = lambda: read().replace("- [ ]", "- [x]") if not rounds else read()
        self.runner.sync_and_ci = lambda: (None, None)
        self.runner.check = lambda: (True, [], [])
        self.runner.finish = lambda block: events.append("finish")
        self.assertEqual(self.runner.run(), 0)
        self.assertEqual(events, ["review", "finish"])
        self.assertIn("Correct the criteria and the parts first", prompts[1])
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
        gid = goal.create(self.dir, "1", "A-1", "x", base="main")
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
        gid = goal.create(self.dir, "1", "A-1", "x", base="main")
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

    def test_the_bash_hook_refuses_pushes_and_ci_but_not_other_git(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("hook", goal.HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        for command in ("git push", "git push -u origin x", "cd a && git -C b push --force",
                        "gh pr ready 5", "gh pr merge 5", "gh workflow run ci", "gh run rerun 9"):
            self.assertTrue(hook.blocked(command), command)
        for command in ("git status", "git stash push -m x", "git commit -m 'push it'",
                        "gh run view 9 --log-failed", "gh pr view 5", "npm run lint"):
            self.assertFalse(hook.blocked(command), command)

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


if __name__ == "__main__":
    unittest.main()
