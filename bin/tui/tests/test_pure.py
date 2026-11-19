import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tui  # noqa: E402

NOW = 1_800_000_000


def goal(gid, **kw):
    return dict({"id": gid, "repo": "web", "title": gid, "status": "working", "alive": True,
                 "created": NOW - 100, "state": {"text": "working", "tone": "ok", "label": "working"}}, **kw)


GOALS = [
    goal("done-1", finished=True, status="done", created=NOW - 50,
         state={"text": "merged", "tone": "", "label": "merged"}),
    goal("busy", round=3, cost=4.5, plan={"done": 2, "total": 5}, created=NOW - 40),
    goal("busy--api", parent="busy", part="API", parent_title="busy"),
    goal("asks", waiting=True, created=NOW - 300, pr_url="https://gh/pr/7",
         awaiting={"asked_at": "t", "kind": "plan", "detail": "- API\n- UI"},
         state={"text": "the plan waits on your review", "tone": "warn", "label": "waiting on you"}),
]


class FakeClient(object):
    url = "http://127.0.0.1:4747"

    def __init__(self):
        self.calls = []
        self.detail = goal("asks", awaiting=GOALS[3]["awaiting"], timeline=[
            {"i": 0, "kind": "step", "phase": "Setup", "title": "Reading the ask", "at": NOW - 300,
             "until": NOW - 290, "cost": 0, "summary": "1 file(s)", "lines": ["1 file(s)"], "tasks": None},
            {"i": 1, "kind": "round", "phase": "Build", "title": "Round 2", "at": NOW - 200, "until": None,
             "cost": 2.5, "summary": "Running 1 task(s) · Wave 1.", "lines": ["lead: 9 turns", "Wave 1."],
             "tasks": [{"kind": "code", "name": "API", "model": "sonnet", "result": "failed · kept"}]}])

    def goals(self):
        return GOALS

    def goal(self, repo, gid):
        self.calls.append(("goal", repo, gid))
        return self.detail

    def log(self, repo, gid, start):
        return {"text": "one\ntwo\n", "next": 8}

    def act(self, repo, gid, action, body=None):
        self.calls.append((action, repo, gid, body))
        return {"result": "ok"}


class TestHelpers(unittest.TestCase):
    def test_waiting_goals_first_then_running_then_finished_each_with_its_parts(self):
        self.assertEqual([(g["id"], part) for g, part in tui.ordered(GOALS)],
                         [("asks", False), ("busy", False), ("busy--api", True), ("done-1", False)])
        self.assertNotIn("done-1", [g["id"] for g, _ in tui.ordered(GOALS, show_finished=False)])
        done = [goal("old", finished=True), goal("old--a", parent="old", part="A", finished=True),
                goal("old--b", parent="old", part="B")]
        self.assertEqual([g["id"] for g, _ in tui.ordered(done, show_finished=False)], ["old", "old--a", "old--b"])
        self.assertEqual(tui.ordered(done[:2], show_finished=False), [])

    def test_status_lines_flag_what_waits_and_give_the_pr(self):
        lines = tui.status_lines(GOALS, NOW)
        self.assertTrue(lines[0].startswith("⚑ waiting on you"))
        self.assertIn("the plan waits on your review", lines[0])
        self.assertTrue(lines[0].endswith("https://gh/pr/7"))
        self.assertIn("busy — working  ·  plan 2/5  round 3  $4.50  now", lines[1])
        self.assertIn("└ API", lines[2])
        self.assertEqual(tui.status_lines([]), ["no goals"])

    def test_a_plan_s_wait_says_how_to_approve_and_questions_show_their_options(self):
        text = [t for t, _ in tui.wait_lines(GOALS[3]["awaiting"], 80)]
        self.assertEqual(text[0], "The plan waits on your review")
        self.assertIn("  - API", text)
        q = {"asked_at": "t", "questions": [{"q": "Which red?", "why": "They differ.", "recommend": "B",
                                             "options": [{"label": "A. Mock", "means": "exact", "flow": ["Shows it."]}]}]}
        text = [t for t, _ in tui.wait_lines(q, 80)]
        self.assertEqual(text[:5], ["1 question for you", "  1. Which red?", "     They differ.",
                                    "     A. Mock → exact", "        Shows it."])
        self.assertEqual(tui.wait_lines({}, 80), [])

    def test_the_editor_template_drops_its_comments(self):
        template = tui.answer_template("asks", GOALS[3]["awaiting"])
        self.assertIn("# The plan waits on your review", template)
        self.assertEqual(tui.parse_answer("Drop the export.\n" + template), "Drop the export.")
        self.assertIsNone(tui.parse_answer(template))

    def test_a_goal_screen_shows_its_wait_then_its_timeline_by_phase(self):
        g = FakeClient().detail
        lines, starts = tui.goal_lines(g, 100, opened={1}, selected=1, now=NOW)
        text = [t for t, _ in lines]
        self.assertIn("  The plan waits on your review", text)
        self.assertLess(text.index("SETUP"), text.index("BUILD"))
        self.assertTrue(text[starts[1]].startswith("▾ Round 2  Running 1 task(s) · Wave 1."))
        self.assertEqual(lines[starts[1]][1], "sel")
        self.assertIn("    Wave 1.", text)
        self.assertNotIn("    lead: 9 turns", text)
        self.assertIn(("    code     API  —  failed · kept · sonnet", "bad"), lines)
        self.assertTrue(text[starts[0]].startswith("▸ Reading the ask"))

    def test_a_goal_screen_shows_its_stages_who_works_and_what_was_answered(self):
        g = dict(FakeClient().detail, who="The lead (Opus) reads the reports and decides what to hand out next",
                 stages=[{"label": "Plan", "state": "done"}, {"label": "Fixing gaps", "state": "now"},
                         {"label": "Push", "state": "next"}],
                 sent={"kind": "plan", "approved": True, "text": "approved"},
                 lead_edits=[{"file": "src/app.ts", "tool": "Edit", "by": "lead", "round": 4}])
        g["timeline"] = g["timeline"] + [{"i": 2, "kind": "you", "phase": "Build", "title": "Asking you", "at": NOW,
                                          "until": None, "cost": 0, "summary": "1 question · answered", "lines": [],
                                          "tasks": None, "qa": {"kind": "questions", "note": None,
                                                                "items": [{"q": "Colour?", "a": "Red"}]}}]
        text = [t for t, _ in tui.goal_lines(g, 100, opened={2}, now=NOW)[0]]
        self.assertIn("✓ Plan ▸ [Fixing gaps] ▸ Push", text)
        self.assertIn("The lead (Opus) reads the reports and decides what to hand out next", text)
        self.assertIn("  Plan approved — the goal carries on as soon as it picks it up", text)
        self.assertNotIn("  The plan waits on your review", text)
        self.assertIn("  src/app.ts  · Edit by lead in round 4", text)
        self.assertEqual(text[-2:], ["    1. Colour?", "       → Red"])

    def test_money_and_spans(self):
        self.assertEqual((tui.money(0), tui.money(2.456)), ("", "$2.46"))
        self.assertEqual([tui.span(s) for s in (5, 300, 4000)], ["5s", "5m", "1h 7m"])


