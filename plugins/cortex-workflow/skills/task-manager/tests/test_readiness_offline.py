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

    SPRINT = {"active_sprint": {"gid": "9", "name": "Humanus | Sprint 26/4", "due_on": "2099-01-01"}}
    EPIC = {"ref": "e1", "name": "E3 — Dev env", "kind": "milestone",
            "board": [{"project": "Humanus | Infra", "section": "Epics"},
                      {"project": "Humanus | Sprint 26/4", "section": "In Progress"}], "fields": {}}

    def member(self, dev_status="To Do"):
        return {"ref": "s1", "name": "E3.1", "status": "Unassigned", "board": [],
                "parent": {"ref": "e1", "name": "E3 — Dev env"},
                "fields": {"Dev Status": dev_status}, "task_id": "HGM-504"}

    def check_member(self, task, epic):
        args = ["check", "--offline", "--task-json", self.write("task.json", task),
                "--sprint-json", self.write("sprint.json", self.SPRINT)]
        if epic is not None:
            args += ["--milestone-json", self.write("epic.json", epic)]
        code, out, err = run(args, self.dir)
        self.assertEqual(code, 0, err)
        verdict = json.loads(out)
        return verdict, {c["name"]: c["result"] for c in verdict["checks"]}

    def test_member_ready_through_its_epic_without_estimate(self):
        verdict, names = self.check_member(self.member(), self.EPIC)
        self.assertTrue(verdict["ready"])
        self.assertEqual(names["active_sprint"], "pass")
        self.assertEqual(names["estimate"], "skip")
        self.assertEqual(verdict["milestone"], {"ref": "e1", "name": "E3 — Dev env"})

    def test_member_blocked_when_epic_not_in_sprint(self):
        epic = dict(self.EPIC, board=[{"project": "Humanus | Infra", "section": "Epics"}])
        verdict, names = self.check_member(self.member(), epic)
        self.assertFalse(verdict["ready"])
        self.assertEqual(names["active_sprint"], "fail")

    def test_member_in_progress_is_not_startable(self):
        verdict, names = self.check_member(self.member("In Progress"), self.EPIC)
        self.assertFalse(verdict["ready"])
        self.assertEqual(names["status"], "fail")

    def test_member_without_epic_projection_fails_sprint_check(self):
        verdict, names = self.check_member(self.member(), None)
        self.assertFalse(verdict["ready"])
        self.assertEqual(names["active_sprint"], "fail")

    def test_offline_without_task_json_exits_1(self):
        code, _, err = run(["check", "--offline"], self.dir)
        self.assertEqual(code, 1)
        self.assertIn("--task-json", err)


if __name__ == "__main__":
    unittest.main()
