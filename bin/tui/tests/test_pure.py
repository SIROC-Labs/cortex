#!/usr/bin/env python3
#
# Unit tests for the TUI's pure functions — the rows each tab shows, the goals and
# what they wait on, and the keys. The curses layer is validated by running it.
#
#   python3 tests/test_pure.py

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lib"))

import cache  # noqa: E402
import control as dm  # noqa: E402
import tui  # noqa: E402
from tui import palette_matches  # noqa: E402,F401
from tui import (  # noqa: E402
    NAV, App, answer_template, board_list_rows, board_rows, branch_rows, decode_escape,
    decode_key, fit, log_line, matches, parse_answer, parse_ls_remote, setup_rows,
    valid_branch_name, wait_lines, wait_summary,
)
import core as st  # noqa: E402


class TestControlFile(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_no_file_reads_as_empty(self):
        self.assertEqual(dm.read_control(self.root), dm.empty_control())


class TestMatches(unittest.TestCase):
    def test_every_word_anywhere_ignoring_case(self):
        self.assertTrue(matches("Humanus | Sprint 26/2", "sprint human"))
        self.assertFalse(matches("Humanus | Candidate Intake", "sprint"))
        self.assertTrue(matches("anything", ""))


class TestGoalRows(unittest.TestCase):
    def goal(self, **fields):
        return dict({"id": "goal-1027-1432-dark-mode", "key": "A-7", "name": "Add dark mode",
                     "status": "working", "round": 3, "alive": True, "pid": 9,
                     "log": "/r/goal.log", "pr_url": "https://github.com/o/r/pull/1",
                     "limits": [{"name": "session", "used": 61}, {"name": "week", "used": 22}]},
                    **fields)

    def test_a_working_goal_says_its_round_and_the_usage(self):
        [row] = tui.goal_rows([self.goal()])
        self.assertEqual(row["cols"], ["goal", "A-7 Add dark mode", "working · round 3 · usage 61%"])
        self.assertEqual((row["kind"], row["id"], row["style"]), ("goal", "goal:goal-1027-1432-dark-mode", "ok"))

    def test_a_checking_goal_says_what_it_is_doing_and_how_far_its_plan_is(self):
        [row] = tui.goal_rows([self.goal(status="checking", doing="fixing CI, try 1",
                                         plan={"done": 5, "total": 5}, limits=[])])
        self.assertEqual(row["cols"][2], "fixing CI, try 1 · round 3 · plan 5/5")

    def test_a_goal_waiting_on_you_comes_first_and_says_why(self):
        waits = {"goal:b": {"kind": "questions", "questions": [{"q": "Which theme?"}]}}
        rows = tui.goal_rows([self.goal(id="a"), self.goal(id="b")], waits)
        self.assertEqual([r["goal"] for r in rows], ["b", "a"])
        self.assertIn("has questions for you: Which theme?", rows[0]["cols"][2])

    def test_a_goal_s_parts_follow_it_indented_and_move_with_it(self):
        goals = [self.goal(id="a"), self.goal(id="b", status="parts", doing="parts: 1 of 2 done · building Inbox"),
                 self.goal(id="b--api", parent="b", part="API", status="done", alive=False),
                 self.goal(id="b--inbox", parent="b", part="Inbox")]
        waits = {"goal:b--inbox": {"kind": "questions", "questions": [{"q": "Which tab?"}]}}
        rows = tui.goal_rows(goals, waits)
        self.assertEqual([r["goal"] for r in rows], ["b", "b--api", "b--inbox", "a"])
        self.assertEqual(rows[0]["cols"][2], "parts: 1 of 2 done · building Inbox · usage 61%")
        self.assertEqual(rows[1]["cols"][:2], ["part", "  └ API"])
        self.assertEqual(rows[1]["cols"][2], "done — merged into the goal's branch")
        self.assertEqual([r["goal"] for r in tui.goal_rows(goals, hide_done=True)], ["a", "b", "b--inbox"])

    def test_a_goal_whose_process_died_can_carry_on(self):
        [row] = tui.goal_rows([self.goal(alive=False)])
        self.assertEqual((row["cols"][2], row["style"]), ("stopped unexpectedly — r carries on", "bad"))

    def test_done_goals_hide_with_done_tasks_once_merged(self):
        goals = [self.goal(status="done", phase="merged", alive=False), self.goal(id="b"),
                 self.goal(id="c", status="done", alive=False, pr_url="https://github.com/o/r/pull/1")]
        rows = tui.goal_rows(goals, hide_done=True)
        self.assertEqual([r["goal"] for r in rows], ["b", "c"])
        self.assertIn("r watches it", rows[1]["cols"][2])
        review = tui.goal_status(self.goal(status="review", alive=True))[0]
        self.assertTrue(review.startswith("ready to merge"))

    def test_a_goal_s_questions_are_waits(self):
        g = self.goal(awaiting={"kind": "problem", "asked_at": "t", "headline": "push refused"})
        waits = tui.goal_waits([g])
        self.assertEqual(waits["goal:%s" % g["id"]]["key"], g["id"])
        rows = tui.goal_rows([g], waits)
        self.assertEqual(rows[0]["kind"], "goal")
        self.assertTrue(rows[0]["cols"][2].startswith("⚑ push refused"))


class TestBoardRows(unittest.TestCase):
    SECTIONS = [
        {"gid": "s1", "name": "M1 :: Built", "tasks": [
            {"gid": "m", "name": "M1", "kind": "milestone"},
            {"gid": "1", "name": "CI1 enums", "kind": "task", "completed": True},
            {"gid": "2", "name": "CI2 DTOs", "kind": "task", "completed": False}]},
        {"gid": "s2", "name": "M2 :: Dev", "tasks": [
            {"gid": "3", "name": "Deploy", "kind": "task", "completed": False}]},
    ]

    def test_sections_then_their_tasks(self):
        rows = board_rows("100", self.SECTIONS, "")
        self.assertEqual([(r["kind"], r["id"]) for r in rows],
                         [("section", "s1"), ("task", "m"), ("task", "1"), ("task", "2"),
                          ("section", "s2"), ("task", "3")])
        self.assertEqual(rows[0]["cols"][1], "1 open")
        self.assertEqual(rows[2]["cols"][1], "done")

    def test_a_task_key_comes_before_its_name_faintly_and_can_be_filtered_on(self):
        sections = [{"gid": "s", "name": "S", "tasks": [
            {"gid": "1", "name": "Login", "key": "HRT1-7", "kind": "task"},
            {"gid": "2", "name": "Logout", "kind": "task"}]}]
        rows = board_rows("100", sections, "")
        self.assertEqual(rows[1]["cols"][0], "    HRT1-7 Login")
        self.assertEqual(rows[1]["cols"][0][slice(rows[1]["faint"][0], sum(rows[1]["faint"]))], "HRT1-7")
        self.assertEqual(rows[2]["cols"][0], "    Logout")
        self.assertIsNone(rows[2]["faint"])
        self.assertEqual([r["id"] for r in board_rows("100", sections, "hrt1-7")], ["s", "1"])

    def test_a_milestone_shows_marked(self):
        rows = board_rows("100", self.SECTIONS, "")
        self.assertTrue(rows[1]["milestone"])
        self.assertIn("◈", rows[1]["cols"][0])

    def test_filter_keeps_matching_tasks_under_their_section(self):
        rows = board_rows("100", self.SECTIONS, "dto")
        self.assertEqual([r["id"] for r in rows], ["s1", "2"])

    def test_filter_on_a_section_name_keeps_all_of_it(self):
        rows = board_rows("100", self.SECTIONS, "m2")
        self.assertEqual([r["id"] for r in rows], ["s2", "3"])

    def test_hiding_done_leaves_out_completed_tasks_and_emptied_sections(self):
        sections = self.SECTIONS + [{"gid": "s3", "name": "Old", "tasks": [
            {"gid": "9", "name": "Finished", "kind": "task", "completed": True}]}]
        rows = board_rows("100", sections, "", hide_done=True)
        self.assertEqual([r["id"] for r in rows], ["s1", "m", "2", "s2", "3"])

    def test_a_task_says_how_many_subtasks_it_has_and_shows_them_when_open(self):
        sections = [{"gid": "s", "name": "M", "tasks": [
            {"gid": "1", "name": "Parent", "kind": "task", "subtasks": 2}]}]
        rows = board_rows("100", sections, "")
        self.assertEqual(rows[1]["cols"][1], "▸ 2 subtasks")
        rows = board_rows("100", sections, "", subtasks={"1": None})
        self.assertEqual(rows[2]["kind"], "loading")
        rows = board_rows("100", sections, "", subtasks={"1": [
            {"gid": "a", "name": "first"}, {"gid": "b", "name": "second", "completed": True}]})
        self.assertIn("▾ 2 subtasks", rows[1]["cols"][1])
        self.assertEqual([(r["id"], r.get("parent")) for r in rows[2:]], [("a", "1"), ("b", "1")])
        self.assertEqual(rows[3]["cols"][1], "done")


class TestBoardListRows(unittest.TestCase):
    def test_filters(self):
        boards = [{"gid": "1", "name": "Humanus | Candidate Intake"},
                  {"gid": "2", "name": "Humanus | Sprint 26/2"}]
        self.assertEqual([r["id"] for r in board_list_rows(boards, "")], ["1", "2"])
        self.assertEqual([r["id"] for r in board_list_rows(boards, "intake")], ["1"])


class TestFit(unittest.TestCase):
    def test_four_columns_all_show(self):
        line = fit(["/repos/humanus-mono", "running", "pid 42", "2 live run(s)"], 120)
        for part in ("humanus-mono", "running", "pid 42", "2 live run(s)"):
            self.assertIn(part, line)

    def test_never_wider_than_the_screen(self):
        line = fit(["HCI-24", "x" * 80, "status " * 20], 60)
        self.assertLessEqual(len(line), 59)
        self.assertIn("…", line)


def isolate_cache(test):
    saved = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp()

    def restore():
        shutil.rmtree(os.environ["XDG_CACHE_HOME"], True)
        if saved is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = saved
    test.addCleanup(restore)


class TestCache(unittest.TestCase):
    def setUp(self):
        isolate_cache(self)

    def test_lives_under_xdg_cache_home(self):
        self.assertTrue(cache.cache_dir().startswith(os.environ["XDG_CACHE_HOME"]))
        self.assertTrue(cache.cache_dir().endswith(os.path.join("cortex", "asana")))

    def test_roundtrip_with_its_age(self):
        c = cache.Cache()
        c.put("sections-1", [{"gid": "s"}], at=100.0)
        self.assertEqual(c.get("sections-1"), ([{"gid": "s"}], 100.0))

    def test_a_missing_or_broken_copy_is_no_copy(self):
        c = cache.Cache()
        self.assertEqual(c.get("nope"), (None, None))
        os.makedirs(c.root, exist_ok=True)
        with open(c.path("bad"), "w") as f:
            f.write("{not json")
        self.assertEqual(c.get("bad"), (None, None))


class TestAge(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(cache.age_label(None, 0), "not loaded yet")
        self.assertEqual(cache.age_label(100, 105), "updated just now")
        self.assertEqual(cache.age_label(100, 130), "updated 30s ago")
        self.assertEqual(cache.age_label(0, 300), "updated 5m ago")
        self.assertEqual(cache.age_label(0, 7200), "updated 2h ago")

    def test_staleness(self):
        self.assertTrue(cache.is_stale(None, 0, 60))
        self.assertFalse(cache.is_stale(100, 150, 60))
        self.assertTrue(cache.is_stale(100, 161, 60))


class TestLoader(unittest.TestCase):
    def wait(self, loader, key):
        for _ in range(200):
            done = loader.take(key)
            if done:
                return done
            tui.time.sleep(0.01)
        self.fail("load never finished")

    def test_one_load_per_key_and_its_result_once(self):
        import threading
        gate = threading.Event()
        loader = cache.Loader()
        self.assertTrue(loader.start("k", "label", lambda: gate.wait() and "data"))
        self.assertFalse(loader.start("k", "label", lambda: "again"))
        self.assertTrue(loader.busy("k"))
        gate.set()
        self.assertEqual(self.wait(loader, "k"), ("data", None))
        self.assertIsNone(loader.take("k"))
        self.assertFalse(loader.busy("k"))

    def test_a_failure_is_reported_not_raised(self):
        loader = cache.Loader()
        loader.start("k", "label", lambda: 1 / 0)
        data, error = self.wait(loader, "k")
        self.assertIsNone(data)
        self.assertIn("division", error)


class TestStaleWhileRevalidate(unittest.TestCase):
    SECTIONS = [{"gid": "s", "name": "M1", "tasks": [
        {"gid": "t1", "name": "one", "kind": "task", "completed": False}]}]

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        isolate_cache(self)
        self.fetches = []
        self.app = App(self.root)
        self.app.boards = [{"gid": "1", "name": "Alpha"}]
        self.app.boards_at = tui.time.time()
        self.app.fetch_sections = lambda gid: self.fetches.append(gid) or self.SECTIONS

    def settle(self):
        for _ in range(200):
            self.app.sync()
            if not self.app.loader.busy():
                self.app.sync()
                return
            tui.time.sleep(0.01)

    def open_board(self):
        self.app.key("2", self.app.view())
        self.app.key("enter", self.app.view())

    def test_a_fresh_copy_is_shown_and_not_refetched(self):
        self.app.cache.put("sections-1", self.SECTIONS)
        self.open_board()
        self.settle()
        self.assertEqual(self.fetches, [])
        self.assertEqual(self.app.sections["1"], self.SECTIONS)

    def test_a_stale_copy_is_shown_at_once_and_refreshed_behind_it(self):
        old = [{"gid": "s", "name": "old", "tasks": []}]
        self.app.cache.put("sections-1", old, at=tui.time.time() - 3600)
        self.open_board()
        self.assertEqual(self.app.sections["1"], old)
        self.settle()
        self.assertEqual(self.fetches, ["1"])
        self.assertEqual(self.app.sections["1"], self.SECTIONS)

    def test_no_copy_loads_in_the_background(self):
        self.open_board()
        self.assertIsNone(self.app.sections["1"])
        self.settle()
        self.assertEqual(self.app.sections["1"], self.SECTIONS)

    def test_R_refetches_even_a_fresh_copy(self):
        self.app.cache.put("sections-1", self.SECTIONS)
        self.open_board()
        self.app.key("R", self.app.view())
        self.settle()
        self.assertEqual(self.fetches, ["1"])


class TestScrollTop(unittest.TestCase):
    def test_moving_up_from_the_bottom_does_not_scroll(self):
        top = tui.scroll_top(0, 12, 10, 30)
        self.assertEqual(top, 3)
        self.assertEqual(tui.scroll_top(top, 11, 10, 30), 3)
        self.assertEqual(tui.scroll_top(top, 3, 10, 30), 3)

    def test_it_scrolls_only_when_the_cursor_leaves_the_window(self):
        self.assertEqual(tui.scroll_top(3, 2, 10, 30), 2)
        self.assertEqual(tui.scroll_top(3, 13, 10, 30), 4)

    def test_a_shrunk_list_never_leaves_blank_rows_below(self):
        self.assertEqual(tui.scroll_top(20, 5, 10, 8), 0)
        self.assertEqual(tui.scroll_top(20, 25, 10, 26), 16)


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
        self.assertEqual([decode_key(c) for c in (14, 16, 6, 2, 4, 21, 9, 10, 127, 1, 5, 11, 23)],
                         ["ctrl-n", "ctrl-p", "ctrl-f", "ctrl-b", "ctrl-d", "ctrl-u",
                          "tab", "enter", "backspace", "ctrl-a", "ctrl-e", "ctrl-k", "ctrl-w"])

    def test_curses_keys_and_characters(self):
        import curses
        self.assertEqual(decode_key(curses.KEY_DOWN), "down")
        self.assertEqual(decode_key(curses.KEY_NPAGE), "pgdn")
        self.assertEqual(decode_key(ord("j")), "j")
        self.assertIsNone(decode_key(curses.KEY_RESIZE))


class TestNav(unittest.TestCase):
    def test_vi_emacs_and_arrows_agree(self):
        for keys, action in ((("down", "j", "ctrl-n"), "down"), (("up", "k", "ctrl-p"), "up"),
                             (("pgdn", "alt-n"), "pgdn"), (("pgup", "alt-b"), "pgup"),
                             (("right", "l", "enter"), "open"),
                             (("left", "h", "esc", "backspace"), "back")):
            for k in keys:
                self.assertEqual(NAV[k], action, k)

    def test_numbers_and_alt_numbers_pick_a_tab(self):
        for n in "123":
            self.assertEqual(NAV[n], "tab")
            self.assertEqual(NAV["alt-" + n], "tab")
        self.assertNotIn("4", NAV)


class TestAppKeys(unittest.TestCase):
    """Key handling without a terminal: the app is driven by tokens."""

    BOARDS = [{"gid": "1", "name": "Alpha"}, {"gid": "2", "name": "Beta"},
              {"gid": "3", "name": "Gamma"}]
    SECTIONS = [{"gid": "s", "name": "M1", "tasks": [
        {"gid": "t1", "name": "one", "kind": "task"}, {"gid": "t2", "name": "two", "kind": "task"}]}]

    def asked(self):
        """The yes/no question the TUI is showing in its dialog, or ""."""
        return self.app.confirm[0] if self.app.confirm else ""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        isolate_cache(self)
        self.app = App(self.root)
        self.app.boards = list(self.BOARDS)
        self.app.sections = {"2": self.SECTIONS}
        self.app.sections_at = {"2": tui.time.time()}
        self.app.fetch_sections = lambda gid: self.SECTIONS

    def press(self, *keys):
        for k in keys:
            self.app.key(k, self.app.view())

    def test_tabs_are_runs_boards_setup(self):
        self.assertEqual(tui.TABS, ("Runs", "Boards", "Setup"))
        self.press("3", "4")
        self.assertEqual(tui.TABS[self.app.tab], "Setup")

    def test_a_number_goes_straight_to_its_tab(self):
        self.press("3")
        self.assertEqual(tui.TABS[self.app.tab], "Setup")
        self.press("alt-1")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")

    def test_tab_and_shift_tab_cycle(self):
        self.press("tab", "tab")
        self.assertEqual(self.app.tab, 2)
        self.press("tab")
        self.assertEqual(self.app.tab, 0)
        self.press("btab")
        self.assertEqual(self.app.tab, 2)

    def test_holding_ctrl_on_l_and_k_still_works(self):
        self.assertEqual(tui.decode_key(12), "ctrl-l")
        self.assertEqual(tui.NAV["ctrl-l"], "open")
        self.assertEqual(tui.NAV["ctrl-k"], "up")
        self.assertEqual(tui.NAV["backspace"], "back")

    def test_moving_in_every_style_and_clamping(self):
        self.press("2", "down", "j", "ctrl-n")
        self.assertEqual(self.app.cursor["Boards"], 2)
        self.press("up", "ctrl-p", "k", "k")
        self.assertEqual(self.app.cursor["Boards"], 0)
        self.press("G")
        self.assertEqual(self.app.cursor["Boards"], 2)
        self.press("g")
        self.assertEqual(self.app.cursor["Boards"], 0)
        self.press("alt-n")
        self.assertEqual(self.app.cursor["Boards"], 2)

    def test_the_list_still_moves_while_typing_a_filter(self):
        self.press("2", "/", "ctrl-n")
        self.assertTrue(self.app.typing)
        self.assertEqual(self.app.cursor["Boards"], 1)
        self.press("ctrl-p")
        self.assertEqual(self.app.cursor["Boards"], 0)
        self.press("alt-n")
        self.assertEqual(self.app.cursor["Boards"], 2)

    def test_done_tasks_toggle_from_setup_and_from_the_palette(self):
        self.press("3")
        rows = self.app.view()
        self.app.cursor[self.app.view_key()] = [r["id"] for r in rows].index("done")
        self.press("enter")
        self.assertTrue(dm.read_control(self.root).get("hide_done"))
        self.press(":", *"show done", "enter")
        self.assertFalse(dm.read_control(self.root).get("hide_done"))

    def test_subtasks_open_with_l_and_close_with_h(self):
        self.app.sections["2"][0]["tasks"][0]["subtasks"] = 2
        self.addCleanup(self.app.sections["2"][0]["tasks"][0].pop, "subtasks")
        self.app.asana = lambda args: [{"ref": "u1", "name": "sub one", "completed": False},
                                       {"ref": "u2", "name": "sub two", "completed": False}]
        self.press("2", "down", "enter", "down", "l")
        for _ in range(100):
            self.app.sync()
            if self.app.subtasks.get("t1") is not None:
                break
            tui.time.sleep(0.01)
        self.assertEqual([r["id"] for r in self.app.view()], ["s", "t1", "u1", "u2", "t2"])
        self.press("down", "down", "h")
        self.assertEqual([r["id"] for r in self.app.view()], ["s", "t1", "t2"])
        self.assertEqual(self.app.selected(self.app.view())["id"], "t1")
        self.assertTrue(self.app.board)
        self.press("h")
        self.assertFalse(self.app.board)

    def test_a_board_ticket_runs_as_a_goal_once(self):
        launched = []
        launch, tui.gl.launch = tui.gl.launch, lambda root, gid: launched.append(gid)
        self.addCleanup(setattr, tui.gl, "launch", launch)
        self.press("2", "down", "enter", "down")
        self.press(":", *"goal", "enter")
        [goal] = tui.gl.list_goals(self.root)
        self.assertEqual((goal["ref"], goal["name"], goal["status"]), ("t1", "one", "new"))
        self.assertEqual(launched, [goal["id"]])
        self.press(":", *"goal", "enter")
        self.assertEqual(len(tui.gl.list_goals(self.root)), 1)
        self.assertIn("already a goal", self.app.message)

    def test_space_on_a_board_row_queues_nothing(self):
        self.app.sections["2"] = [{"gid": "s", "name": "M1", "tasks": [
            {"gid": "m", "name": "the milestone", "kind": "milestone"},
            {"gid": "t1", "name": "one", "kind": "task"}]}]
        self.press("2", "down", "enter")
        for _ in range(3):
            self.press(" ", "down")
        self.assertFalse(dm.read_control(self.root).get("queue"))
        self.assertEqual(tui.gl.list_goals(self.root), [])
        for row in ("m", "t1"):
            self.app.cursor["board:2"] = [r["id"] for r in self.app.view()].index(row)
            self.press(":")
            titles = [c["title"] for c in self.app.palette["commands"]]
            self.assertTrue(any(t.startswith("Run ") and "as a goal" in t for t in titles), row)
            self.press("esc")

    def test_an_old_control_file_still_opens(self):
        launched = []
        launch, tui.gl.launch = tui.gl.launch, lambda root, gid: launched.append(gid)
        self.addCleanup(setattr, tui.gl, "launch", launch)
        old = {"queue": [{"gid": "t2", "board": "2", "name": "two", "checkpoint": True}],
               "commands": [{"id": 1, "op": "merge", "gid": "t2"}], "checkpoints": ["t1"],
               "sprint": {"gid": "9", "name": "Sprint 26/2"}, "merge_mode": "asked",
               "base": "feature/x"}
        with dm.control_file(self.root) as c:
            c.update(old)
        self.app = App(self.root)
        self.app.boards, self.app.sections = list(self.BOARDS), {"2": self.SECTIONS}
        self.app.sections_at = {"2": tui.time.time()}
        self.assertEqual(self.app.view(), [])
        self.press("3")
        self.assertEqual(self.app.view()[0]["cols"], ["Queue into", "feature/x"])
        self.press("2", "down", "enter", "down", ":", *"goal", "enter")
        [goal] = tui.gl.list_goals(self.root)
        self.assertEqual(goal["base"], "feature/x")
        self.assertIn("goal started on feature/x", self.app.message)
        self.press("3", "down", "enter")
        saved = dm.read_control(self.root)
        self.assertTrue(saved["hide_done"])
        self.assertEqual({k: saved[k] for k in old}, old)

    def test_o_opens_the_task_or_the_board_in_asana(self):
        opened = []
        saved = tui.webbrowser.open
        tui.webbrowser.open = opened.append
        self.addCleanup(setattr, tui.webbrowser, "open", saved)
        self.press("2", "down", "o")
        self.assertEqual(opened[-1], "https://app.asana.com/0/2/list")
        self.press("enter", "down", "o")
        self.assertEqual(opened[-1], "https://app.asana.com/0/2/t1")

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
        self.press("ctrl-a", "x", "ctrl-e", "ctrl-b", "ctrl-d")
        self.assertEqual(self.app.query["Boards"], "xjq")
        self.assertEqual(tui.TABS[self.app.tab], "Boards")
        self.press("esc")
        self.assertEqual(self.app.query["Boards"], "")
        self.assertFalse(self.app.typing)

    def test_target_branch_is_picked_from_the_list(self):
        self.app.branches, self.app.default_branch = ["main", "release/1.2"], "main"
        self.app.branches_at = tui.time.time()
        self.press("3", "enter")
        self.assertEqual(self.app.setup, "base")
        self.press("down", "right")
        self.assertIsNone(self.app.control.get("base"))
        self.press("enter")
        self.assertEqual(self.app.control["base"], "release/1.2")
        self.press("enter")
        self.assertEqual(self.app.selected(self.app.view())["id"], "release/1.2")  # opens on it
        self.press("up", "enter")
        self.assertIsNone(self.app.control["base"])  # the default is stored as "no override"

    def new_branch_setup(self):
        self.created = []
        self.app.branches, self.app.default_branch = ["main", "develop"], "main"
        self.app.branches_at = tui.time.time()
        self.app.create_branch = lambda name: self.created.append(name)
        self.press("3", "enter")

    def test_the_new_branch_row_takes_a_name_with_slashes_and_asks_first(self):
        self.new_branch_setup()
        self.press("home", "enter")
        self.assertEqual(self.app.compose["kind"], "branch")
        self.press(*"milestone/m1", "enter")
        self.assertIn("create milestone/m1 on origin from origin/main", self.asked())
        self.assertEqual(self.created, [])
        self.press("y")
        self.assertEqual(self.created, ["milestone/m1"])

    def test_n_starts_a_new_branch_too_and_esc_cancels(self):
        self.new_branch_setup()
        self.press("n", *"x/y", "esc")
        self.assertIsNone(self.app.compose)
        self.assertEqual(self.created, [])

    def test_a_bad_name_is_refused_and_an_existing_one_is_just_picked(self):
        self.new_branch_setup()
        self.press("n", *"bad..name", "enter")
        self.assertIn("not a name git takes", self.app.message)
        self.press("n", *"develop", "enter")
        self.assertEqual(self.app.control["base"], "develop")
        self.assertEqual(self.created, [])

    def test_the_models_are_set_on_setup_and_a_new_goal_uses_them(self):
        self.press("3", *["down"] * 2, "enter", "ctrl-u", *"82", "enter")
        self.assertEqual(self.app.control["usage_threshold"], 82)
        self.press("enter", "ctrl-u", *"150", "enter")
        self.assertEqual(self.app.control["usage_threshold"], 82)
        self.assertIn("1 to 100", self.app.message)
        self.press("down", "enter")
        self.assertEqual([r["cols"][0] for r in self.app.view()], ["haiku", "sonnet", "opus", "fable"])
        self.press("up", "enter")
        self.assertEqual(self.app.control["models"], {"lead": "claude-sonnet-5-5"})
        self.press("down", "enter", "down", "enter")
        self.press("down", "enter", "home", "enter", "down", "enter", "end", "enter")
        self.assertEqual(self.app.control["models"]["check"], "claude-haiku-4-5-20251001")
        self.assertEqual(self.app.control["models"]["check_effort"], "max")
        settings = tui.gl.settings_from(self.app.control)
        self.assertEqual(settings, {"model": "claude-sonnet-5-5", "subagent_model": "claude-opus-5-5",
                                    "check_model": "claude-haiku-4-5-20251001", "check_effort": "max",
                                    "threshold": 82, "gate": "wait"})
        self.press("down", "enter")
        self.assertEqual([r["id"] for r in self.app.view()], ["wait", "top", "auto"])
        self.press("down", "enter")
        self.assertEqual(tui.gl.settings_from(self.app.control)["gate"], "top")

    def test_q_quits_and_help_closes_on_any_key(self):
        self.press("?")
        self.assertTrue(self.app.help)
        self.press("j", "down", "alt-n")
        self.assertTrue(self.app.help)          # the arrows scroll it
        self.press("x")
        self.assertFalse(self.app.help)         # anything else closes it
        self.assertFalse(self.app.key("q", []))


QUESTION = {"kind": "questions", "asked_at": "2026-10-01T10:00:00.000Z", "label": "implement",
            "questions": [{"q": "Which VPC — nonprod or shared?", "why": "two in tfvars"},
                          {"q": "Fail closed?", "why": ""}]}
PROBLEM = {"kind": "qa", "asked_at": "2026-10-01T11:00:00.000Z",
           "headline": "QA gate still failing at 'backend'", "detail": "line 1\nE   assert 2 == 3"}


class TestWaits(unittest.TestCase):
    def test_summaries(self):
        self.assertEqual(wait_summary(QUESTION),
                         "has questions for you: Which VPC — nonprod or shared? (+1 more)")
        self.assertEqual(wait_summary(PROBLEM), "QA gate still failing at 'backend' — ⏎ to read, a to reply")
        self.assertIn("c approves it", wait_summary({"kind": "plan"}))
        lines = " ".join(t for t, _ in wait_lines({"kind": "plan", "split": True,
                                                   "detail": "- API\n- Inbox"}, 80))
        self.assertIn("You approve the split here, not how the work is built", lines)
        self.assertIn("Review the split", wait_summary({"kind": "plan", "split": True}))
        self.assertIn("Review the plan", wait_summary({"kind": "plan"}))
        self.assertIn("Nothing is built until you approve it",
                      " ".join(t for t, _ in wait_lines({"kind": "plan"}, 80)))
        self.assertIn("The parts:", lines)
        self.assertIn("- Inbox", lines)

    def test_the_whole_wait_is_shown(self):
        text = [t for t, _ in wait_lines(QUESTION, 80)]
        self.assertIn("1. Which VPC — nonprod or shared?", text)
        self.assertIn("   two in tfvars", text)
        self.assertIn("2. Fail closed?", text)
        problem = [t for t, _ in wait_lines(PROBLEM, 80)]
        self.assertIn("QA gate still failing at 'backend'", problem)
        self.assertIn("  E   assert 2 == 3", problem)

    def test_long_questions_wrap_to_the_screen(self):
        long_q = {"questions": [{"q": "word " * 40}]}
        self.assertTrue(all(len(t) <= 36 for t, _ in wait_lines(long_q, 40)))

    def test_the_editor_template_round_trips_to_just_the_answer(self):
        template = answer_template("HCI-24", QUESTION)
        self.assertIn("# 1. Which VPC — nonprod or shared?", template)
        self.assertIsNone(parse_answer(template))
        self.assertEqual(parse_answer("nonprod, and fail closed\n\n" + template),
                         "nonprod, and fail closed")

    def test_a_wait_with_no_headline_still_says_what_it_asks_of_you(self):
        self.assertIn("has questions for you", wait_summary({"kind": "questions"}))
        self.assertIn("waiting on a reply from you", wait_summary({"kind": "?"}))

class TestAnswering(unittest.TestCase):
    def asked(self):
        """The yes/no question the TUI is showing in its dialog, or ""."""
        return self.app.confirm[0] if self.app.confirm else ""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        isolate_cache(self)
        self.gid = tui.gl.create(self.root, "1", "A-1", "one", base="main")
        tui.gl.Goal(self.root, self.gid).state.write("awaiting.json", QUESTION)
        self.row = "goal:%s" % self.gid
        self.app = App(self.root)

    def press(self, *keys):
        for k in keys:
            self.app.key(k, self.app.view())

    def handed_over(self):
        return st.State(self.root, self.gid).read(st.ANSWER_FILE)

    def test_enter_on_a_waiting_goal_opens_its_questions(self):
        self.press("1")
        self.assertEqual(self.app.view()[0]["id"], self.row)
        self.press("enter")
        self.assertEqual(self.app.question, self.row)
        self.press("esc")
        self.assertIsNone(self.app.question)

    def test_a_one_line_answer_reaches_the_goal(self):
        self.press("1", "enter", "a")
        self.press(*"use nonprod")
        self.press("enter")
        handed = self.handed_over()
        self.assertEqual(handed["text"], "use nonprod")
        self.assertEqual(handed["asked_at"], QUESTION["asked_at"])
        self.assertEqual(self.app.message, "answered — the goal carries on")

    def test_typing_an_answer_does_not_trigger_keys(self):
        self.press("1", "a", *"q2x")
        self.assertEqual(self.app.compose["text"], "q2x")
        self.press("ctrl-a", "ctrl-k", *"use nonprod", "alt-b", "ctrl-k")
        self.assertEqual(self.app.compose["text"], "use ")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")

    def test_escape_or_an_empty_answer_sends_nothing(self):
        self.press("1", "a", *"draft", "esc")
        self.press("a", "enter")
        self.assertIsNone(self.handed_over())

    def test_A_asks_for_the_editor(self):
        self.press("1", "A")
        self.assertEqual(self.app.edit_request, self.row)

    def test_c_approves_a_plan_waiting_on_you(self):
        self.press("c")
        self.assertEqual(self.asked(), "")
        self.assertIn("no plan waits on your approval", self.app.message)
        tui.gl.Goal(self.root, self.gid).state.write(
            "awaiting.json", {"kind": "plan", "asked_at": "2026-10-01T12:00:00.000Z"})
        self.app.snapshot()
        self.press("c")
        self.assertIn("approve the plan of \"A-1 one\"", self.asked())
        self.press("y")
        self.assertEqual(self.handed_over()["text"], "continue")

    def palette_titles(self):
        return [c["title"] for c in tui.palette_matches(self.app.palette["commands"],
                                                        self.app.palette["query"])]

    def select(self, gid):
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index(gid)

    def test_the_palette_has_only_what_no_key_below_does(self):
        self.select(self.row)
        self.press(":")
        self.assertEqual(self.palette_titles(),
                         ["Discuss the goal A-1 one", "Undo the goal A-1 one", "Hide done tasks"])

    def test_typing_in_the_palette_does_not_trigger_hotkeys(self):
        self.press(":", *"xq2m")
        self.assertEqual(self.app.palette["query"], "xq2m")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")
        self.assertIsNone(self.app.confirm)
        self.press("esc")
        self.assertIsNone(self.app.palette)

    def test_the_palette_line_takes_editing_keys(self):
        self.press(":", *"undo", "ctrl-a", "ctrl-k")
        self.assertEqual(self.app.palette["query"], "")
        self.press(*"stat", "ctrl-b", "r", "ctrl-e", "ctrl-n", "ctrl-p")
        self.assertEqual(self.app.palette["query"], "start")

    def frame(self):
        class Scr(object):
            def __init__(self):
                self.grid = [[" "] * 90 for _ in range(24)]

            def getmaxyx(self):
                return 24, 90

            def erase(self):
                pass

            def refresh(self):
                pass

            def hline(self, y, x, ch, n):
                self.addnstr(y, x, "─" * n, n)

            def addnstr(self, y, x, text, n, attr=0):
                for i, ch in enumerate(text[:n]):
                    if 0 <= y < 24 and 0 <= x + i < 90:
                        self.grid[y][x + i] = ch
        scr = Scr()
        self.app.draw(scr, {k: 0 for k in ("normal", "bold", "dim", "sel", "ok", "warn", "bad")})
        return ["".join(r).rstrip() for r in scr.grid]

    def test_enter_on_a_goal_opens_its_live_view(self):
        gid = tui.gl.create(self.root, "9", "A-9", "Queue", base="main")
        tui.gl.Goal(self.root, gid).update(status="working", round=2, doing="round 2",
                                           worktree="/nowhere")
        self.app.snapshot()
        self.press("1")
        self.select("goal:%s" % gid)
        self.press("enter")
        self.assertEqual(self.app.goal_view, gid)
        lines = self.frame()
        self.assertIn("Runs › goal A-9 Queue", lines[2])
        self.assertTrue(any("Running now" in l for l in lines))
        self.press("l")
        self.assertEqual(self.app.log_path, tui.gl.Goal(self.root, gid).log)
        self.press("esc")
        self.assertEqual((self.app.log_path, self.app.goal_view), (None, gid))
        self.press("esc")
        self.assertIsNone(self.app.goal_view)

    def test_a_question_is_asked_in_the_dialog_box_not_the_bottom_line(self):
        self.press("1", "x")
        lines = self.frame()
        box = [l for l in lines if "│" in l]
        self.assertTrue(any("─ confirm" in l for l in lines))
        self.assertTrue(any("take the goal" in l for l in box))
        self.assertTrue(any("y yes · any other key no" in l for l in box))
        self.assertNotIn("(y/n)", "\n".join(lines))
        self.press("n")
        self.assertFalse(any("─ confirm" in l for l in self.frame()))

    def test_typing_and_picking_happen_in_the_dialog_box(self):
        self.press("3", *["down"] * 2, "enter")
        lines = self.frame()
        self.assertTrue(any("─ usage limit" in l for l in lines))
        self.assertTrue(any("› 75" in l for l in lines))
        self.press("esc", "down", "enter")
        lines = self.frame()
        self.assertTrue(any("─ goal lead" in l for l in lines))
        self.assertTrue(any("▸ opus" in l and "← now" in l for l in lines))
        self.assertIn("3 Setup", lines[1])   # Setup stays behind it

    def test_the_selected_row_is_marked_not_only_coloured(self):
        self.press("1")
        lines = self.frame()
        marked = [l for l in lines[3:8] if l.startswith("▸ ")]
        self.assertEqual(len(marked), 1)

    def test_the_palette_marks_its_choice_and_hides_the_list_behind_it(self):
        self.press("1", ":")
        lines = self.frame()
        self.assertFalse(any(l.startswith("▸") for l in lines[3:10]))
        self.assertEqual(sum("│ ▸ " in l for l in lines), 1)


class TestSetup(unittest.TestCase):
    def test_rows_say_what_is_set(self):
        rows = setup_rows({"base": None}, "main")
        self.assertEqual([r["cols"][0] for r in rows],
                         ["Queue into", "Done tasks", "Usage limit", "Goal lead",
                          "Goal sub-agents", "Goal checker", "Checker effort", "Plan approval"])
        self.assertEqual([r["cols"][1].split(" — ")[0] for r in rows[2:]],
                         ["75%", "opus", "sonnet", "opus", "high",
                          "you, for the goal and each of its parts (recommended)"])
        self.assertEqual(rows[0]["cols"][1], "the default branch (main)")
        self.assertEqual(setup_rows({"base": "feature/x"}, "main")[0]["cols"][1], "feature/x")

    def test_setup_has_no_sprint_merging_or_task_model(self):
        rows = setup_rows({"sprint": {"name": "Sprint 26/2"}, "merge_mode": "always",
                           "models": {"task": "claude-opus-5-5"}}, "main")
        names = [r["cols"][0] for r in rows]
        for gone in ("Sprint", "Merging", "Task model"):
            self.assertNotIn(gone, names)
        for kept in ("Plan approval", "Queue into", "Goal lead", "Goal sub-agents", "Goal checker",
                     "Checker effort", "Usage limit"):
            self.assertIn(kept, names)
        self.assertNotIn("merge", tui.PICKED)
        self.assertNotIn("model-task", tui.PICKED)
        self.assertFalse(hasattr(tui, "MERGE_LABELS"))

    def test_a_setting_s_choices_say_what_each_means_and_which_is_set(self):
        rows = tui.choice_rows("model-check", {})
        self.assertEqual([r["id"] for r in rows if "← now" in r["cols"][1]], ["claude-opus-5-5"])
        self.assertIn("narrow, well-briefed work", rows[1]["cols"][1])
        efforts = tui.choice_rows("effort-check", {"models": {"check_effort": "high"}})
        self.assertEqual([r["cols"][0] for r in efforts], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(efforts[2]["style"], "bold")

    def test_ls_remote_gives_the_default_first(self):
        text = ("ref: refs/heads/main\tHEAD\nabc\tHEAD\nabc\trefs/heads/main\n"
                "def\trefs/heads/HGM-1/x\n123\trefs/heads/develop\n")
        self.assertEqual(parse_ls_remote(text), ("main", ["main", "develop", "HGM-1/x"]))

    def test_branch_rows_start_with_new_and_search_only_filters(self):
        rows = branch_rows(["main", "develop"], "main", "", None)
        self.assertEqual([r["kind"] for r in rows], ["new", "branch", "branch"])
        self.assertIn("from origin/main", rows[0]["cols"][1])
        self.assertEqual([r["id"] for r in branch_rows(["main", "develop"], "main", "dev", None)],
                         ["+new", "develop"])
        picked = branch_rows(["main", "develop"], "main", "", "develop")
        self.assertIn("← queueing here", picked[2]["cols"][1])

    def test_branch_names(self):
        for good in ("release/1.2", "milestone-m1", "HGM-1/x"):
            self.assertTrue(valid_branch_name(good), good)
        for bad in ("", "-x", "a..b", "a b", "x.lock", "a//b", "/x", "x/"):
            self.assertFalse(valid_branch_name(bad), bad)


class TestLineEdit(unittest.TestCase):
    def typed(self, text, *keys):
        line = tui.LineEdit(text)
        for k in keys:
            self.assertTrue(line.key(k), k)
        return line.text, line.pos

    def test_moving_and_inserting_mid_line(self):
        self.assertEqual(self.typed("milestone", "ctrl-a", "x"), ("xmilestone", 1))
        self.assertEqual(self.typed("ab", "ctrl-b", "-"), ("a-b", 2))
        self.assertEqual(self.typed("ab", "left", "left", "right", "|"), ("a|b", 2))
        self.assertEqual(self.typed("ab", "home", "end", "!"), ("ab!", 3))

    def test_killing(self):
        self.assertEqual(self.typed("feature/m1", "ctrl-a", "ctrl-f", "ctrl-k"), ("f", 1))
        self.assertEqual(self.typed("feature/m1", "ctrl-b", "ctrl-u"), ("1", 0))
        self.assertEqual(self.typed("use nonprod please", "ctrl-w"), ("use nonprod ", 12))
        self.assertEqual(self.typed("ab", "ctrl-a", "ctrl-d"), ("b", 0))
        self.assertEqual(self.typed("ab", "backspace", "backspace", "backspace"), ("", 0))

    def test_words(self):
        self.assertEqual(self.typed("feature/candidate intake", "alt-b", "alt-b")[1], 8)
        self.assertEqual(self.typed("feature/candidate", "ctrl-a", "alt-f")[1], 7)

    def test_other_keys_are_left_to_the_caller(self):
        self.assertFalse(tui.LineEdit("x").key("enter"))
        self.assertFalse(tui.LineEdit("x").key("up"))

    def test_the_cursor_is_drawn_and_kept_in_view(self):
        self.assertEqual(tui.LineEdit("ab").show(), "ab▏")
        line = tui.LineEdit("abcdefghij")
        line.key("ctrl-a")
        self.assertTrue(line.show(5).startswith("▏"))
        self.assertLessEqual(len(tui.LineEdit("x" * 50).show(10)), 10)


class TestHelpPage(unittest.TestCase):
    def test_the_tab_you_are_on_comes_right_after_moving_around(self):
        headings = [t for k, t, style in tui.help_lines(100, "Setup") if style == "bold"]
        self.assertEqual(headings[:2], ["Moving around", "Setup   · this tab"])
        self.assertTrue(headings[-1].startswith("Typing"))

    def test_palette_commands_are_explained_and_tasks_are_gone(self):
        text = " ".join(t for _, t, _ in tui.help_lines(100, "Runs"))
        for words in ("Run HCI-8 as a goal", "Undo the goal", "Discuss the goal", "Queue into"):
            self.assertIn(words, text)
        for words in ("Checkpoints", "Daemons", "checkpoint", "merge:", "space"):
            self.assertNotIn(words, text)

    def test_keys_and_text_are_separate_columns_and_long_text_wraps_under_itself(self):
        lines = tui.help_lines(60, "Runs")
        approve = [i for i, (k, t, s) in enumerate(lines) if k == "c"][0]
        self.assertTrue(lines[approve][1].startswith("approve"))
        self.assertEqual(lines[approve + 1][0], "")          # the wrap has no key of its own
        self.assertTrue(all(len(t) <= 60 - tui.HELP_KEYS_WIDTH - 6
                            for _, t, style in lines if style != "bold"))


class TestGoalStatus(unittest.TestCase):
    def test_a_goal_stopped_while_it_waits_on_you_says_it_is_stopped(self):
        wait = {"kind": "questions", "questions": [{"q": "Colour?"}], "asked_at": "x"}
        text, _ = tui.goal_status({"status": "stopped", "alive": False}, wait)
        self.assertTrue(text.startswith("stopped — r carries it on"))
        text, _ = tui.goal_status({"status": "waiting", "alive": True}, wait)
        self.assertTrue(text.startswith("⚑"))


class TestGoalPRError(unittest.TestCase):
    def test_a_goal_that_cannot_read_its_pr_says_so(self):
        text, style = tui.goal_status({"status": "review", "alive": True,
                                       "pr_error": "HTTP 401: Bad credentials"})
        self.assertIn("cannot read its PR", text)
        self.assertEqual(style, "bad")


class TestMarkGoalDone(unittest.TestCase):
    def test_a_goal_marked_done_stays_done_and_leaves_a_hidden_list(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        gid = tui.gl.create(d, "1", "A-1", "x", base="main")
        tui.gl.Goal(d, gid).update(status="done", phase="review", pr_url="https://github.com/o/r/pull/1")
        tui.gl.mark_done(d, gid)
        tui.gl.Goal(d, gid).update(status="stopped", reason="stopped", doing="stopped")
        [g] = tui.gl.list_goals(d)
        self.assertEqual((g["status"], g["phase"], g["reason"]), ("done", tui.gl.MARKED, "stopped"))
        self.assertEqual(tui.goal_status(g), ("marked done by you", "dim"))
        [row] = tui.goal_rows([g])
        self.assertTrue(row["done"])
        self.assertEqual(tui.goal_rows([g], hide_done=True), [])

    def test_a_part_already_merged_keeps_its_status(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        gid = tui.gl.create(d, "1", "A-1", "x", base="main")
        tui.gl.Goal(d, gid).update(status="parts", branch="A-1/goal-x", worktree=d)
        brief = {"brief": "b", "criteria": [], "after": []}
        done = tui.gl.create_part(d, tui.gl.Goal(d, gid).read(), dict(brief, name="API"), 0, [])
        live = tui.gl.create_part(d, tui.gl.Goal(d, gid).read(), dict(brief, name="UI"), 1, [])
        tui.gl.Goal(d, done).update(status="done", phase="merged")
        tui.gl.mark_done(d, gid)
        self.assertEqual(tui.gl.Goal(d, done).read()["phase"], "merged")
        self.assertEqual(tui.gl.Goal(d, live).read()["phase"], tui.gl.MARKED)
        self.assertEqual(tui.gl.Goal(d, gid).read()["status"], "done")


class TestClearGoals(unittest.TestCase):
    def test_done_goals_and_their_parts_leave_the_list(self):
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        gid = tui.gl.create(d, "1", "A-1", "x", base="main")
        tui.gl.Goal(d, gid).update(status="done", branch="A-1/goal-x", worktree=d)
        part = tui.gl.create_part(d, tui.gl.Goal(d, gid).read(), {"name": "API", "brief": "b",
                                                                  "criteria": [], "after": []}, 0, [])
        other = tui.gl.create(d, "2", "A-2", "y", base="main")
        app = type("App", (), {"main_root": d, "snapshot": lambda self: None})()
        tui.App.clear_goals(app, [g for g in tui.gl.list_goals(d) if g["id"] == gid])
        self.assertEqual([g["id"] for g in tui.gl.list_goals(d)], [other])
        self.assertTrue(tui.gl.Goal(d, part).read().get("cleared"))


class TestDiscussTab(unittest.TestCase):
    def test_ghostty_on_macos_gets_a_tab_that_runs_the_discussion(self):
        calls = []
        run = tui.subprocess.run
        tui.subprocess.run = lambda argv, **kw: calls.append(argv) or tui.subprocess.CompletedProcess(argv, 0)
        self.addCleanup(setattr, tui.subprocess, "run", run)
        env = dict(os.environ, TERM_PROGRAM="ghostty")
        with mock.patch.dict(os.environ, env), mock.patch.object(tui.sys, "platform", "darwin"):
            self.assertTrue(tui.discuss_in_tab('/r/my "repo"', "goal-a-1"))
        script = calls[0][2]
        self.assertIn("new tab in front window", script)
        self.assertIn('goal discuss goal-a-1 --repo \'/r/my \\"repo\\"\'', script)

    def test_another_terminal_gets_no_tab(self):
        with mock.patch.dict(os.environ, {"TERM_PROGRAM": "Apple_Terminal"}):
            self.assertFalse(tui.discuss_in_tab("/r", "goal-a-1"))


class TestLogLine(unittest.TestCase):
    def test_escape_codes_are_removed_and_headings_stay_bold(self):
        self.assertEqual(log_line("\x1b[1mFetching task\x1b[0m"), ("Fetching task", "bold"))
        self.assertEqual(log_line("  status → In Progress"), ("  status → In Progress", "normal"))

    def test_plain_headings_are_bold_and_run_headers_stand_out(self):
        self.assertEqual(log_line("20:01:08  Applying the feedback")[1], "bold")
        self.assertEqual(log_line("━━ 2026-10-01 20:01:08 · revise: x ━━")[1], "warn")
        self.assertEqual(log_line("")[1], "normal")

    def test_colour_and_cursor_codes_go_too(self):
        self.assertEqual(log_line("\x1b[32mok\x1b[39m \x1b[2Kdone")[0], "ok done")



class TestPrintStatus(unittest.TestCase):
    def test_print_status_lists_goals_only(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        with dm.control_file(root) as c:
            c.update(queue=[{"gid": "7", "name": "a queued task"}], sprint={"gid": "9", "name": "S"})
        gid = tui.gl.create(root, "9", "A-9", "Dark mode", base="main")
        tui.gl.Goal(root, gid).state.write("awaiting.json", QUESTION)
        out = io.StringIO()
        with mock.patch.object(tui.sys, "stdout", out):
            tui.print_status(root)
        text = out.getvalue()
        self.assertIn("A-9 Dark mode", text)
        self.assertIn("⚑ 1 waiting on you", text)
        self.assertIn("Which VPC", text)
        for gone in ("a queued task", "daemon", "sprint"):
            self.assertNotIn(gone, text)
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        out = io.StringIO()
        with mock.patch.object(tui.sys, "stdout", out):
            tui.print_status(empty)
        self.assertEqual(out.getvalue(), "no goals\n")


class TestSettleFinishedPRs(unittest.TestCase):
    def test_a_finished_goal_learns_its_pr_was_closed(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        gid = tui.gl.create(root, "9", "A-9", "Old", base="main")
        tui.gl.Goal(root, gid).update(status="done", pr_url="https://github.com/o/r/pull/5")
        run = tui.subprocess.run
        tui.subprocess.run = lambda *a, **k: tui.subprocess.CompletedProcess(a, 0, "CLOSED\n", "")
        self.addCleanup(setattr, tui.subprocess, "run", run)
        tui._PR_LOOKED.clear()
        tui.settle_finished_prs(root, tui.gl.list_goals(root))
        deadline = time.time() + 2
        while tui.gl.Goal(root, gid).read().get("phase") != "closed" and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(tui.gl.Goal(root, gid).read().get("phase"), "closed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
