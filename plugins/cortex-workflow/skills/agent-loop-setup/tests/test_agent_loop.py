import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "agent_loop.py")

CACHE = {
    "provider": "asana", "workspace": "w1",
    "board": {"ref": "b3", "name": "ENG | [AGENT] Sprint 26/3"},
    "columns": {"queue": "c1", "in_progress": "c2", "blocked": "c3", "in_review": "c4", "ready": "c6",
                "done": "c5"},
    "column_names": {"queue": "Backlog", "in_progress": "In Progress", "blocked": "Blocked",
                     "in_review": "Pending PR Review", "ready": "Ready", "done": "Completed"},
    "rotation": {"pattern": r"^ENG \| \[AGENT\] Sprint (\d+)/(\d+)$"},
    "repos_root": "/tmp/repos",
}


class AgentLoopCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def run_cmd(self, args, stdin=None):
        env = dict(os.environ, HOME=self.home)
        proc = subprocess.run([sys.executable, SCRIPT] + args, input=stdin, capture_output=True,
                              text=True, env=env, cwd=self.home)
        return proc.returncode, proc.stdout, proc.stderr

    def write_json(self, name, obj):
        path = os.path.join(self.home, name)
        with open(path, "w") as f:
            json.dump(obj, f)
        return path

    def seed(self, cache=CACHE):
        code, _, err = self.run_cmd(["write", "asana", "--from-json", "-"], stdin=json.dumps(cache))
        self.assertEqual(code, 0, err)


class KeyReadWriteTest(AgentLoopCase):
    def test_key_is_provider(self):
        code, out, _ = self.run_cmd(["key", "asana"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "asana")

    def test_read_missing_exits_4(self):
        code, _, err = self.run_cmd(["read", "asana"])
        self.assertEqual(code, 4)
        self.assertIn("agent-loop-setup", err)

    def test_write_then_read_roundtrip(self):
        self.seed()
        code, out, _ = self.run_cmd(["read", "asana"])
        self.assertEqual(code, 0)
        cache = json.loads(out)
        self.assertEqual(cache["board"]["ref"], "b3")
        self.assertIn("resolved_at", cache)
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".cortex", "agent-loop", "asana.json")))

    def test_write_missing_role_exits_1(self):
        bad = dict(CACHE, columns={"queue": "c1"})
        code, _, err = self.run_cmd(["write", "asana", "--from-json", "-"], stdin=json.dumps(bad))
        self.assertEqual(code, 1)
        self.assertIn("in_progress", err)

    def test_write_missing_ready_exits_1(self):
        columns = {k: v for k, v in CACHE["columns"].items() if k != "ready"}
        code, _, err = self.run_cmd(["write", "asana", "--from-json", "-"], stdin=json.dumps(dict(CACHE, columns=columns)))
        self.assertEqual(code, 1)
        self.assertIn("columns.ready", err)

    def test_write_duplicate_column_exits_1(self):
        bad = dict(CACHE, columns=dict(CACHE["columns"], done="c4"))
        code, _, err = self.run_cmd(["write", "asana", "--from-json", "-"], stdin=json.dumps(bad))
        self.assertEqual(code, 1)
        self.assertIn("distinct", err)


class RotateTest(AgentLoopCase):
    BOARDS = [
        {"ref": "b3", "name": "ENG | [AGENT] Sprint 26/3", "completed": False},
        {"ref": "b10", "name": "ENG | [AGENT] Sprint 26/10", "completed": False},
        {"ref": "b9", "name": "ENG | [AGENT] Sprint 26/9", "completed": False},
        {"ref": "x", "name": "ENG | Sprint 26.16", "completed": False},
    ]

    def test_numeric_groups_pick_26_10_over_26_9(self):
        self.seed()
        path = self.write_json("boards.json", self.BOARDS)
        code, out, err = self.run_cmd(["rotate", "asana", "--from-json", path])
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertTrue(result["rotate"])
        self.assertEqual(result["board"]["ref"], "b10")
        self.assertEqual(result["previous"]["ref"], "b3")

    def test_cached_board_is_newest_no_rotation(self):
        self.seed()
        path = self.write_json("boards.json", [self.BOARDS[0], self.BOARDS[3]])
        code, out, _ = self.run_cmd(["rotate", "asana", "--from-json", path])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["rotate"])

    def test_no_pattern_never_rotates(self):
        self.seed(dict(CACHE, rotation=None))
        path = self.write_json("boards.json", self.BOARDS)
        code, out, _ = self.run_cmd(["rotate", "asana", "--from-json", path])
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertFalse(result["rotate"])
        self.assertEqual(result["board"]["ref"], "b3")

    def test_no_match_at_all_exits_2(self):
        self.seed()
        path = self.write_json("boards.json", [self.BOARDS[3]])
        code, _, _ = self.run_cmd(["rotate", "asana", "--from-json", path])
        self.assertEqual(code, 2)


