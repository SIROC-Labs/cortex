import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("cortex_queue", os.path.join(HERE, "queue.py"))
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

    def test_a_milestone_queues_its_open_subtasks(self):
        self.assertEqual(q.queue_items(TASKS["9"], "77", SUBTASKS["9"]),
                         [{"gid": "10", "board": "77", "name": "ten"}])
        self.assertEqual(q.queue_items(TASKS["1"], "77"), [{"gid": "1", "board": "77", "name": "one"}])
        self.assertEqual(q.queue_items(TASKS["2"], "77"), [])


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

    def queued(self):
        return [(e["gid"], e.get("base"), e.get("checkpoint")) for e in
                q.dm.read_control(self.root)["queue"]]

    def test_add_queues_like_the_tui_into_its_branch(self):
        with q.dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        out = q.add(self.root, ["https://app.asana.com/0/0/1", "9", "2"])
        self.assertEqual(self.queued(), [("1", "feature/m1", None), ("10", "feature/m1", None)])
        self.assertIn("A-2 two: nothing to queue — it is complete", out)
        self.assertIn("into feature/m1", out)
        self.assertTrue(any("daemon is not running" in line for line in out))
        self.assertIn("already queued: one", q.add(self.root, ["1"]))

    def test_into_and_checkpoint(self):
        q.add(self.root, ["1"], branch="feature/x", checkpoint=True)
        self.assertEqual(self.queued(), [("1", "feature/x", True)])

    def test_remove(self):
        q.add(self.root, ["1"])
        self.assertEqual(q.remove(self.root, ["1", "5"])[:2], ["unqueued one", "not queued: 5"])
        self.assertEqual(self.queued(), [])

    def test_goal_starts_once(self):
        launched = []
        launch, q.gl.launch = q.gl.launch, lambda root, gid: launched.append(gid)
        self.addCleanup(setattr, q.gl, "launch", launch)
        q.goal(self.root, "9", branch="feature/m1")
        [g] = q.gl.list_goals(self.root)
        self.assertEqual((g["key"], g["base"], g["url"]),
                         ("A-9", "feature/m1", "https://app.asana.com/0/77/9"))
        self.assertEqual(launched, [g["id"]])
        self.assertIn("already the goal", q.goal(self.root, "9")[0])


if __name__ == "__main__":
    unittest.main()
