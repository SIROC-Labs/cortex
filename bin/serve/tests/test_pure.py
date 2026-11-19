import base64
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import actions as ac  # noqa: E402
import mcp  # noqa: E402
import serve  # noqa: E402


class Repo(unittest.TestCase):
    """A git repo, conductor's home in a temp folder, and goals that never launch."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        old = os.environ.get("COND_HOME")
        os.environ["COND_HOME"] = self.home
        self.addCleanup(lambda: os.environ.__setitem__("COND_HOME", old) if old
                        else os.environ.pop("COND_HOME", None))
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.launched = []
        launch = ac.gl.launch
        ac.gl.launch = lambda root, gid: self.launched.append(gid)
        self.addCleanup(setattr, ac.gl, "launch", launch)

    def wait_on(self, gid, record):
        goal = ac.gl.Goal(self.root, gid)
        goal.state.write("awaiting.json", dict(record, asked_at="2026-11-16T10:00:00.000000Z"))
        return goal


class TestRepos(Repo):
    def test_repos_are_named_by_their_folder_and_unique(self):
        self.assertEqual([r["id"] for r in ac.repo_ids(["/a/web", "/b/web", "/c/My Repo"])],
                         ["web", "web-2", "my-repo"])

    def test_a_repo_is_added_once_by_any_folder_in_it(self):
        os.makedirs(os.path.join(self.root, "sub"))
        first = ac.add_repo(os.path.join(self.root, "sub"))
        ac.add_repo(self.root)
        self.assertEqual(ac.repos(), [first])
        self.assertEqual(first["path"], self.root)
        with self.assertRaises(ac.Problem):
            ac.add_repo(self.home)


class TestActions(Repo):
    def test_a_goal_starts_from_a_prompt_and_uploaded_files(self):
        gid = ac.start(self.root, "Make the badge red", [
            {"name": "shot.png", "data": base64.b64encode(b"png").decode()}])
        self.assertEqual(self.launched, [gid])
        self.assertEqual(ac.repos()[0]["path"], self.root)
        detail = ac.detail(self.root, gid)
        self.assertEqual((detail["name"], detail["files"], detail["waiting"]),
                         ("Make the badge red", ["inputs/shot.png"], False))
        self.assertEqual(ac.state_file(self.root, gid, "inputs/shot.png")[1], b"png")

    def test_a_goal_goes_into_the_queue_into_branch_unless_another_is_named(self):
        ac.set_settings(self.root, {"base": "feature/m1"})
        first = ac.start(self.root, "One")
        second = ac.start(self.root, "Two", base="feature/x")
        self.assertEqual([ac.detail(self.root, g)["base"] for g in (first, second)],
                         ["feature/m1", "feature/x"])

    def test_a_folder_starts_a_goal_by_its_path_or_uploaded_file_by_file(self):
        proto = os.path.join(self.home, "Proto")
        os.makedirs(proto)
        with open(os.path.join(proto, "Main.dc.html"), "w") as f:
            f.write("<x-dc></x-dc>")
        by_path = ac.start(self.root, "Build it", [proto])
        b64 = lambda t: base64.b64encode(t).decode()  # noqa: E731
        uploaded = ac.start(self.root, "Build it", [
            {"name": "Proto/Main.dc.html", "data": b64(b"<x-dc></x-dc>")},
            {"name": "Proto/css/app.css", "data": b64(b"a{}")},
            {"name": "shot.png", "data": b64(b"png")}])
        self.assertEqual(ac.detail(self.root, by_path)["files"], ["inputs/Proto/"])
        self.assertEqual(ac.detail(self.root, uploaded)["files"], ["inputs/Proto/", "inputs/shot.png"])
        self.assertEqual(ac.state_file(self.root, uploaded, "inputs/Proto/css/app.css")[1], b"a{}")
        for bad in ("../x", "/etc/passwd", "Proto/../../x"):
            with self.assertRaises(ac.Problem):
                ac.start(self.root, "x", [{"name": bad, "data": b64(b"x")}])

    def test_bad_starts_are_refused(self):
        for prompt, files in (("  ", []), ("x", [{"name": "a", "data": "%%%"}]), ("x", ["/no/such"])):
            with self.assertRaises(ac.Problem):
                ac.start(self.root, prompt, files)
        self.assertEqual(self.launched, [])

    def test_only_the_goal_s_own_files_are_readable(self):
        gid = ac.start(self.root, "x")
        goal = ac.gl.Goal(self.root, gid)
        goal.state.write("secret.json", {})
        for rel in ("goal.json", "../../x", "inputs/../goal.json", "secret.json"):
            with self.assertRaises(ac.Problem):
                ac.state_file(self.root, gid, rel)
        with self.assertRaises(ac.Problem):
            ac.detail(self.root, "../etc")

    def test_an_answer_reaches_the_question_it_answers(self):
        gid = ac.start(self.root, "x")
        with self.assertRaises(ac.Problem):
            ac.answer(self.root, gid, "Blue")
        goal = self.wait_on(gid, {"kind": "questions", "questions": [{"q": "Colour?"}]})
        self.assertTrue(ac.detail(self.root, gid)["waiting"])
        with self.assertRaises(ac.Problem):
            ac.approve(self.root, gid)
        ac.answer(self.root, gid, " Blue ")
        self.assertEqual(ac.st.local_answer(goal.state.read(ac.st.ANSWER_FILE),
                                            "2026-11-16T10:00:00.000000Z"), "Blue")

    def test_approving_a_plan_answers_it_with_an_approval(self):
        gid = ac.start(self.root, "x")
        goal = self.wait_on(gid, {"kind": "plan", "detail": "- API"})
        ac.approve(self.root, gid)
        text = goal.state.read(ac.st.ANSWER_FILE)["text"]
        self.assertTrue(ac.gl.approves(text))

    def test_stop_and_resume_follow_whether_it_runs(self):
        gid = ac.start(self.root, "x")
        self.launched.clear()
        with self.assertRaises(ac.Problem):
            ac.stop(self.root, gid)
        ac.resume(self.root, gid)
        self.assertEqual(self.launched, [gid])
        ac.gl.Goal(self.root, gid).update(status="done", phase="merged", pr_url="u")
        with self.assertRaises(ac.Problem):
            ac.resume(self.root, gid)

    def test_the_log_reads_on_from_where_it_left_off(self):
        gid = ac.start(self.root, "x")
        with open(ac.gl.Goal(self.root, gid).log, "w") as f:
            f.write("one\ntwo\n")
        first = ac.log(self.root, gid)
        self.assertEqual(first, {"text": "one\ntwo\n", "next": 8})
        self.assertEqual(ac.log(self.root, gid, first["next"]), {"text": "", "next": 8})
        self.assertEqual(ac.log(self.root, gid, -4)["text"], "two\n")

    def test_settings_have_defaults_and_bad_values_are_refused(self):
        self.assertEqual(ac.settings(self.root)["models"]["check"], ac.gl.DEFAULT_CHECK_MODEL)
        self.assertIsNone(ac.settings(self.root)["base"])
        for bad in ({"colour": 1}, {"usage_threshold": 0}, {"goal_gate": "never"},
                    {"models": {"check_effort": "huge"}}, {"models": {"lead": ""}},
                    {"base": "a b"}, {"models": {"judge": "x"}}):
            with self.assertRaises(ac.Problem):
                ac.set_settings(self.root, bad)
        done = ac.set_settings(self.root, {"usage_threshold": 60, "models": {"lead": "claude-sonnet-5-5"}})
        self.assertEqual((done["usage_threshold"], done["models"]["lead"], done["models"]["subagent"]),
                         (60, "claude-sonnet-5-5", ac.gl.DEFAULT_SUBAGENT_MODEL))


class TestDescribe(unittest.TestCase):
    def test_what_waits_on_you_comes_first_unless_the_goal_is_stopped(self):
        plan = {"asked_at": "t", "kind": "plan"}
        self.assertEqual(ac.describe({"status": "waiting", "alive": True, "awaiting": plan}),
                         ("the plan waits on your review", "warn", "waiting on you"))
        self.assertEqual(ac.describe({"status": "waiting", "alive": True, "awaiting": {
            "asked_at": "t", "questions": [{"q": "a"}, {"q": "b"}]}})[0], "has 2 questions for you")
        self.assertEqual(ac.describe({"status": "stopped", "alive": False, "awaiting": plan})[2], "stopped")

    def test_a_live_status_without_its_process_is_a_crash(self):
        self.assertEqual(ac.describe({"status": "working", "alive": False})[1:], ("bad", "stopped"))
        self.assertEqual(ac.describe({"status": "working", "alive": True, "phase": "planning"})[2], "analysing")
        self.assertEqual(ac.describe({"status": "done", "phase": "merged"}), ("merged", "", "merged"))


class TestTimeline(unittest.TestCase):
    def test_the_log_becomes_steps_with_their_lines_and_costs(self):
        import time
        created = time.mktime((2026, 11, 16, 13, 0, 0, 0, 0, -1))
        text = ("13:21:42  Reading the ask\n  1 file(s)\n\n13:22:00  Round 1\n  lead: calling claude\n"
                "Traceback: raw output\n\n23:59:00  Round 2\n\n01:40:22  Review comments on the PR\n")
        steps = ac.timeline(text, created, [{"started": created + 22 * 60 + 5, "cost": 2.5},
                                            {"started": created + 22 * 60 + 9, "cost": 0.5},
                                            {"started": None, "cost": 9}])
        self.assertEqual([s["title"] for s in steps],
                         ["Reading the ask", "Round 1", "Round 2", "Review comments on the PR"])
        self.assertEqual(steps[1]["lines"], ["lead: calling claude", "Traceback: raw output"])
        self.assertEqual(steps[1]["cost"], 3.0)
        self.assertEqual(steps[0]["at"], created + 21 * 60 + 42)
        self.assertEqual(steps[3]["at"] - steps[2]["at"], 60 + 100 * 60 + 22)
        self.assertEqual(ac.timeline("", created), [])


class TestCards(unittest.TestCase):
    def step(self, title, lines=(), at=0, cost=0.0):
        return {"title": title, "lines": list(lines), "at": at, "cost": cost}

    def test_a_round_takes_the_tasks_it_handed_out_and_phases_follow_the_work(self):
        steps = [self.step("Reading the ask"), self.step("Round 1", ["lead: calling claude", "Planned it."], 10, 1.0),
                 self.step("Reviewing the acceptance criteria", ["review: calling claude", "review: 26 turns",
                                                                 "review: 2 problem(s), 0 question(s)", "- gap"], 20),
                 self.step("The plan is ready for your review", ["answered", "the plan is approved"], 30),
                 self.step("Round 2", ["Wave 1."], 40, 0.5),
                 self.step("Running 2 task(s) from the lead", ["task: API on sonnet", "question: E1 where on sonnet",
                                                              "API: done · merged", "E1 where: done"], 50, 2.0),
                 self.step("Syncing with main", [], 60), self.step("Checking against the ask", ["verdict: 1 gap(s), 0 question(s)"], 70),
                 self.step("Round 3", [], 80), self.step("Watching the PR for review comments and the merge", [], 90),
                 self.step("Review comments on the PR", [], 100), self.step("Round 4", [], 110)]
        cs = ac.cards(steps)
        self.assertEqual([(c["title"], c["phase"]) for c in cs], [
            ("Reading the ask", "Setup"), ("Round 1", "Plan"),
            ("Reviewing the acceptance criteria", "Plan"),
            ("The plan is ready for your review", "Plan"), ("Round 2", "Build"),
            ("Syncing with main", "Check 1"), ("Checking against the ask", "Check 1"),
            ("Round 3", "Fixing gaps"), ("Watching the PR for review comments and the merge", "PR review"),
            ("Review comments on the PR", "Revision 1"), ("Round 4", "Revision 1")])
        round2 = cs[4]
        self.assertEqual((round2["cost"], round2["until"]), (2.5, 60))
        self.assertEqual(round2["tasks"], [
            {"kind": "code", "name": "API", "model": "sonnet", "result": "done · merged"},
            {"kind": "explore", "name": "E1 where", "model": "sonnet", "result": "done"}])
        self.assertEqual(round2["summary"], "Handed out 1 coding task and 1 question (sonnet): Wave 1.")
        self.assertEqual(cs[1]["summary"], "Said: Planned it.")
        self.assertEqual(cs[2]["summary"], "2 problem(s), 0 question(s)")
        self.assertEqual(cs[3]["summary"], "answered")
        self.assertEqual(ac.card_summary({"kind": "check", "lines": ["check: 3 turns", "verdict: done"]}), "clean")
        self.assertIsNone(cs[-1]["until"])

    def late_goal(self):
        return [self.step("Setting up"), self.step("Small change: building without a plan review"),
                self.step("Round 1", ["lead: 9 turns", "The badge is red."]),
                self.step("Syncing with main", ["! the merge conflicts — back to the lead"]),
                self.step("Round 2", ["Resolve the markers."]),
                self.step("Paused — Current session at 85%", ["resumes at Wed 19:49"]),
                self.step("Running 1 task(s) from the lead", ["task: Markers on sonnet"]),
                self.step("Paused — Current session at 90%", ["resumes at Wed 20:49", "Markers: done · merged"]),
                self.step("Round 3", ["Done again."]), self.step("Syncing with main"),
                self.step("Running CI's static checks here", ["1 of 3 step(s) fail"]),
                self.step("Fixing CI's static checks (1/2) on opus"),
                self.step("Running CI's static checks here again", ["! 1 step(s) still fail — over to the lead"]),
                self.step("Round 4", ["Fixed lint."]), self.step("Syncing with main"),
                self.step("Running CI's static checks here", ["CI's static checks pass here"]),
                self.step("Checking against the ask", ["verdict: 2 gap(s), 0 question(s)", "- a", "- b"]),
                self.step("Round 5", ["Fix the gaps."]), self.step("Running 2 task(s) from the lead", ["task: G1 on sonnet"]),
                self.step("Round 6", ["Done."]), self.step("Syncing with main"),
                self.step("Running CI's static checks here", ["CI's static checks pass here"]),
                self.step("Checking against the ask", ["verdict: done"]),
                self.step("Syncing with main", ["PR marked ready for review: u"]),
                self.step("Waiting for CI", ["! CI failed: test"]), self.step("Fixing CI (1/2) on sonnet"),
                self.step("Waiting for CI", ["CI passed: test"]), self.step("Finishing"),
                self.step("Watching the PR for review comments and the merge"),
                self.step("Review comments on the PR"), self.step("Round 7", ["Fix comment 1."]),
                self.step("Syncing with main"), self.step("Running CI's static checks here"),
                self.step("Checking against the ask", ["verdict: done"])]

    def test_late_phases_say_what_the_goal_does_and_a_revision_names_its_own(self):
        cs = ac.cards(self.late_goal())
        self.assertEqual([(c["title"], c["phase"]) for c in cs], [
            ("Setting up", "Setup"), ("Small change: building without a plan review", "Build"),
            ("Round 1", "Build"), ("Syncing with main", "Merge conflict"), ("Round 2", "Merge conflict"),
            ("Round 3", "Merge conflict"), ("Syncing with main", "Static checks"),
            ("Running CI's static checks here", "Static checks"),
            ("Fixing CI's static checks (1/2) on opus", "Static checks"),
            ("Running CI's static checks here again", "Static checks"), ("Round 4", "Fixing static checks"),
            ("Syncing with main", "Static checks"), ("Running CI's static checks here", "Static checks"),
            ("Checking against the ask", "Check 1"), ("Round 5", "Fixing gaps"), ("Round 6", "Fixing gaps"),
            ("Syncing with main", "Static checks"), ("Running CI's static checks here", "Static checks"),
            ("Checking against the ask", "Check 2"), ("Syncing with main", "Merge and push"),
            ("Waiting for CI", "CI"), ("Fixing CI (1/2) on sonnet", "CI"), ("Waiting for CI", "CI"),
            ("Finishing", "CI"), ("Watching the PR for review comments and the merge", "PR review"),
            ("Review comments on the PR", "Revision 1"), ("Round 7", "Revision 1"),
            ("Syncing with main", "Revision 1 · Static checks"),
            ("Running CI's static checks here", "Revision 1 · Static checks"),
            ("Checking against the ask", "Revision 1 · Check 1")])
        round2 = cs[4]
        self.assertEqual(round2["tasks"], [{"kind": "code", "name": "Markers", "model": "sonnet",
                                            "result": "done · merged"}])
        self.assertEqual(round2["summary"], "Handed out 1 coding task (sonnet): Resolve the markers.")
        self.assertEqual(cs[5]["summary"], "Reported done: Done again.")
        self.assertEqual(ac.cards(self.late_goal()[:10])[-1]["phase"], "Static checks")
        self.assertEqual(ac.cards([self.step("Small change: building without a plan review"),
                                   self.step("Checking against the ask", ["verdict: done"]),
                                   self.step("Syncing with goal/x")], part=True)[-1]["phase"], "Merge")

    def strip(self, steps, **data):
        return " ▸ ".join(("[%s]" if s["state"] == "now" else "%s✓" if s["state"] == "done" else "%s") % s["label"]
                          for s in ac.stage_strip(ac.cards(steps), dict({"status": "working"}, **data)))

    def test_the_stage_strip_marks_where_the_goal_is_and_names_its_checks(self):
        steps = self.late_goal()
        self.assertEqual(self.strip(steps[:3]), "Plan✓ ▸ [Build] ▸ Static checks ▸ Check ▸ Push ▸ CI ▸ PR review")
        self.assertEqual(self.strip(steps[:13]), "Plan✓ ▸ Build✓ ▸ [Static checks] ▸ Check ▸ Push ▸ CI ▸ PR review")
        self.assertEqual(self.strip(steps[:17]), "Plan✓ ▸ Build✓ ▸ Static checks✓ ▸ [Check 1: 2 gaps] ▸ "
                                                 "Fixing gaps ▸ Check again ▸ Push ▸ CI ▸ PR review")
        self.assertEqual(self.strip(steps[:19]), "Plan✓ ▸ Build✓ ▸ Static checks✓ ▸ Check 1: 2 gaps✓ ▸ "
                                                 "[Fixing gaps] ▸ Check again ▸ Push ▸ CI ▸ PR review")
        self.assertEqual(self.strip(steps[:22]), "Plan✓ ▸ Build✓ ▸ Static checks✓ ▸ Check 1: 2 gaps✓ ▸ "
                                                 "Fixing gaps✓ ▸ [Check again] ▸ Push ▸ CI ▸ PR review")
        self.assertEqual(self.strip(steps[:25]), "Plan✓ ▸ Build✓ ▸ Static checks✓ ▸ Check 1: 2 gaps✓ ▸ "
                                                 "Fixing gaps✓ ▸ Check 2: clean✓ ▸ Push✓ ▸ [CI] ▸ PR review")
        self.assertEqual(self.strip(steps[:29], status="review"),
                         "Plan✓ ▸ Build✓ ▸ Static checks✓ ▸ Check 1: 2 gaps✓ ▸ Fixing gaps✓ ▸ "
                         "Check 2: clean✓ ▸ Push✓ ▸ CI✓ ▸ [PR review]")
        self.assertEqual(self.strip(steps[:31]), "Plan✓ ▸ [Revision 1] ▸ Static checks ▸ Check ▸ Push ▸ CI ▸ PR review")
        self.assertEqual(self.strip(steps, status="done", phase="merged", pr_url="u"),
                         "Plan✓ ▸ Revision 1✓ ▸ Static checks✓ ▸ Check 1: clean✓ ▸ Push✓ ▸ CI✓ ▸ PR review✓")
        self.assertEqual(self.strip(steps[:1], parent="goal-x"), "[Plan] ▸ Build ▸ Static checks ▸ Check ▸ Merge")

    def test_who_works_now_says_who_in_a_line(self):
        cs = ac.cards(self.late_goal()[:19])
        data = {"status": "working", "alive": True, "phase": "building"}
        self.assertEqual(ac.who_works(data, [], [{"status": "running", "kind": "code", "model": "claude-sonnet-5-5"},
                                                  {"status": "running", "kind": "code", "model": "claude-sonnet-5-5"},
                                                  {"status": "waiting", "kind": "code"}], cs),
                         "2 coding tasks on Sonnet run, 1 more wait to start; the lead waits for their reports")
        self.assertEqual(ac.who_works(data, [{"role": "Lead", "model": "claude-opus-5-5"}], [], cs),
                         "The lead (Opus) reads the reports and decides what to hand out next")
        self.assertEqual(ac.who_works(dict(data, status="checking"), [{"role": "Checker", "model": "claude-opus-5-5"}],
                                      [], cs), "The checker (Opus) checks the branch against the ask and its criteria")
        self.assertEqual(ac.who_works(dict(data, status="waiting", awaiting={"asked_at": "t", "questions": [{"q": "a"}]}),
                                      [], [], cs), "You: it has 1 question for you")
        self.assertEqual(ac.who_works(dict(data, status="checking", runner_doing="31 step(s) of CI's static checks"),
                                      [], [], cs), "The runner: 31 step(s) of CI's static checks")


class TestAsked(Repo):
    def setUp(self):
        Repo.setUp(self)
        import asked
        self.asked = asked
        self.gid = ac.start(self.root, "x")
        self.goal = self.wait_on(self.gid, {"kind": "questions", "questions": [{"q": "Colour?"}, {"q": "Size?"}]})

    def test_numbered_answers_split_by_question_and_the_rest_is_a_note(self):
        self.assertEqual(self.asked.split_answers("1. Red\n2. Big,\nreally\n\nAnd hurry.", 2),
                         (["Red", "Big,\nreally"], "And hurry."))
        self.assertEqual(self.asked.split_answers("Red and big", 2), (None, "Red and big"))
        self.assertEqual(self.asked.split_answers("2. Big\n1. Red", 2), (None, "2. Big\n1. Red"))

    def test_a_sent_answer_shows_until_the_goal_picks_it_up_and_stays_in_the_history(self):
        self.assertIsNone(ac.detail(self.root, self.gid)["sent"])
        ac.answer(self.root, self.gid, "1. Red\n2. Big\n\nThanks", ["Red", "Big"], "Thanks")
        sent = ac.detail(self.root, self.gid)["sent"]
        self.assertEqual(sent["items"], [{"q": "Colour?", "a": "Red"}, {"q": "Size?", "a": "Big"}])
        self.assertEqual(sent["note"], "Thanks")
        self.goal.state.remove(ac.st.ANSWER_FILE)
        self.goal.state.remove("awaiting.json")
        self.assertIsNone(ac.detail(self.root, self.gid)["sent"])
        with open(self.goal.log, "w") as f:
            f.write("10:00:00  Asking you\n  Q: Colour?\n  Q: Size?\n  waiting on you\n  answered\n\n"
                    "10:01:00  Round 2\n")
        asked_at = self.asked.epoch("2026-11-16T10:00:00.000000Z")
        cs = [{"kind": "you", "title": "Asking you", "lines": ["Q: Colour?", "Q: Size?", "answered"],
               "at": asked_at, "until": None}]
        self.asked.attach(cs, self.goal, {}, [])
        self.assertEqual(cs[0]["qa"]["items"][1], {"q": "Size?", "a": "Big"})

    def test_a_plan_decision_puts_its_talks_away(self):
        self.goal = self.wait_on(self.gid, {"kind": "plan"})
        os.makedirs(self.goal.state.path("discussions"))
        for name in ("plan-20261116T100000000000Z.json", "plan-now.json", "q1-x.json"):
            self.goal.state.write("discussions/" + name, {"messages": [{"role": "person", "text": "hi"}]})
        ac.approve(self.root, self.gid)
        self.assertEqual(sorted(n for n in os.listdir(self.goal.state.path("discussions")) if n.endswith(".json")),
                         ["q1-x.json"])
        self.assertTrue(ac.detail(self.root, self.gid)["sent"]["approved"])

    def test_earlier_answers_are_read_back_from_the_lead_s_prompts(self):
        prompt = ("Before you build, a reviewer found:\n\n- gap\n\nThe person was asked:\n\n"
                  "- Colour? (options: A. Red; B. Blue)\n- Size?\n\nThey answered:\n\n1. A. Red\n2. Big\n\n"
                  "Correct the criteria, the plan and the parts first: everything is built from them.")
        self.assertEqual(self.asked.answers_in_prompt(prompt), [
            {"kind": "questions", "questions": ["Colour?", "Size?"], "text": "1. A. Red\n2. Big"}])
        changes = ("The person reviewed your plan and asked for changes:\n\nUse WhatsApp.\n\n"
                   "Revise your journal to answer it: the acceptance criteria")
        self.assertEqual(self.asked.answers_in_prompt(changes), [{"kind": "plan", "questions": [], "text": "Use WhatsApp."}])
        path = os.path.join(self.home, "s.jsonl")
        row = lambda t, ts: json.dumps({"type": "user", "timestamp": ts, "message": {"content": t}}) + "\n"  # noqa: E731
        with open(path, "w") as f:
            f.write(row(prompt, "2026-11-16T10:05:00.000Z"))
        self.assertEqual(len(self.asked.scan(path)), 1)
        with open(path, "a") as f:
            f.write(row(changes, "2026-11-16T11:00:00.000Z") + '{"type": "user", "message": {"content": "They answered:')
        found = self.asked.scan(path)
        self.assertEqual([(a["kind"], a["at"]) for a in found],
                         [("questions", self.asked.epoch("2026-11-16T10:05:00Z")),
                          ("plan", self.asked.epoch("2026-11-16T11:00:00Z"))])


class TestRunning(unittest.TestCase):
    def setUp(self):
        import running
        self.running = running
        running._SUMMARIES.clear()

    def test_the_summary_model_is_haiku_on_claude_and_the_cheapest_priced_one_on_opencode(self):
        self.assertEqual(self.running.model_for({"model": "claude-opus-5-5"}, {}), "haiku")
        control = {"providers": [{"id": "big", "models": ["m1"], "input_price": 3, "output_price": 15},
                                 {"id": "small", "models": ["m2", "m3"], "input_price": 0.1, "output_price": 0.4},
                                 {"id": "free", "models": ["m4"]}]}
        self.assertEqual(self.running.model_for({"model": "big/m1"}, control), "small/m2")
        self.assertIsNone(self.running.model_for({"model": "free/m4"}, {"providers": control["providers"][2:]}))

    def test_a_summary_is_asked_for_when_the_agent_moved_and_at_most_every_45_seconds(self):
        asked = []
        spawn = lambda f, args: (asked.append(args[0]), f(*args))  # noqa: E731

        def runner(cmd, **kw):
            class P(object):
                stdout = json.dumps({"result": "It fixes the badge colour so it matches the prototype."}).encode()
            return P()
        live = lambda at: [{"role": "Lead", "path": "/nowhere/s.jsonl", "at": at}]  # noqa: E731
        first = self.running.summarize(live(10), {"model": "claude-opus-5-5"}, {}, 1000, runner, spawn)
        self.assertEqual(first[0]["summary"], "It fixes the badge colour so it matches the prototype.")
        self.running.summarize(live(10), {"model": "claude-opus-5-5"}, {}, 1100, runner, spawn)
        self.running.summarize(live(20), {"model": "claude-opus-5-5"}, {}, 1020, runner, spawn)
        self.assertEqual(len(asked), 1)
        self.running.summarize(live(20), {"model": "claude-opus-5-5"}, {}, 1050, runner, spawn)
        self.assertEqual(len(asked), 2)

    def test_a_summary_that_fails_is_left_out(self):
        def runner(cmd, **kw):
            raise OSError("no claude")
        spawn = lambda f, args: f(*args)  # noqa: E731
        out = self.running.summarize([{"role": "Lead", "path": "/nowhere/f.jsonl", "at": 1}], {"model": "x"}, {},
                                     1000, runner, spawn)
        self.assertIsNone(out[0]["summary"])
        self.assertEqual(self.running.summarize([{"role": "Lead", "path": "/n/g.jsonl", "at": 1}],
                                                {"model": "free/m"}, {}, 1000, runner, spawn)[0]["summary"], None)

    def test_the_lead_s_own_edits_of_repo_files_are_found_and_its_journal_is_not_one(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home)
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = home
        self.addCleanup(lambda: os.environ.__setitem__("CLAUDE_CONFIG_DIR", old) if old
                        else os.environ.pop("CLAUDE_CONFIG_DIR", None))
        root = "/r/web"
        worktree = root + "/.cortex/worktrees/goal-x"
        os.makedirs(os.path.join(home, "projects", "w"))

        def use(n, file, ts="2026-11-16T10:00:00.000Z"):
            return json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": [
                {"type": "tool_use", "id": "t%d" % n, "name": "Edit", "input": {"file_path": file}}]}})

        def result(n, error=False):
            return json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t%d" % n, "is_error": error}]}})
        with open(os.path.join(home, "projects", "w", "lead-1.jsonl"), "w") as f:
            f.write("\n".join([use(1, worktree + "/src/app.ts"), result(1),
                               use(2, root + "/.cortex/state/goal-x/journal.md"), result(2),
                               use(3, worktree + "/src/b.ts"), result(3, error=True), ""]))
        edits = self.running.lead_edits(root, {"worktree": worktree}, [
            {"label": "lead", "session": "lead-1", "round": 4, "started": 0}])
        self.assertEqual([(e["file"], e["round"], e["by"]) for e in edits], [("src/app.ts", 4, "lead")])


class TestProviders(Repo):
    def test_custom_providers_name_the_key_s_variable_and_are_checked(self):
        good = {"id": "acme", "base_url": "https://llm.acme/v1", "key_env": "ACME_KEY",
                "models": ["qwen3-coder"], "input_price": 0.5, "output_price": None}
        self.assertEqual(ac.set_settings(self.root, {"providers": [good]})["providers"],
                         [{"id": "acme", "base_url": "https://llm.acme/v1", "key_env": "ACME_KEY",
                           "models": ["qwen3-coder"], "input_price": 0.5}])
        for bad in (dict(good, key_env="sk-live-123"), dict(good, id="Acme Co"), dict(good, base_url="ftp://x"),
                    dict(good, models=[]), dict(good, models=["acme/q"]), dict(good, extra=1),
                    dict(good, input_price=-1)):
            with self.assertRaises(ac.Problem):
                ac.set_settings(self.root, {"providers": [bad]})
        with self.assertRaises(ac.Problem):
            ac.set_settings(self.root, {"providers": [good, good]})
        builtin = {"id": "openrouter", "models": ["qwen/qwen3-coder"]}
        self.assertEqual(ac.set_settings(self.root, {"providers": [builtin]})["providers"], [builtin])
        self.assertEqual(ac.set_settings(self.root, {"providers": []})["providers"], [])


class TestRunner(Repo):
    def test_goals_run_on_claude_unless_opencode_is_chosen_with_its_own_models(self):
        self.assertEqual(ac.settings(self.root)["runner"], "claude")
        with self.assertRaises(ac.Problem):
            ac.set_settings(self.root, {"runner": "pi"})
        with self.assertRaises(ac.Problem):
            ac.set_settings(self.root, {"opencode_models": {"lead": "claude-opus-5-5"}})
        with self.assertRaises(ac.Problem):
            ac.set_settings(self.root, {"models": {"lead": "openrouter/x"}})
        ac.set_settings(self.root, {"runner": "opencode", "opencode_models": {"lead": "openrouter/a"}})
        with self.assertRaises(ac.Problem):
            ac.start(self.root, "Do it")
        ac.set_settings(self.root, {"opencode_models": {"subagent": "openrouter/b", "check": "openrouter/c"}})
        gid = ac.start(self.root, "Do it")
        g = ac.detail(self.root, gid)
        self.assertEqual((g["model"], g["subagent_model"], g["check_model"]),
                         ("openrouter/a", "openrouter/b", "openrouter/c"))
        ac.set_settings(self.root, {"runner": "claude"})
        g = ac.detail(self.root, ac.start(self.root, "Again"))
        self.assertEqual(g["model"], ac.gl.DEFAULT_MODEL)


class TestDiscuss(Repo):
    def setUp(self):
        Repo.setUp(self)
        import discuss
        self.discuss = discuss
        self.gid = ac.start(self.root, "Build the badge")
        self.goal = ac.gl.Goal(self.root, self.gid)
        self.goal.update(ask="# The ask\n\nBuild the badge", model="claude-opus-5-5")
        with open(self.goal.journal, "w") as f:
            f.write("## References\n- prototype: badge.html\n\n## Decisions\n- D1: red\n\n"
                    "## Acceptance criteria\n- [ ] The badge is red\n\n## Plan\n1. [ ] Badge: red\n")
        with open(self.goal.state.path("technical-plan.md"), "w") as f:
            f.write("# Technical plan\nUse the token.")
        self.goal.state.write("awaiting.json", {"kind": "questions", "asked_at": "2026-11-17T10:00:00Z",
                                                "questions": [{"q": "Which red?", "why": "They differ.",
                                                               "options": [{"label": "A. Mock", "means": "exact"}]}]})
        self.calls = []

    def runner(self, reply="Pick A: it matches the prototype."):
        def run(cmd, **kw):
            self.calls.append(cmd)
            class P(object):
                stdout = json.dumps({"result": reply, "session_id": "s"}).encode()
            return P()
        return run

    def test_a_question_thread_starts_from_its_question_and_carries_on_in_its_session(self):
        out = self.discuss.say(self.root, self.gid, "q1", "Which is closer to the prototype?", runner=self.runner())
        first = self.calls[0]
        prompt = first[-1]
        self.assertIn("Which red?", prompt)
        self.assertIn("A. Mock → exact", prompt)
        self.assertIn("D1: red", prompt)
        self.assertIn("Build the badge", prompt)
        self.assertNotIn("Use the token", prompt)
        self.assertIn("--session-id", first)
        self.assertIn("--disallowedTools", first)
        self.assertEqual([m["role"] for m in out["messages"]], ["person", "agent"])
        self.discuss.say(self.root, self.gid, "q1", "And B?", runner=self.runner())
        self.assertIn("--resume", self.calls[1])
        self.assertEqual(self.calls[1][-1], "And B?")
        self.assertEqual(len(self.discuss.read(self.root, self.gid, "q1")["messages"]), 4)

    def test_the_plan_thread_gets_the_plan_and_a_new_question_a_new_thread(self):
        self.discuss.say(self.root, self.gid, "plan", "Is the token right?", runner=self.runner())
        self.assertIn("Use the token", self.calls[0][-1])
        self.assertIn("The badge is red", self.calls[0][-1])
        self.goal.state.write("awaiting.json", dict(self.goal.state.read("awaiting.json"), asked_at="later"))
        self.assertEqual(self.discuss.read(self.root, self.gid, "plan")["messages"], [])

    def test_a_talk_starts_over_and_not_while_a_reply_is_coming(self):
        self.discuss.say(self.root, self.gid, "q1", "Which?", runner=self.runner())
        self.assertEqual(self.discuss.clear(self.root, self.gid, "q1")["messages"], [])
        self.assertEqual(self.discuss.read(self.root, self.gid, "q1")["messages"], [])
        self.discuss._RUNNING.add((self.root, self.gid, self.discuss.read(self.root, self.gid, "q1")["key"]))
        self.addCleanup(self.discuss._RUNNING.clear)
        with self.assertRaises(ac.Problem):
            self.discuss.clear(self.root, self.gid, "q1")

    def test_bad_topics_and_failures_are_said(self):
        for topic, text in (("q9", "x"), ("zz", "x"), ("q1", " ")):
            with self.assertRaises(ac.Problem):
                self.discuss.say(self.root, self.gid, topic, text, runner=self.runner())
        out = self.discuss.say(self.root, self.gid, "q1", "Hm?", runner=self.runner(reply=""))
        self.assertEqual(out["error"], "no reply")
        self.assertEqual([m["role"] for m in out["messages"]], ["person"])


class TestHTTP(Repo):
    def setUp(self):
        Repo.setUp(self)
        self.server = serve.make_server(0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.rid = ac.add_repo(self.root)["id"]

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, payload, dict({"Content-Type": "application/json"},
                                                 **(headers or {})))
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(data) if data else None
        except ValueError:
            return resp.status, data

    def test_a_goal_through_the_api(self):
        status, body = self.call("POST", "/api/repos/%s/goals" % self.rid, {
            "prompt": "Fix the badge", "files": [{"name": "a.txt", "data": base64.b64encode(b"hi").decode()}]})
        self.assertEqual(status, 200)
        gid = body["goal"]
        status, goals = self.call("GET", "/api/goals")
        self.assertEqual([(g["repo"], g["id"]) for g in goals], [(self.rid, gid)])
        status, goal = self.call("GET", "/api/repos/%s/goals/%s" % (self.rid, gid))
        self.assertEqual((status, goal["files"]), (200, ["inputs/a.txt"]))
        status, raw = self.call("GET", "/api/repos/%s/goals/%s/files/inputs/a.txt" % (self.rid, gid))
        self.assertEqual((status, raw), (200, b"hi"))
        self.wait_on(gid, {"kind": "plan"})
        self.assertEqual(self.call("POST", "/api/repos/%s/goals/%s/approve" % (self.rid, gid)),
                         (200, {"result": "approved"}))
        self.assertEqual(self.call("POST", "/api/repos/%s/goals/%s/stop" % (self.rid, gid))[0], 409)
        self.assertEqual(self.call("POST", "/api/repos/%s/goals/%s/fly" % (self.rid, gid))[0], 404)
        self.assertEqual(self.call("GET", "/api/repos/nope/goals")[0], 404)
        status, settings = self.call("PUT", "/api/repos/%s/settings" % self.rid, {"goal_gate": "auto"})
        self.assertEqual((status, settings["goal_gate"]), (200, "auto"))
        self.assertEqual(self.call("PUT", "/api/repos/%s/settings" % self.rid, {"goal_gate": "x"})[0], 400)

    def test_other_sites_and_other_hosts_are_refused(self):
        self.assertEqual(self.call("GET", "/api/repos", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("GET", "/api/repos", headers={"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.call("GET", "/api/repos", headers={
            "Origin": "http://localhost:%d" % self.port})[0], 200)

    def test_mcp_lists_and_calls_tools(self):
        status, init = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                  "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual((status, init["result"]["protocolVersion"]), (200, "2025-03-26"))
        self.assertEqual(self.call("POST", "/mcp", {"jsonrpc": "2.0",
                                                    "method": "notifications/initialized"})[0], 202)
        status, tools = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("start_goal", [t["name"] for t in tools["result"]["tools"]])
        status, started = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                     "params": {"name": "start_goal", "arguments": {
                                                         "repo": self.rid, "prompt": "Do it"}}})
        gid = json.loads(started["result"]["content"][0]["text"])["goal"]
        self.assertEqual(self.launched, [gid])
        status, refused = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                     "params": {"name": "approve_plan", "arguments": {
                                                         "repo": self.rid, "goal": gid}}})
        self.assertTrue(refused["result"]["isError"])
        self.assertEqual(self.call("GET", "/mcp")[0], 405)


class TestMCP(unittest.TestCase):
    def test_bad_messages_get_json_rpc_errors(self):
        self.assertEqual(mcp.handle(b"{")[1]["error"]["code"], -32700)
        self.assertEqual(mcp.handle(b'{"jsonrpc": "2.0", "id": 1, "method": "x"}')[1]["error"]["code"],
                         -32601)
        status, replies = mcp.handle(b'[{"jsonrpc": "2.0", "id": 1, "method": "ping"},'
                                     b' {"jsonrpc": "2.0", "method": "notifications/x"}]')
        self.assertEqual((status, replies), (200, [{"jsonrpc": "2.0", "id": 1, "result": {}}]))

    def test_every_tool_has_a_closed_schema(self):
        for tool in mcp.TOOLS:
            self.assertFalse(tool["inputSchema"]["additionalProperties"], tool["name"])
            for name in tool["inputSchema"]["required"]:
                self.assertIn(name, tool["inputSchema"]["properties"], tool["name"])


class TestLaunchd(unittest.TestCase):
    def test_the_job_loads_zshrc_and_the_login_path_and_runs_the_service(self):
        text = serve.plist("/x/cond", 4747, "/h/serve.log")
        self.assertIn("<string>/bin/zsh</string><string>-l</string><string>-i</string><string>-c</string>"
                      "<string>exec /x/cond serve --port 4747</string>", text)
        self.assertIn("<key>KeepAlive</key><true/>", text)


if __name__ == "__main__":
    unittest.main()
