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
        snap = gv.snapshot(self.goal)
        self.assertEqual((snap["role"], snap["running"]), ("lead", 1))
        self.assertEqual(snap["main"]["action"], "Edit apps/api/queue.py")
        self.assertEqual(snap["main"]["said"], "Starting the API with two sub-agents.")
        self.assertEqual([a["description"] for a in snap["agents"]], ["Build the API", "Map the frontend"])
        self.assertEqual(gv.running_count(self.goal), 1)
        journal = ["- D1 no tabs", "## Plan", "- [x] Backend", "- [ ] Frontend"]
        text = "\n".join(l for l, _ in gv.lines_for(self.goal, snap, journal, 100))
        for expected in ("round 2", "Lead · opus", "doing: Edit apps/api/queue.py",
                         "Sub-agents: 1 running, 1 finished", "● Build the API",
                         "Bash: pytest apps/api/tests/test_queue.py", "✓ Map the frontend",
                         "- D1 no tabs", "[building] ▸ syncing", "1 of 2 steps done · next: Frontend",
                         "✓ Backend", "· Frontend"):
            self.assertIn(expected, text)

    def test_a_sub_agent_of_a_paused_goal_was_cut_off(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(now)])
        self.agent("a", "Task panel", None, [line(now, model="claude-sonnet-5-5")])
        paused = dict(self.goal, status="paused")
        snap = gv.snapshot(paused)
        self.assertEqual((snap["running"], snap["agents"][0]["cut"]), (0, True))
        self.assertEqual(gv.running_count(paused), 0)
        text = "\n".join(l for l, _ in gv.lines_for(paused, snap, [], 100))
        self.assertIn("0 running, 0 finished, 1 cut off when the goal stopped", text)
        self.assertIn("✗ Task panel", text)

    def test_a_sub_agent_quiet_for_long_is_not_running(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(old)])
        path = os.path.join(self.folder, "s1", "subagents", "agent-a.jsonl")
        self.agent("a", "Stuck", None, [line(old)])
        os.utime(path, (time.time() - 3600, time.time() - 3600))
        self.assertEqual(gv.snapshot(self.goal)["running"], 0)
        self.assertEqual(gv.running_count(self.goal), 0)

    def test_a_call_other_than_the_lead(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.write(os.path.join(self.folder, "c1.jsonl"), [line(now, model="claude-fable-5-1")])
        self.write(os.path.join(self.folder, "s1.jsonl"), [line(now)])
        os.utime(os.path.join(self.folder, "s1.jsonl"), (time.time() - 60, time.time() - 60))
        self.assertEqual(gv.snapshot(self.goal)["role"], "call")

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
                         "building ▸ syncing ▸ [CI] ▸ checking ▸ done")

    def test_no_call_yet(self):
        self.assertIsNone(gv.snapshot(dict(self.goal, worktree="/nothing")))
        self.assertIn("No call has started yet.", [l for l, _ in gv.lines_for(self.goal, None, [], 80)])


if __name__ == "__main__":
    unittest.main()
