import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
READINESS = os.path.join(HERE, "..", "scripts", "readiness.py")


def run(args, cwd):
    proc = subprocess.run([sys.executable, READINESS] + args, capture_output=True, text=True, cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


class ReadinessOfflineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, obj):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            json.dump(obj, f)
        return path

    def test_ready_task(self):
        task = self.write("task.json", {"ref": "1", "name": "t", "status": "Assigned",
                                        "board": [{"project": "ENG | Sprint 26.16", "section": "Backlog"}],
                                        "fields": {"Estimate": "1h"}, "task_id": "PD1-1"})
        sprint = self.write("sprint.json", {"active_sprint": {"gid": "9", "name": "ENG | Sprint 26.16", "due_on": "2099-01-01"}})
        code, out, err = run(["check", "--offline", "--provider", "asana", "--task-json", task, "--sprint-json", sprint], self.dir)
        self.assertEqual(code, 0, err)
        verdict = json.loads(out)
        self.assertTrue(verdict["ready"])
        names = {c["name"]: c["result"] for c in verdict["checks"]}
        self.assertEqual(names["task_key"], "pass")

    def test_not_in_sprint_and_no_sprint_file(self):
        task = self.write("task.json", {"ref": "1", "name": "t", "status": "Assigned", "board": [], "fields": {}})
        code, out, err = run(["check", "--offline", "--task-json", task], self.dir)
        self.assertEqual(code, 0, err)
        verdict = json.loads(out)
        self.assertFalse(verdict["ready"])
        names = {c["name"]: c["result"] for c in verdict["checks"]}
        self.assertEqual(names["active_sprint"], "fail")
        self.assertEqual(names["estimate"], "fail")

    def test_offline_without_task_json_exits_1(self):
        code, _, err = run(["check", "--offline"], self.dir)
        self.assertEqual(code, 1)
        self.assertIn("--task-json", err)


if __name__ == "__main__":
    unittest.main()
