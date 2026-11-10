import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import goal_view as gv  # noqa: E402


def line(at, kind="assistant", model="claude-opus-5-5", **block):
    content = [block] if block else []
    return json.dumps({"type": kind, "timestamp": at,
                       "message": {"model": model, "content": content}})


class TestGoalView(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.environ["CLAUDE_CONFIG_DIR"] = self.base
        self.worktree = "/r/.cortex/worktrees/goal-1-x"
        self.folder = os.path.join(self.base, "projects", "-r--cortex-worktrees-goal-1-x")
        os.makedirs(os.path.join(self.folder, "s1", "subagents"))
        self.goal = {"id": "goal-1-x", "worktree": self.worktree, "session": "s1",
                     "doing": "round 2", "round": 2, "cost": 1.5,
                     "status": "working"}

    def tearDown(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        shutil.rmtree(self.base)

    def write(self, path, lines):
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def agent(self, name, description, finished, lines):
        self.write(os.path.join(self.folder, "s1", "subagents", "agent-%s.jsonl" % name), lines)
        with open(os.path.join(self.folder, "s1", "subagents", "agent-%s.meta.json" % name), "w") as f:
            json.dump({"description": description, "finished": finished}, f)

    def test_the_folder_is_the_worktree_path_with_dashes(self):
        self.assertEqual(gv.project_dir(self.worktree), self.folder)
        self.assertIsNone(gv.project_dir("/elsewhere"))

    def test_the_lead_and_its_sub_agents_as_they_stand(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write(os.path.join(self.folder, "s1.jsonl"), [
            line(now, type="text", text="Starting the API with two sub-agents."),
            line(now, type="tool_use", name="Agent", input={"description": "Build the API"}),
            line(now, type="tool_use", name="Edit", input={"file_path": "apps/api/queue.py"})])
        self.agent("a", "Build the API", None, [
            line(now, kind="user", model=None),
            line(now, model="claude-sonnet-5-5", type="tool_use", name="Bash",
                 input={"command": "pytest apps/api/tests/test_queue.py"})])
        self.agent("b", "Map the frontend", True, [line(now, model="claude-sonnet-5-5")])
        snap = gv.snapshot(self.goal, processes={"s1": 120})
        self.assertEqual((snap["role"], snap["running"]), ("lead", 1))
        self.assertEqual(snap["main"]["action"], "Edit apps/api/queue.py")
        self.assertEqual(snap["main"]["said"], "Starting the API with two sub-agents.")
        self.assertEqual([a["description"] for a in snap["agents"]], ["Build the API", "Map the frontend"])
        self.assertEqual(gv.running_count(self.goal, processes={"s1": 120}), 2)
        self.assertEqual(gv.running_count(self.goal, processes={}), 0)
        journal = ["- D1 no tabs", "## Plan", "- [x] Backend", "- [ ] Frontend"]
        text = "\n".join(l for l, _ in gv.lines_for(self.goal, snap, journal, 100))
        for expected in ("round 2", "Running now", "● Lead", "opus", "Edit apps/api/queue.py",
                         "● Sub-agent: Build the API", "Bash: pytest apps/api/tests/test_queue.py",
                         "- D1 no tabs", "[building] ▸ syncing", "1 of 2 steps done · next: Frontend",
                         "✓ Backend", "· Frontend"):
            self.assertIn(expected, text)

    def test_a_sub_agent_of_a_paused_goal_was_cut_off(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(now)])
        self.agent("a", "Task panel", None, [line(now, model="claude-sonnet-5-5")])
        paused = dict(self.goal, status="paused")
        snap = gv.snapshot(paused, processes={})
        self.assertEqual((snap["running"], snap["agents"][0]["cut"]), (0, True))
        self.assertEqual(gv.running_count(paused, processes={}), 0)
        text = "\n".join(l for l, _ in gv.lines_for(paused, snap, [], 100))
        self.assertIn("Running now\n  nothing — round 2", text)

    def test_a_sub_agent_quiet_for_long_is_not_running_but_its_call_is(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(old)])
        path = os.path.join(self.folder, "s1", "subagents", "agent-a.jsonl")
        self.agent("a", "Stuck", None, [line(old)])
        os.utime(path, (time.time() - 3600, time.time() - 3600))
        self.assertEqual(gv.snapshot(self.goal, processes={"s1": 60})["running"], 0)
        self.assertEqual(gv.running_count(self.goal, processes={"s1": 60}), 1)

    def test_a_call_other_than_the_lead(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write(os.path.join(self.folder, "c1.jsonl"), [line(now, model="claude-fable-5-1")])
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(now)])
        os.utime(os.path.join(self.folder, "s1.jsonl"), (time.time() - 60, time.time() - 60))
        self.assertEqual(gv.snapshot(self.goal)["role"], "call")

    def test_every_agent_running_is_listed_with_what_it_does(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state = os.path.join(self.base, "state")
        os.makedirs(state)
        self.goal.update(log=os.path.join(state, "goal.log"), round=4, session="s1",
                         status="working", doing="running 2 task(s)")
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(now)])
        task_folder = os.path.join(self.base, "projects", "task")
        os.makedirs(task_folder)
        self.write(os.path.join(task_folder, "t1.jsonl"), [line(now, model="claude-sonnet-5-5")])
        with open(os.path.join(state, "tasks.json"), "w") as f:
            json.dump({"round": 4, "tasks": [
                {"name": "Inbox screen", "kind": "code", "status": "running", "session": "t1",
                 "model": "claude-sonnet-5-5", "started": time.time() - 90},
                {"name": "Where is X", "kind": "explore", "status": "done", "session": "t2",
                 "started": time.time() - 60, "ended": time.time()}]}, f)
        snap = gv.snapshot(self.goal, processes={"t1": 90, "elsewhere": 30})
        text = "\n".join(l for l, _ in gv.lines_for(self.goal, snap, [], 120))
        self.assertIn("Lead             not running", text)
        self.assertIn("● Coder: Inbox screen", text)
        self.assertIn("sonnet", text)
        self.assertNotIn("elsewhere", text)
        self.assertIn("Finished this round\n  ✓ Explorer: Where is X", text)
        self.assertNotIn("░", gv.bar(1, 4))

    def test_a_cheap_model_says_why_an_agent_does_what_it_does_once_per_move(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [line(now, type="text", text="I check the step 3 screen."),
                 line(now, type="tool_use", name="Bash",
                      input={"command": "sed -n 1,80p a.tsx", "description": "Show the fit screen"})]
        actions, said = gv.recent(lines)
        self.assertEqual(actions, ["Bash: sed -n 1,80p a.tsx (Show the fit screen)"])
        self.assertIn("I check the step 3 screen.", gv.why_prompt("Lead", "", said, actions))
        asked = []
        ask, gv._ask_why = gv._ask_why, lambda key, prompt: (asked.append(key), gv._WHY[key].update(
            pending=False, text="checking the step 3 screen"))
        self.addCleanup(setattr, gv, "_ask_why", ask)
        self.addCleanup(gv._WHY.clear)
        gv.why("s9", 100, lambda: "p")
        deadline = time.time() + 2
        while gv._WHY["s9"].get("pending") and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(gv.why("s9", 100, lambda: "p"), "checking the step 3 screen")
        gv.why("s9", 101, lambda: "p")
        self.assertEqual(asked, ["s9"])

    def test_the_plan_is_the_checklist_under_its_heading(self):
        journal = ["# Journal", "- [x] not part of the plan", "## Plan", "1. [x] Backend",
                   "2. [ ] Migration 0030", "- [ ] Frontend", "### detail", "- [x] sub-step",
                   "## Status", "- [ ] not part either"]
        steps = gv.plan(journal)
        self.assertEqual((steps["done"], steps["total"], steps["next"]), (2, 4, "Migration 0030"))
        self.assertEqual(gv.plan(["- [x] a", "- [ ] b"])["total"], 2)
        self.assertIsNone(gv.plan(["## Status", "- DONE: everything"]))

    def test_the_stage_follows_what_the_goal_says_it_is_doing(self):
        for status, doing, expected in (("working", "round 2", "building"),
                                        ("checking", "syncing with main", "syncing"),
                                        ("checking", "waiting for CI: test", "CI"),
                                        ("checking", "fixing CI, try 1", "CI"),
                                        ("checking", "checking the branch against the ask", "checking"),
                                        ("done", "", "done")):
            self.assertEqual(gv.stage({"status": status, "doing": doing}), expected)
        self.assertEqual(gv.stage_line({"status": "checking", "doing": "fixing CI, try 1"}),
                         "analysis ▸ review ▸ approval ▸ building ▸ syncing ▸ [CI] ▸ checking ▸ done")
        self.assertEqual(gv.stage({"status": "waiting", "phase": "planning",
                                   "awaiting": {"kind": "plan"}}), "approval")
        self.assertEqual(gv.stage({"status": "working", "phase": "planning"}), "analysis")
        self.assertEqual(gv.stage({"status": "checking", "phase": "planning",
                                   "doing": "reviewing the acceptance criteria"}), "review")

    def test_the_acceptance_criteria_met_so_far(self):
        journal = ["## Acceptance criteria", "### Inbox", "- [x] Groups by day (prototype: inbox)",
                   "- [ ] Empty state (prototype: inbox)", "## Plan", "- [ ] Inbox"]
        met = gv.plan(journal, "acceptance criteria", anywhere=False)
        self.assertEqual((met["done"], met["total"]), (1, 2))
        self.assertIsNone(gv.plan(["## Plan", "- [ ] x"], "acceptance criteria", anywhere=False))
        text = "\n".join(l for l, _ in gv.lines_for(self.goal, None, journal, 100))
        self.assertIn("1 of 2 acceptance criteria", text)
        self.assertIn("· Empty state (prototype: inbox)", text)

    def test_no_call_yet(self):
        self.assertIsNone(gv.snapshot(dict(self.goal, worktree="/nothing")))
        self.assertIn("  nothing — round 2", [l for l, _ in gv.lines_for(self.goal, None, [], 80)])


if __name__ == "__main__":
    unittest.main()