class TestApp(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.app = tui.App(self.client)
        self.app.load(force=True)

    def test_the_list_opens_a_goal_and_back(self):
        _, lines, _, keys = self.app.lines(120, 40)
        self.assertEqual(lines[0][1], "sel")
        self.assertEqual(keys, tui.LIST_KEYS)
        self.app.key("\n")
        self.assertEqual((self.app.screen, self.app.where), ("goal", ("web", "asks")))
        self.assertEqual(self.app.card, 1)
        self.app.key("KEY_UP")
        self.assertEqual((self.app.card, self.app.follow), (0, False))
        self.app.key("KEY_LEFT")
        self.assertEqual(self.app.screen, "list")

    def test_c_approves_a_waiting_plan_and_a_asks_for_a_line(self):
        self.app.key("c")
        self.assertEqual(self.client.calls[-1][:3], ("approve", "web", "asks"))
        self.assertEqual(self.app.key("a"), ("line", "answer: "))
        self.assertEqual(self.app.key("A")[0], "editor")
        self.app.answer("Drop the export.")
        self.assertEqual(self.client.calls[-1], ("answer", "web", "asks", {"text": "Drop the export."}))

    def test_stopping_asks_first(self):
        self.app.key("j")
        self.app.key("x")
        self.assertIn("stop \"busy\"?", self.app.ask[0])
        self.app.key("n")
        self.assertFalse([c for c in self.client.calls if c[0] == "stop"])
        self.app.key("x")
        self.app.key("y")
        self.assertEqual(self.client.calls[-1][:3], ("stop", "web", "busy"))

    def test_space_folds_and_unfolds_a_goal_s_parts(self):
        self.app.key("j")
        self.assertIn("busy--api", [g["id"] for g, _ in self.app.rows()])
        self.app.key(" ")
        self.assertNotIn("busy--api", [g["id"] for g, _ in self.app.rows()])
        self.app.key(" ")
        self.assertIn("busy--api", [g["id"] for g, _ in self.app.rows()])

    def test_nothing_to_answer_says_so(self):
        self.app.key("j")
        self.app.key("a")
        self.assertEqual(self.app.message, "nothing waits on you there")

    def test_a_service_that_does_not_answer_is_shown(self):
        class Down(FakeClient):
            def goals(self):
                raise tui.Unreachable("the service does not answer")
        app = tui.App(Down())
        app.load(force=True)
        _, lines, _, _ = app.lines(80, 20)
        self.assertEqual(lines[0], ("the service does not answer", "bad"))
        self.assertFalse(app.key("q"))

    def test_the_log_tails_the_goal_s_log(self):
        self.app.key("\n")
        self.app.key("L")
        title, lines, _, keys = self.app.lines(80, 20)
        self.assertEqual([t for t, _ in lines], ["one", "two"])
        self.assertEqual(keys, tui.LOG_KEYS)


class TestClient(unittest.TestCase):
    def test_a_closed_port_is_unreachable(self):
        with self.assertRaises(tui.Unreachable):
            tui.Client("http://127.0.0.1:9").goals()


if __name__ == "__main__":
    unittest.main()
