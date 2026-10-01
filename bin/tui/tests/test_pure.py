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

import cache  # noqa: E402
import daemon as dm  # noqa: E402
import tui  # noqa: E402
from tui import (  # noqa: E402
    NAV, App, answer_template, board_list_rows, board_rows, decode_escape, decode_key, fit,
    matches, parse_answer, read_waits, run_rows, wait_lines, wait_summary,
)
from daemon import st  # noqa: E402


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


class TestOrphanAgents(unittest.TestCase):
    WT = "/repo/.cortex/worktrees"
    AGENT = "claude -p --add-dir /repo/.cortex/worktrees/HCI-6+ci8-mailbox --model x"

    def test_an_agent_whose_run_is_gone_is_found(self):
        rows = [(1, 0, "launchd"), (500, 1, self.AGENT)]
        self.assertEqual(dm.orphan_agents(rows, self.WT, []), [("HCI-6+ci8-mailbox", 500)])

    def test_an_agent_under_a_live_run_is_owned(self):
        rows = [(1, 0, "launchd"), (400, 1, "python start_task.py ..."), (500, 400, self.AGENT)]
        self.assertEqual(dm.orphan_agents(rows, self.WT, [400]), [])

    def test_only_the_top_of_a_stray_tree_is_listed(self):
        rows = [(500, 1, self.AGENT),
                (501, 500, "bash -c cd /repo/.cortex/worktrees/HCI-6+ci8-mailbox && make")]
        self.assertEqual([pid for _, pid in dm.orphan_agents(rows, self.WT, [])], [500])

    def test_other_repos_and_processes_are_not_ours(self):
        rows = [(500, 1, "claude -p --add-dir /other/.cortex/worktrees/X+y"), (9, 1, "vim")]
        self.assertEqual(dm.orphan_agents(rows, self.WT, []), [])


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
        rows = run_rows(control, data, [("HCI-1", 10), ("HCI-7", 77)],
                        agents=[("HCI-6+mailbox", 500)])
        self.assertEqual([r["kind"] for r in rows], ["task", "task", "orphan", "orphan"])
        self.assertIn("no run owns it", rows[3]["cols"][1])
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
        self.app = App(self.root, [])
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

    def test_the_daemons_view_of_a_task_overrides_the_cache(self):
        rows = board_rows("1", self.SECTIONS, set(), {}, "", {"t1": {"completed": True}})
        self.assertEqual(rows[1]["cols"][1], "done")


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
        isolate_cache(self)
        self.app = App(self.root, [])
        self.app.boards = list(self.BOARDS)
        self.app.sections = {"2": self.SECTIONS}
        self.app.sections_at = {"2": tui.time.time()}
        self.app.fetch_sections = lambda gid: self.SECTIONS

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


QUESTION = {"kind": "questions", "asked_at": "2026-10-01T10:00:00.000Z", "label": "implement",
            "questions": [{"q": "Which VPC — nonprod or shared?", "why": "two in tfvars"},
                          {"q": "Fail closed?", "why": ""}]}
PROBLEM = {"kind": "qa", "asked_at": "2026-10-01T11:00:00.000Z",
           "headline": "QA gate still failing at 'backend'", "detail": "line 1\nE   assert 2 == 3"}


class TestWaits(unittest.TestCase):
    def test_summaries(self):
        self.assertEqual(wait_summary(QUESTION), "Which VPC — nonprod or shared? (+1 more)")
        self.assertEqual(wait_summary(PROBLEM), "QA gate still failing at 'backend'")
        self.assertIn("a to have it resolved", wait_summary({"kind": "conflict"}))

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

    def test_waiting_tasks_sort_first_and_are_flagged(self):
        control = {"queue": [{"gid": "1"}, {"gid": "2"}]}
        data = {"tasks": {"1": {"key": "A-1", "name": "one", "deps": []},
                          "2": {"key": "A-2", "name": "two", "deps": []}}, "records": {}}
        rows = run_rows(control, data, [], waits={"2": QUESTION})
        self.assertEqual([r["id"] for r in rows], ["2", "1"])
        self.assertTrue(rows[0]["cols"][2].startswith("⚑ Which VPC"))
        self.assertEqual(rows[0]["style"], "warn")


