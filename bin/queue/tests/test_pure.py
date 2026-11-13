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


class TestPure(unittest.TestCase):
    def test_the_board_is_the_url_s_project_else_the_task_s(self):
        self.assertEqual(q.board_of(TASKS["1"], "https://app.asana.com/1/5/project/42/task/1"), "42")
        self.assertEqual(q.board_of(TASKS["1"], "https://app.asana.com/0/43/1"), "43")
        self.assertEqual(q.board_of(TASKS["1"], "https://app.asana.com/0/0/1"), "77")
        self.assertEqual(q.board_of(TASKS["1"], "1"), "77")
        self.assertIsNone(q.board_of({}, "1"))


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

    def test_add_starts_a_goal_per_ticket_into_the_queue_into_branch(self):
        launched = self.launched()
        with q.dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        out = q.add(self.root, ["https://app.asana.com/0/0/1", "9"])
        goals = {g["key"]: g for g in q.gl.list_goals(self.root)}
        self.assertEqual(sorted(goals), ["A-1", "A-9"])
        self.assertEqual({g["base"] for g in goals.values()}, {"feature/m1"})
        self.assertEqual(goals["A-9"]["url"], "https://app.asana.com/0/77/9")
        self.assertEqual(len(launched), 2)
        self.assertEqual(q.dm.read_control(self.root)["queue"], [])
        self.assertTrue(all(line.startswith("started the goal") for line in out))

    def test_a_milestone_is_one_goal_not_its_subtasks(self):
        self.launched()
        q.add(self.root, ["9"])
        self.assertEqual([g["key"] for g in q.gl.list_goals(self.root)], ["A-9"])

    def test_into_names_the_branch(self):
        self.launched()
        q.add(self.root, ["1"], branch="feature/x")
        self.assertEqual(q.gl.list_goals(self.root)[0]["base"], "feature/x")

    def test_a_ticket_that_is_already_a_goal_starts_nothing(self):
        launched = self.launched()
        q.add(self.root, ["9"])
        self.assertIn("already the goal", q.add(self.root, ["9"])[0])
        self.assertEqual(len(launched), 1)

    def test_undo_undoes_the_goal(self):
        self.launched()
        q.add(self.root, ["1"])
        undone, q.gl.undo = q.gl.undo, lambda root, gid: ["PR closed"]
        self.addCleanup(setattr, q.gl, "undo", undone)
        self.assertTrue(q.undo(self.root, ["1"])[0].endswith("undone — PR closed"))
        self.assertEqual(q.undo(self.root, ["5"]), ["5: no goal to undo"])

    def test_only_add_undo_and_list(self):
        for argv in (["remove", "1"], ["goal", "1"], ["add", "1", "--checkpoint"]):
            with self.assertRaises(SystemExit):
                q.main(["--repo", self.root] + argv)


if __name__ == "__main__":
    unittest.main()