class OrderTest(AgentLoopCase):
    def test_priority_then_native_index_unset_last(self):
        payload = {"tasks": [
            {"ref": "a", "name": "A", "index": 0, "priority": None},
            {"ref": "b", "name": "B", "index": 1, "priority": "P2"},
            {"ref": "c", "name": "C", "index": 2, "priority": "P0"},
            {"ref": "d", "name": "D", "index": 3, "priority": "p2"},
        ], "priority_order": ["P0", "P1", "P2", "P3", "P4"]}
        code, out, err = self.run_cmd(["order", "--from-json", "-"], stdin=json.dumps(payload))
        self.assertEqual(code, 0, err)
        self.assertEqual([t["ref"] for t in json.loads(out)], ["c", "b", "d", "a"])

    def test_unknown_priority_value_sorts_last(self):
        payload = {"tasks": [{"ref": "a", "name": "A", "index": 0, "priority": "Urgent"},
                             {"ref": "b", "name": "B", "index": 1, "priority": "P4"}],
                   "priority_order": ["P0", "P4"]}
        code, out, _ = self.run_cmd(["order", "--from-json", "-"], stdin=json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual([t["ref"] for t in json.loads(out)], ["b", "a"])


class GateTest(AgentLoopCase):
    def payload(self, blockers):
        return {"blockers": blockers, "board": "b3", "columns": CACHE["columns"],
                "column_names": CACHE["column_names"]}

    def gate(self, blockers):
        code, out, err = self.run_cmd(["gate", "--from-json", "-"], stdin=json.dumps(self.payload(blockers)))
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_no_blockers_passes(self):
        self.assertTrue(self.gate([])["pass"])

    def test_completed_passes(self):
        r = self.gate([{"ref": "x", "name": "X", "completed": True, "memberships": []}])
        self.assertTrue(r["pass"])

    def test_in_review_by_ref_passes(self):
        r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": [
            {"board": {"ref": "b3", "name": "agent"}, "column": {"ref": "c4", "name": "Pending PR Review"}}]}])
        self.assertTrue(r["pass"])

    def test_ready_by_ref_passes(self):
        r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": [
            {"board": {"ref": "b3", "name": "agent"}, "column": {"ref": "c6", "name": "Ready"}}]}])
        self.assertTrue(r["pass"])

    def test_done_by_name_on_other_board_passes(self):
        r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": [
            {"board": {"ref": "team", "name": "ENG | Sprint 26.16"}, "column": {"ref": "zz", "name": "Completed"}}]}])
        self.assertTrue(r["pass"])

    def test_queue_in_progress_blocked_unknown_and_no_board_block(self):
        for column in ({"ref": "c1", "name": "Backlog"}, {"ref": "c2", "name": "In Progress"},
                       {"ref": "c3", "name": "Blocked"}, {"ref": "c9", "name": "Mystery"}):
            r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": [
                {"board": {"ref": "b3", "name": "agent"}, "column": column}]}])
            self.assertFalse(r["pass"], column)
            self.assertEqual(r["blocking"][0]["ref"], "x")
        r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": []}])
        self.assertFalse(r["pass"])
        self.assertIn("no board", r["blocking"][0]["reason"])


class LastRunTest(AgentLoopCase):
    def test_start_then_write(self):
        self.seed()
        code, _, err = self.run_cmd(["last-run", "asana", "start"])
        self.assertEqual(code, 0, err)
        code, out, err = self.run_cmd(["last-run", "asana", "write", "in_review", "--task", "t1", "--detail", "PR #5"])
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.home, ".cortex", "agent-loop", "asana.last-run.json")) as f:
            rec = json.load(f)
        self.assertEqual(rec["outcome"], "in_review")
        self.assertEqual(rec["task"], "t1")
        self.assertTrue(rec["started"])
        self.assertTrue(rec["ended"])


if __name__ == "__main__":
    unittest.main()
