#!/usr/bin/env python3
#
# Unit tests for the TUI's and the daemon's pure functions — the queue and its
# commands, daemon health, finding runs nothing owns, and the rows each tab
# shows. The curses layer and the daemon loop are validated by running them.
#
#   python3 tests/test_pure.py

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daemon as dm  # noqa: E402
from tui import board_list_rows, board_rows, fit, matches, run_rows  # noqa: E402


class TestQueue(unittest.TestCase):
    def test_add_skips_what_is_already_queued_and_keeps_order(self):
        c = dm.empty_control()
        self.assertEqual(dm.queue_add(c, [{"gid": "1"}, {"gid": "2"}]), ["1", "2"])
        self.assertEqual(dm.queue_add(c, [{"gid": "2"}, {"gid": "3"}]), ["3"])
        self.assertEqual([q["gid"] for q in c["queue"]], ["1", "2", "3"])

    def test_remove(self):
        c = dm.empty_control()
        dm.queue_add(c, [{"gid": "1"}, {"gid": "2"}])
        dm.queue_remove(c, ["1"])
        self.assertEqual([q["gid"] for q in c["queue"]], ["2"])


class TestCommands(unittest.TestCase):
    def test_ids_grow_and_applied_ones_are_dropped(self):
        c = dm.empty_control()
        self.assertEqual(dm.add_command(c, "stop", "1"), 1)
        self.assertEqual(dm.add_command(c, "retry", "1"), 2)
        self.assertEqual(dm.add_command(c, "stop", "2", applied=2), 3)
        self.assertEqual([x["id"] for x in c["commands"]], [3])

    def test_an_id_is_never_reused_after_everything_was_applied(self):
        c = dm.empty_control()
        dm.add_command(c, "stop", "1")
        self.assertEqual(dm.add_command(c, "stop", "1", applied=5), 6)

    def test_pending_is_what_the_daemon_has_not_applied_in_order(self):
        c = {"commands": [{"id": 3, "op": "x", "gid": "a"}, {"id": 2, "op": "y", "gid": "b"},
                          {"id": 1, "op": "z", "gid": "c"}]}
        self.assertEqual([x["id"] for x in dm.pending_commands(c, 1)], [2, 3])


class TestDaemonHealth(unittest.TestCase):
    def test_states(self):
        self.assertEqual(dm.daemon_health(None, False, 100), "stopped")
        self.assertEqual(dm.daemon_health({"beat": 90}, False, 100), "crashed")
        self.assertEqual(dm.daemon_health({"beat": 90}, True, 100), "running")
        self.assertEqual(dm.daemon_health({"beat": 0}, True, 1000), "stale")


class TestUnmanaged(unittest.TestCase):
    def test_runs_nobody_here_launched_are_listed(self):
        self.assertEqual(dm.unmanaged([("HCI-1", 10), ("HCI-2", 20)], [10]), [("HCI-2", 20)])
        self.assertEqual(dm.unmanaged([], [10]), [])


class TestControlFile(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_changes_are_written_back_and_cortex_ignores_itself(self):
        with dm.control_file(self.root) as c:
            dm.queue_add(c, [{"gid": "1", "name": "CI1"}])
            c["sprint"] = {"gid": "9", "name": "Sprint"}
        c = dm.read_control(self.root)
        self.assertEqual(c["queue"][0]["name"], "CI1")
        self.assertEqual(c["sprint"]["gid"], "9")
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".cortex", ".gitignore")))

    def test_no_file_reads_as_empty(self):
        self.assertEqual(dm.read_control(self.root), dm.empty_control())


class TestMatches(unittest.TestCase):
    def test_every_word_anywhere_ignoring_case(self):
        self.assertTrue(matches("Humanus | Sprint 26/2", "sprint human"))
        self.assertFalse(matches("Humanus | Candidate Intake", "sprint"))
        self.assertTrue(matches("anything", ""))


