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
import tui  # noqa: E402
from tui import (  # noqa: E402
    NAV, App, board_list_rows, board_rows, decode_escape, decode_key, fit, matches, run_rows,
)


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


class TestDecodeEscape(unittest.TestCase):
    """Arrows must work whether the terminal sends CSI (`ESC [ B`) or SS3
    (`ESC O B`) — curses only decodes the one its terminfo names."""

    def test_arrows_in_both_forms(self):
        for final, name in (("A", "up"), ("B", "down"), ("C", "right"), ("D", "left")):
            self.assertEqual(decode_escape("[" + final), name)
            self.assertEqual(decode_escape("O" + final), name)

    def test_modified_arrows_still_move(self):
        self.assertEqual(decode_escape("[1;5B"), "down")

    def test_paging_home_end_and_shift_tab(self):
        self.assertEqual(decode_escape("[5~"), "pgup")
        self.assertEqual(decode_escape("[6~"), "pgdn")
        self.assertEqual(decode_escape("[H"), "home")
        self.assertEqual(decode_escape("[4~"), "end")
        self.assertEqual(decode_escape("[Z"), "btab")

    def test_bare_escape_and_alt_keys(self):
        self.assertEqual(decode_escape(""), "esc")
        self.assertEqual(decode_escape("2"), "alt-2")

    def test_unknown_sequences_mean_nothing(self):
        self.assertIsNone(decode_escape("[99~"))


class TestDecodeKey(unittest.TestCase):
    def test_control_keys(self):
        self.assertEqual([decode_key(c) for c in (14, 16, 6, 2, 4, 21, 9, 10, 127)],
                         ["ctrl-n", "ctrl-p", "ctrl-f", "ctrl-b", "ctrl-d", "ctrl-u",
                          "tab", "enter", "backspace"])

    def test_curses_keys_and_characters(self):
        import curses
        self.assertEqual(decode_key(curses.KEY_DOWN), "down")
        self.assertEqual(decode_key(curses.KEY_NPAGE), "pgdn")
        self.assertEqual(decode_key(ord("j")), "j")
        self.assertIsNone(decode_key(curses.KEY_RESIZE))


class TestNav(unittest.TestCase):
    def test_vi_emacs_and_arrows_agree(self):
        for keys, action in ((("down", "j", "ctrl-n"), "down"), (("up", "k", "ctrl-p"), "up"),
                             (("pgdn", "ctrl-f"), "pgdn"), (("pgup", "ctrl-b"), "pgup"),
                             (("right", "l", "enter"), "open"),
                             (("left", "h", "esc", "backspace"), "back")):
            for k in keys:
                self.assertEqual(NAV[k], action, k)

    def test_numbers_and_alt_numbers_pick_a_tab(self):
        for n in "1234":
            self.assertEqual(NAV[n], "tab")
            self.assertEqual(NAV["alt-" + n], "tab")


class TestAppKeys(unittest.TestCase):
    """Key handling without a terminal: the app is driven by tokens."""

    BOARDS = [{"gid": "1", "name": "Alpha"}, {"gid": "2", "name": "Beta"},
              {"gid": "3", "name": "Gamma"}]
    SECTIONS = [{"gid": "s", "name": "M1", "tasks": [
        {"gid": "t1", "name": "one", "kind": "task"}, {"gid": "t2", "name": "two", "kind": "task"}]}]

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.app = App(self.root, [])
        self.app.boards = list(self.BOARDS)
        self.app.sections = {"2": self.SECTIONS}

    def press(self, *keys):
        for k in keys:
            self.app.key(k, self.app.view())

    def test_a_number_goes_straight_to_its_tab(self):
        self.press("3")
        self.assertEqual(tui.TABS[self.app.tab], "Sprint")
        self.press("alt-1")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")

    def test_tab_and_shift_tab_cycle(self):
        self.press("tab", "tab")
        self.assertEqual(self.app.tab, 2)
        self.press("btab", "btab", "btab")
        self.assertEqual(self.app.tab, 3)

    def test_moving_in_every_style_and_clamping(self):
        self.press("2", "down", "j", "ctrl-n")
        self.assertEqual(self.app.cursor["Boards"], 2)
        self.press("up", "ctrl-p", "k", "k")
        self.assertEqual(self.app.cursor["Boards"], 0)
        self.press("G")
        self.assertEqual(self.app.cursor["Boards"], 2)
        self.press("g")
        self.assertEqual(self.app.cursor["Boards"], 0)
        self.press("ctrl-f")
        self.assertEqual(self.app.cursor["Boards"], 2)

    def test_into_a_board_and_back_out_keeps_the_place(self):
        self.press("2", "down", "right")
        self.assertEqual(self.app.board, ("2", "Beta"))
        self.press("down")
        self.assertEqual(self.app.cursor["board:2"], 1)
        self.press("left")
        self.assertIsNone(self.app.board)
        self.assertEqual(self.app.cursor["Boards"], 1)
        for out in ("esc", "h", "backspace"):
            self.press("enter", out)
            self.assertIsNone(self.app.board, out)

    def test_the_current_tabs_number_takes_it_to_its_top(self):
        self.press("2", "down", "enter")
        self.assertIsNotNone(self.app.board)
        self.press("2")
        self.assertIsNone(self.app.board)

    def test_back_clears_a_filter_before_leaving_the_board(self):
        self.press("2", "down", "enter", "/", "t", "w", "enter")
        self.assertEqual(self.app.query["board:2"], "tw")
        self.press("esc")
        self.assertEqual(self.app.query["board:2"], "")
        self.assertIsNotNone(self.app.board)
        self.press("esc")
        self.assertIsNone(self.app.board)

    def test_typing_takes_letters_that_are_otherwise_keys(self):
        self.press("2", "/", "j", "q", "2")
        self.assertEqual(self.app.query["Boards"], "jq2")
        self.assertEqual(tui.TABS[self.app.tab], "Boards")
        self.press("esc")
        self.assertEqual(self.app.query["Boards"], "")
        self.assertFalse(self.app.typing)

    def test_right_does_not_pick_the_sprint_enter_does(self):
        self.press("3", "down", "right")
        self.assertIsNone(self.app.control.get("sprint"))
        self.press("enter")
        self.assertEqual(self.app.control["sprint"]["gid"], "2")

    def test_q_quits_and_help_closes_on_any_key(self):
        self.press("?")
        self.assertTrue(self.app.help)
        self.press("j")
        self.assertFalse(self.app.help)
        self.assertFalse(self.app.key("q", []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
