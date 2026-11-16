import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("conductor_queue", os.path.join(HERE, "queue.py"))
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)

TASKS = {
    "1": {"ref": "1", "task_id": "A-1", "name": "one", "kind": "task",
          "board": [{"project": "Board", "project_gid": "77"}]},
    "2": {"ref": "2", "task_id": "A-2", "name": "two", "kind": "task", "completed": True},
    "9": {"ref": "9", "task_id": "A-9", "name": "milestone", "kind": "milestone",
          "board": [{"project": "Board", "project_gid": "77"}]},
}
SUBTASKS = {"9": [{"ref": "10", "name": "ten"}, {"ref": "11", "name": "eleven", "completed": True}]}


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", self.root], check=True)
        asana = q.st.asana

        def fake(args, cwd):
            if args[:2] == ["ref", "parse"]:
                return args[2].rstrip("/").split("/")[-1]
            if args[:2] == ["task", "get"]:
                return TASKS[args[2]]
            if args[:2] == ["task", "subtasks"]:
                return SUBTASKS.get(args[2], [])
            raise AssertionError(args)
        q.st.asana = fake
        self.addCleanup(setattr, q.st, "asana", asana)

    def tearDown(self):
        shutil.rmtree(self.root)

    def launched(self):
        launched = []
        launch, q.gl.launch = q.gl.launch, lambda root, gid: launched.append(gid)
        self.addCleanup(setattr, q.gl, "launch", launch)
        return launched

    def test_add_starts_a_goal_on_the_prompt_into_the_queue_into_branch(self):
        launched = self.launched()
        with q.dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        out = q.add(self.root, "Fix the inbox badge\n\nIt counts read items too.")
        goals = q.gl.list_goals(self.root)
        self.assertEqual([g["name"] for g in goals], ["Fix the inbox badge"])
        self.assertEqual(goals[0]["base"], "feature/m1")
        self.assertIsNone(goals[0]["key"])
        self.assertEqual(len(launched), 1)
        self.assertTrue(out[0].startswith("started the goal goal-fix-the-inbox-badge"))

    def test_a_bare_ticket_link_names_the_goal_after_the_ticket(self):
        self.launched()
        q.add(self.root, "https://app.asana.com/0/77/9")
        goal = q.gl.list_goals(self.root)[0]
        self.assertEqual((goal["key"], goal["name"]), ("A-9", "milestone"))
        self.assertEqual(goal["prompt"], "https://app.asana.com/0/77/9")

    def test_files_are_copied_into_the_goal(self):
        self.launched()
        shot = os.path.join(self.root, "shot.png")
        with open(shot, "wb") as f:
            f.write(b"png")
        q.add(self.root, "Match the screenshot", [shot])
        goal = q.gl.list_goals(self.root)[0]
        self.assertEqual(goal["files"], ["inputs/shot.png"])
        with open(q.gl.Goal(self.root, goal["id"]).state.path("inputs/shot.png"), "rb") as f:
            self.assertEqual(f.read(), b"png")

    def test_into_names_the_branch(self):
        self.launched()
        q.add(self.root, "Do it", branch="feature/x")
        self.assertEqual(q.gl.list_goals(self.root)[0]["base"], "feature/x")

    def test_a_prompt_is_needed(self):
        with self.assertRaises(q.st.Failure):
            q.add(self.root, "  \n")

    def test_undo_undoes_the_goal(self):
        self.launched()
        q.add(self.root, "Do it")
        gid = q.gl.list_goals(self.root)[0]["id"]
        undone, q.gl.undo = q.gl.undo, lambda root, gid: ["PR closed"]
        self.addCleanup(setattr, q.gl, "undo", undone)
        self.assertTrue(q.undo(self.root, [gid])[0].endswith("undone — PR closed"))
        self.assertEqual(q.undo(self.root, ["goal-nope"]), ["goal-nope: no goal to undo"])

    def test_only_add_undo_and_list(self):
        for argv in (["remove", "1"], ["goal", "1"], ["add", "x", "--checkpoint"]):
            with self.assertRaises(SystemExit):
                q.main(["--repo", self.root] + argv)


if __name__ == "__main__":
    unittest.main()