class TestRunRows(unittest.TestCase):
    def test_queued_tasks_in_order_then_runs_nobody_owns(self):
        control = {"queue": [{"gid": "2", "board": "100", "name": "CI2"},
                             {"gid": "1", "board": "100", "name": "CI1"}]}
        data = {"me": {"gid": "42"},
                "tasks": {"1": {"key": "HCI-1", "name": "CI1", "completed": False,
                                "status": "Unassigned", "deps": []}},
                "records": {"1": {"phase": "running", "pid": 10, "log": "/l"}}}
        rows = run_rows(control, data, [("HCI-1", 10), ("HCI-7", 77)])
        self.assertEqual([r["kind"] for r in rows], ["task", "task", "orphan"])
        self.assertEqual(rows[0]["cols"][2], "queued — not read yet")
        self.assertEqual(rows[1]["cols"][:2], ["HCI-1", "CI1"])
        self.assertEqual(rows[1]["style"], "ok")
        self.assertIn("https://app.asana.com/0/100/1", rows[1]["links"])
        self.assertEqual(rows[2]["id"], 77)


class TestBoardRows(unittest.TestCase):
    SECTIONS = [
        {"gid": "s1", "name": "M1 :: Built", "tasks": [
            {"gid": "m", "name": "M1", "kind": "milestone"},
            {"gid": "1", "name": "CI1 enums", "kind": "task", "completed": True},
            {"gid": "2", "name": "CI2 DTOs", "kind": "task", "completed": False}]},
        {"gid": "s2", "name": "M2 :: Dev", "tasks": [
            {"gid": "3", "name": "Deploy", "kind": "task", "completed": False}]},
    ]

    def test_sections_then_their_tasks_without_the_milestone_anchor(self):
        rows = board_rows("100", self.SECTIONS, {"2"}, {}, "")
        self.assertEqual([(r["kind"], r["id"]) for r in rows],
                         [("section", "s1"), ("task", "1"), ("task", "2"),
                          ("section", "s2"), ("task", "3")])
        self.assertEqual(rows[0]["cols"][1], "1 open")
        self.assertIn("●", rows[2]["cols"][0])
        self.assertEqual(rows[1]["cols"][1], "done")

    def test_filter_keeps_matching_tasks_under_their_section(self):
        rows = board_rows("100", self.SECTIONS, set(), {}, "dto")
        self.assertEqual([r["id"] for r in rows], ["s1", "2"])

    def test_filter_on_a_section_name_keeps_all_of_it(self):
        rows = board_rows("100", self.SECTIONS, set(), {}, "m2")
        self.assertEqual([r["id"] for r in rows], ["s2", "3"])

    def test_a_task_shows_its_run_phase(self):
        rows = board_rows("100", self.SECTIONS, {"2"}, {"2": {"phase": "pr_open"}}, "dto")
        self.assertEqual(rows[1]["cols"][1], "pr_open")


class TestBoardListRows(unittest.TestCase):
    def test_marks_the_sprint_and_filters(self):
        boards = [{"gid": "1", "name": "Humanus | Candidate Intake"},
                  {"gid": "2", "name": "Humanus | Sprint 26/2"}]
        rows = board_list_rows(boards, "", {"gid": "2"})
        self.assertEqual(rows[1]["cols"][1], "← sprint")
        self.assertEqual([r["id"] for r in board_list_rows(boards, "intake", None)], ["1"])


class TestFit(unittest.TestCase):
    def test_four_columns_all_show(self):
        line = fit(["/repos/humanus-mono", "running", "pid 42", "2 live run(s)"], 120)
        for part in ("humanus-mono", "running", "pid 42", "2 live run(s)"):
            self.assertIn(part, line)

    def test_never_wider_than_the_screen(self):
        line = fit(["HCI-24", "x" * 80, "status " * 20], 60)
        self.assertLessEqual(len(line), 59)
        self.assertIn("…", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