class TestReadWaits(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_questions_problems_and_parked_conflicts_are_waits(self):
        st.State(self.root, "A-1").write("awaiting.json", QUESTION)
        control = {"queue": [{"gid": "1"}, {"gid": "2"}, {"gid": "3"}]}
        data = {"tasks": {"1": {"key": "A-1"}, "2": {"key": "A-2"}, "3": {"key": "A-3"}},
                "records": {"2": {"phase": "conflict"}, "3": {"phase": "running"}}}
        waits = read_waits(self.root, control, data)
        self.assertEqual(sorted(waits), ["1", "2"])
        self.assertEqual(waits["1"]["key"], "A-1")
        self.assertEqual(waits["2"]["kind"], "conflict")


class TestAnswering(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        isolate_cache(self)
        st.State(self.root, "A-1").write("awaiting.json", QUESTION)
        with dm.control_file(self.root) as c:
            dm.queue_add(c, [{"gid": "1", "board": "9", "name": "one"},
                             {"gid": "2", "board": "9", "name": "two"}])
        os.makedirs(dm.queue_dir(self.root), exist_ok=True)
        dm.write_json(os.path.join(dm.queue_dir(self.root), "state.json"), {
            "tasks": {"1": {"key": "A-1", "name": "one", "deps": []},
                      "2": {"key": "A-2", "name": "two", "deps": []}},
            "records": {"1": {"phase": "awaiting"},
                        "2": {"phase": "conflict", "pr_url": "https://github.com/o/r/pull/7"}}})
        self.posted = []
        self.app = App(self.root, [])
        self.app.asana = lambda args: self.posted.append(args)

    def press(self, *keys):
        for k in keys:
            self.app.key(k, self.app.view())

    def handed_over(self):
        return st.State(self.root, "A-1").read(st.ANSWER_FILE)

    def test_enter_on_a_waiting_task_opens_its_questions(self):
        self.press("1")
        self.assertEqual(self.app.view()[0]["id"], "1")
        self.press("enter")
        self.assertEqual(self.app.question, "1")
        self.press("esc")
        self.assertIsNone(self.app.question)

    def test_a_one_line_answer_reaches_the_run_and_the_task(self):
        self.press("1", "enter", "a")
        self.press(*"use nonprod")
        self.press("enter")
        handed = self.handed_over()
        self.assertEqual(handed["text"], "use nonprod")
        self.assertEqual(handed["asked_at"], QUESTION["asked_at"])
        for _ in range(100):
            self.app.sync()
            if self.posted:
                break
            tui.time.sleep(0.01)
        self.assertEqual(self.posted, [["comment", "add", "1", "use nonprod"]])

    def test_typing_an_answer_does_not_trigger_keys(self):
        self.press("1", "a", *"q2x")
        self.assertEqual(self.app.compose["text"], "q2x")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")

    def test_escape_or_an_empty_answer_sends_nothing(self):
        self.press("1", "a", *"draft", "esc")
        self.press("a", "enter")
        self.assertIsNone(self.handed_over())

    def test_A_asks_for_the_editor(self):
        self.press("1", "A")
        self.assertEqual(self.app.edit_request, "1")

    def test_m_asks_then_tells_the_daemon_to_merge(self):
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index("2")
        self.press("m")
        self.assertIn("merge A-2", self.app.message)
        self.press("y")
        self.assertEqual([(c["op"], c["gid"]) for c in self.app.control["commands"]],
                         [("merge", "2")])

    def test_m_on_a_merge_in_progress_calls_it_off(self):
        path = os.path.join(dm.queue_dir(self.root), "state.json")
        data = dm.read_json(path)
        data["records"]["2"]["merge"] = {"stage": "checks running"}
        dm.write_json(path, data)
        self.app.snapshot()
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index("2")
        self.press("m", "y")
        self.assertEqual(self.app.control["commands"][-1]["op"], "merge-cancel")

    def test_a_blocked_merge_waits_on_you(self):
        path = os.path.join(dm.queue_dir(self.root), "state.json")
        data = dm.read_json(path)
        data["records"]["2"]["merge"] = {"blocked": "checks still failing: e2e"}
        dm.write_json(path, data)
        self.app.snapshot()
        self.assertEqual(self.app.waits["2"]["kind"], "merge")
        self.assertIn("m tries again", wait_summary(self.app.waits["2"]))

    def test_a_on_a_parked_conflict_asks_then_requests_a_resolve(self):
        asked = []
        self.app.resolve = lambda gid, url: asked.append((gid, url))
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index("2")
        self.press("a")
        self.assertIn("please resolve", self.app.message)
        self.press("y")
        self.assertEqual(asked, [("2", "https://github.com/o/r/pull/7")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
