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
from tui import palette_matches  # noqa: E402,F401
from tui import (  # noqa: E402
    NAV, App, answer_template, board_list_rows, board_rows, branch_rows, decode_escape,
    decode_key, fit, log_line, matches, parse_answer, parse_ls_remote, read_waits, run_rows,
    setup_rows, valid_branch_name, wait_lines, wait_summary,
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


class TestDependencies(unittest.TestCase):
    TASKS = {"7": {"key": "T-7", "deps": [{"ref": "5", "name": "five", "completed": False},
                                          {"ref": "4", "name": "four", "completed": True}]},
             "9": {"key": "T-9", "deps": [{"ref": "5", "name": "five", "completed": False},
                                          {"ref": "7", "name": "seven", "completed": False}]},
             "3": {"key": "T-3", "deps": [{"ref": "1", "completed": False}]}}

    def test_unfinished_unqueued_dependencies_of_queued_tasks_once_each(self):
        missing = dm.missing_dependencies(self.TASKS, ["7", "9"])
        self.assertEqual([(m["gid"], m["needed_by"], m["for"]) for m in missing], [("5", "T-7", "7")])

    def test_they_go_in_just_before_the_task_that_needs_them(self):
        c = dm.empty_control()
        dm.queue_add(c, [{"gid": "6"}, {"gid": "8"}, {"gid": "9"}])
        self.assertEqual(dm.queue_insert_before(c, [{"gid": "5", "needed_by": "T-9"},
                                                    {"gid": "8"}], "9"), ["5"])
        self.assertEqual([q["gid"] for q in c["queue"]], ["6", "8", "5", "9"])
        self.assertEqual(c["queue"][2]["needed_by"], "T-9")


class TestCheckpointGate(unittest.TestCase):
    QUEUE = [{"gid": "7"}, {"gid": "8", "checkpoint": True}, {"gid": "9"},
             {"gid": "10", "checkpoint": True}, {"gid": "11"}]

    def gate(self, records=None, continued=(), tasks=None):
        gates, held = dm.checkpoint_gates(self.QUEUE, tasks or {}, records or {}, list(continued))
        return (gates.get(None) or {}).get("gid"), held

    def test_nothing_after_a_checkpoint_starts_while_it_is_still_running(self):
        self.assertEqual(self.gate({"8": {"phase": "running"}}), ("8", {"9", "10", "11"}))

    def test_merged_is_not_enough_it_waits_for_continue(self):
        self.assertEqual(self.gate({"8": {"phase": "merged"}}), ("8", {"9", "10", "11"}))

    def test_continued_moves_the_gate_to_the_next_checkpoint(self):
        self.assertEqual(self.gate({"8": {"phase": "merged"}}, ["8"]), ("10", {"11"}))

    def test_continue_before_the_merge_does_not_open_it(self):
        self.assertEqual(self.gate({}, ["8"]), ("8", {"9", "10", "11"}))

    def test_what_a_task_before_it_needs_is_never_held(self):
        tasks = {"7": {"deps": [{"ref": "11"}]}, "11": {"deps": [{"ref": "9"}]}}
        self.assertEqual(self.gate(tasks=tasks), ("8", {"10"}))

    def test_no_checkpoint_holds_nothing(self):
        self.assertEqual(dm.checkpoint_gates([{"gid": "1"}], {}, {}, []), ({}, set()))

    def test_a_checkpoint_holds_back_only_its_own_feature(self):
        queue = [{"gid": "1", "base": "f/a", "checkpoint": True}, {"gid": "2", "base": "f/b"},
                 {"gid": "3", "base": "f/a"}, {"gid": "4", "base": "f/b", "checkpoint": True},
                 {"gid": "5", "base": "f/b"}]
        gates, held = dm.checkpoint_gates(queue, {}, {}, [])
        self.assertEqual({f: g["gid"] for f, g in gates.items()}, {"f/a": "1", "f/b": "4"})
        self.assertEqual(held, {"3", "5"})

    def test_what_another_feature_needs_is_let_through(self):
        queue = [{"gid": "1", "base": "f/a", "checkpoint": True}, {"gid": "2", "base": "f/a"},
                 {"gid": "3", "base": "f/b"}]
        self.assertEqual(dm.checkpoint_gates(queue, {"3": {"deps": [{"ref": "2"}]}}, {}, [])[1],
                         set())

    def test_tasks_queued_before_features_follow_the_current_target(self):
        queue = [{"gid": "1", "checkpoint": True}, {"gid": "2", "base": None}, {"gid": "3"}]
        gates, held = dm.checkpoint_gates(queue, {}, {}, [], base="f/a")
        self.assertEqual(set(gates), {"f/a"})
        self.assertEqual(held, {"3"})

    def test_flagging(self):
        c = dm.empty_control()
        dm.queue_add(c, [{"gid": "1"}])
        dm.set_checkpoint(c, "1", True)
        self.assertTrue(c["queue"][0]["checkpoint"])
        dm.set_checkpoint(c, "1", False)
        self.assertNotIn("checkpoint", c["queue"][0])

    def test_flagged_before_queueing_it_is_a_checkpoint_once_queued(self):
        c = dm.empty_control()
        dm.set_checkpoint(c, "2", True)
        self.assertEqual(c["queue"], [])
        self.assertEqual(dm.planned_checkpoints(c), {"2"})
        dm.queue_add(c, [{"gid": "1"}, {"gid": "2"}, {"gid": "3"}])
        self.assertEqual([q.get("checkpoint") for q in c["queue"]], [None, True, None])
        self.assertEqual(c["checkpoints"], [])
        dm.set_checkpoint(c, "4", True)
        dm.set_checkpoint(c, "4", False)
        self.assertEqual(c["checkpoints"], [])

    def test_unqueueing_keeps_the_flag_but_clearing_does_not(self):
        c = dm.empty_control()
        dm.queue_add(c, [{"gid": "1"}, {"gid": "2"}])
        dm.set_checkpoint(c, "1", True)
        dm.set_checkpoint(c, "2", True)
        dm.queue_remove(c, ["1"], keep_checkpoints=True)
        dm.queue_remove(c, ["2"])
        self.assertEqual(dm.planned_checkpoints(c), {"1"})
        dm.queue_insert_before(c, [{"gid": "1"}], None)
        self.assertTrue(c["queue"][0]["checkpoint"])


class TestFeatures(unittest.TestCase):
    def test_changing_the_target_keeps_what_is_queued_where_it_was(self):
        c = dm.empty_control()
        c["base"] = "f/a"
        dm.queue_add(c, [{"gid": "1"}, {"gid": "2", "base": "f/b"}])
        dm.stamp_features(c)
        c["base"] = "f/c"
        self.assertEqual([dm.feature_of(q, c["base"]) for q in c["queue"]], ["f/a", "f/b"])

    def test_a_dependency_joins_the_feature_of_the_task_that_needs_it(self):
        c = dm.empty_control()
        dm.queue_add(c, [{"gid": "1", "base": "f/a"}, {"gid": "9", "base": "f/b"}])
        dm.queue_insert_before(c, [{"gid": "5"}], "9")
        self.assertEqual([(q["gid"], q.get("base")) for q in c["queue"]],
                         [("1", "f/a"), ("5", "f/b"), ("9", "f/b")])

    def test_runs_are_grouped_by_feature_once_there_are_two(self):
        control = {"base": "f/b", "queue": [{"gid": "1", "base": None}, {"gid": "2", "base": "f/b"},
                                            {"gid": "3", "base": None}]}
        data = {"me": {"gid": "42"},
                "tasks": {g: {"key": "A-" + g, "name": "n" + g, "completed": False,
                              "status": "Unassigned", "deps": []} for g in "123"},
                "records": {"1": {"phase": "running"}, "3": {"phase": "merged"}}}
        rows = run_rows(control, data, [], default_branch="main")
        self.assertEqual([(r["kind"], r["cols"][0]) for r in rows],
                         [("feature", "main"), ("task", "A-1"), ("task", "A-3"),
                          ("feature", "f/b"), ("task", "A-2")])
        self.assertEqual(rows[0]["cols"][1:], ["1 running · 1 merged", ""])
        self.assertEqual(rows[3]["cols"][1:], ["1 queued", "← queueing here"])

    def test_o_on_a_merged_task_opens_what_it_changed(self):
        row = {"pr_url": "https://github.com/o/r/pull/7", "links": ["https://github.com/o/r/pull/7", "t"]}
        self.assertEqual(tui.open_link(dict(row, phase="merged")), "https://github.com/o/r/pull/7/files")
        self.assertEqual(tui.open_link(dict(row, phase="pr_open")), "https://github.com/o/r/pull/7")
        self.assertEqual(tui.open_link({"phase": "merged", "links": ["t"]}), "t")

    def test_a_feature_heading_shows_its_whole_name(self):
        line = tui.fit(["feature/recruiter-queue-M5", "1 queued", ""], 100, wide=True)
        self.assertTrue(line.startswith("feature/recruiter-queue-M5  1 queued"))

    def test_hiding_done_tasks_keeps_their_count_on_the_feature_line(self):
        control = {"queue": [{"gid": "1", "base": None}, {"gid": "2", "base": None}]}
        data = {"me": {"gid": "42"},
                "tasks": {g: {"key": "A-" + g, "name": "n" + g, "completed": False,
                              "status": "Unassigned", "deps": []} for g in "12"},
                "records": {"1": {"phase": "merged"}, "2": {"phase": "running"}}}
        rows = run_rows(control, data, [], default_branch="main", hide_done=True)
        self.assertEqual([(r["kind"], r["id"]) for r in rows],
                         [("feature", "feature:"), ("task", "2")])
        self.assertEqual(rows[0]["cols"][1], "1 running · 1 merged")
        self.assertEqual(len(run_rows(control, data, [], default_branch="main")), 2)

    def test_one_feature_needs_no_heading(self):
        control = {"queue": [{"gid": "1"}, {"gid": "2", "base": None}]}
        rows = run_rows(control, {"tasks": {}, "records": {}}, [])
        self.assertEqual([r["kind"] for r in rows], ["task", "task"])


class TestCommands(unittest.TestCase):
    def test_ids_grow_and_applied_ones_are_dropped(self):
        c = dm.empty_control()
        self.assertEqual(dm.add_command(c, "stop", "1"), 1)
        self.assertEqual(dm.add_command(c, "retry", "1"), 2)
        self.assertEqual(dm.add_command(c, "stop", "2", applied=2), 3)
        self.assertEqual([x["id"] for x in c["commands"]], [3])

    def test_a_command_can_carry_what_it_needs(self):
        c = dm.empty_control()
        dm.add_command(c, "retarget", "1", base="feature/x")
        self.assertEqual(c["commands"][0], {"id": 1, "op": "retarget", "gid": "1", "base": "feature/x"})

    def test_an_id_is_never_reused_after_everything_was_applied(self):
        c = dm.empty_control()
        dm.add_command(c, "stop", "1")
        self.assertEqual(dm.add_command(c, "stop", "1", applied=5), 6)

    def test_pending_is_what_the_daemon_has_not_applied_in_order(self):
        c = {"commands": [{"id": 3, "op": "x", "gid": "a"}, {"id": 2, "op": "y", "gid": "b"},
                          {"id": 1, "op": "z", "gid": "c"}]}
        self.assertEqual([x["id"] for x in dm.pending_commands(c, 1)], [2, 3])


class TestDaemonHealth(unittest.TestCase):
    def test_busy_names_itself_and_a_wedged_loop_is_stale_even_if_beating(self):
        self.assertEqual(dm.daemon_health({"beat": 99, "loop_at": 95, "busy": ["x"]}, True, 100),
                         "busy")
        self.assertEqual(dm.daemon_health({"beat": 99, "loop_at": 0}, True, 1000), "stale")

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

    def test_work_started_from_your_own_session_or_terminal_is_yours(self):
        work = "/bin/zsh -c cd /repo/.cortex/worktrees/HCI-6+ci8-mailbox && uv run celery"
        for session in ("claude --resume 31ad", "node /usr/local/bin/claude", "-zsh"):
            rows = [(1, 0, "launchd"), (300, 1, session), (500, 300, work)]
            self.assertEqual(dm.orphan_agents(rows, self.WT, []), [], session)

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

    def test_a_goal_whose_process_died_can_carry_on(self):
        [row] = tui.goal_rows([self.goal(alive=False)])
        self.assertEqual((row["cols"][2], row["style"]), ("stopped unexpectedly — r carries on", "bad"))

    def test_done_goals_hide_with_done_tasks(self):
        goals = [self.goal(status="done", alive=False), self.goal(id="b")]
        self.assertEqual([r["goal"] for r in tui.goal_rows(goals, hide_done=True)], ["b"])

    def test_goals_come_before_the_queue_and_their_questions_are_waits(self):
        g = self.goal(awaiting={"kind": "problem", "asked_at": "t", "headline": "push refused"})
        waits = tui.goal_waits([g])
        self.assertEqual(waits["goal:%s" % g["id"]]["key"], g["id"])
        rows = tui.run_rows({"queue": []}, {}, [], waits=waits, goals=[g])
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
        rows = board_rows("100", self.SECTIONS, {"2"}, {}, "")
        self.assertEqual([(r["kind"], r["id"]) for r in rows],
                         [("section", "s1"), ("task", "m"), ("task", "1"), ("task", "2"),
                          ("section", "s2"), ("task", "3")])
        self.assertEqual(rows[0]["cols"][1], "1 open")
        self.assertIn("●", rows[3]["cols"][0])
        self.assertEqual(rows[2]["cols"][1], "done")

    def test_a_task_key_comes_before_its_name_faintly_and_can_be_filtered_on(self):
        sections = [{"gid": "s", "name": "S", "tasks": [
            {"gid": "1", "name": "Login", "key": "HRT1-7", "kind": "task"},
            {"gid": "2", "name": "Logout", "kind": "task"}]}]
        rows = board_rows("100", sections, set(), {}, "")
        self.assertEqual(rows[1]["cols"][0], "    HRT1-7 Login")
        self.assertEqual(rows[1]["cols"][0][slice(rows[1]["faint"][0], sum(rows[1]["faint"]))], "HRT1-7")
        self.assertEqual(rows[2]["cols"][0], "    Logout")
        self.assertIsNone(rows[2]["faint"])
        self.assertEqual([r["id"] for r in board_rows("100", sections, set(), {}, "hrt1-7")], ["s", "1"])

    def test_a_milestone_shows_but_its_section_does_not_queue_it(self):
        rows = board_rows("100", self.SECTIONS, set(), {}, "")
        self.assertTrue(rows[1]["milestone"])
        self.assertIn("◈", rows[1]["cols"][0])
        self.assertNotIn("m", [t["gid"] for t in rows[0]["tasks"]])

    def test_filter_keeps_matching_tasks_under_their_section(self):
        rows = board_rows("100", self.SECTIONS, set(), {}, "dto")
        self.assertEqual([r["id"] for r in rows], ["s1", "2"])

    def test_filter_on_a_section_name_keeps_all_of_it(self):
        rows = board_rows("100", self.SECTIONS, set(), {}, "m2")
        self.assertEqual([r["id"] for r in rows], ["s2", "3"])

    def test_a_task_shows_its_run_phase(self):
        rows = board_rows("100", self.SECTIONS, {"2"}, {"2": {"phase": "pr_open"}}, "dto")
        self.assertEqual(rows[1]["cols"][1], "pr_open")

    def test_hiding_done_leaves_out_completed_tasks_and_emptied_sections(self):
        sections = self.SECTIONS + [{"gid": "s3", "name": "Old", "tasks": [
            {"gid": "9", "name": "Finished", "kind": "task", "completed": True}]}]
        rows = board_rows("100", sections, set(), {}, "", hide_done=True)
        self.assertEqual([r["id"] for r in rows], ["s1", "m", "2", "s2", "3"])

    def test_a_task_says_how_many_subtasks_it_has_and_shows_them_when_open(self):
        sections = [{"gid": "s", "name": "M", "tasks": [
            {"gid": "1", "name": "Parent", "kind": "task", "subtasks": 2}]}]
        rows = board_rows("100", sections, set(), {}, "")
        self.assertEqual(rows[1]["cols"][1], "▸ 2 subtasks")
        rows = board_rows("100", sections, set(), {}, "", subtasks={"1": None})
        self.assertEqual(rows[2]["kind"], "loading")
        rows = board_rows("100", sections, {"a"}, {}, "", subtasks={"1": [
            {"gid": "a", "name": "first"}, {"gid": "b", "name": "second", "completed": True}]})
        self.assertIn("▾ 2 subtasks", rows[1]["cols"][1])
        self.assertEqual([(r["id"], r.get("parent")) for r in rows[2:]], [("a", "1"), ("b", "1")])
        self.assertIn("●", rows[2]["cols"][0])
        self.assertEqual(rows[3]["cols"][1], "done")


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
        self.assertEqual(tui.TABS[self.app.tab], "Setup")
        self.press("alt-1")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")

    def test_tab_and_shift_tab_cycle(self):
        self.press("tab", "tab")
        self.assertEqual(self.app.tab, 2)
        self.press("btab", "btab", "btab")
        self.assertEqual(self.app.tab, 3)

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

    def test_subtasks_open_with_l_queue_on_their_own_and_close_with_h(self):
        self.app.ensure_daemon = lambda: None
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
        self.press("down", "down", " ")
        self.assertEqual([q["gid"] for q in dm.read_control(self.root)["queue"]], ["u2"])
        self.press("h")
        self.assertEqual([r["id"] for r in self.app.view()], ["s", "t1", "t2"])
        self.assertEqual(self.app.selected(self.app.view())["id"], "t1")
        self.assertTrue(self.app.board)
        self.press("h")
        self.assertFalse(self.app.board)

    def test_a_board_task_can_be_flagged_as_a_checkpoint_before_it_is_queued(self):
        self.app.ensure_daemon = lambda: None
        self.press("2", "down", "enter", "down")
        self.press(":", *"checkpoint", "enter")
        control = dm.read_control(self.root)
        self.assertEqual(control["queue"], [])
        self.assertEqual(control["checkpoints"], ["t1"])
        self.assertIn("◇", self.app.view()[1]["cols"][0])
        self.press(" ")
        control = dm.read_control(self.root)
        self.assertEqual([(q["gid"], q.get("checkpoint")) for q in control["queue"]], [("t1", True)])
        self.assertEqual(control["checkpoints"], [])
        self.assertIn("◆", self.app.view()[1]["cols"][0])
        self.press(":", *"checkpoint")
        titles = [c["title"] for c in tui.palette_matches(self.app.palette["commands"],
                                                          self.app.palette["query"])]
        self.assertEqual(titles, ["one is no longer a checkpoint"])
        self.press("esc", " ")
        self.assertEqual(dm.read_control(self.root)["checkpoints"], ["t1"])
        self.assertIn("◇", self.app.view()[1]["cols"][0])

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

    def test_right_does_not_pick_the_sprint_enter_does(self):
        self.press("3", "enter")
        self.assertEqual(self.app.setup, "sprint")
        self.press("down", "right")
        self.assertIsNone(self.app.control.get("sprint"))
        self.press("enter")
        self.assertEqual(self.app.control["sprint"]["gid"], "2")
        self.assertIsNone(self.app.setup)

    def test_target_branch_is_picked_from_the_list(self):
        self.app.branches, self.app.default_branch = ["main", "release/1.2"], "main"
        self.app.branches_at = tui.time.time()
        self.press("3", "down", "enter")
        self.assertEqual(self.app.setup, "base")
        self.press("down", "enter")
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
        self.press("3", "down", "enter")

    def test_the_new_branch_row_takes_a_name_with_slashes_and_asks_first(self):
        self.new_branch_setup()
        self.press("home", "enter")
        self.assertEqual(self.app.compose["kind"], "branch")
        self.press(*"milestone/m1", "enter")
        self.assertIn("create milestone/m1 on origin from origin/main", self.app.message)
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
        self.press("3", *["down"] * 4, "enter")
        self.assertEqual(self.app.control["usage_threshold"], 80)
        self.press("down", "enter")
        self.assertEqual(self.app.control["models"], {"task": "claude-opus-5-5"})
        self.press(*["down"] * 3, "enter", "down", "enter")
        self.assertEqual(self.app.control["models"]["check"], "claude-haiku-4-5-20251001")
        self.assertEqual(self.app.control["models"]["check_effort"], "max")
        settings = tui.gl.settings_from(self.app.control)
        self.assertEqual(settings, {"model": "claude-opus-5-5", "subagent_model": "claude-sonnet-5-5",
                                    "check_model": "claude-haiku-4-5-20251001", "check_effort": "max",
                                    "threshold": 80})

    def test_merging_cycles_through_its_three_modes(self):
        self.press("3", "down", "down")
        modes = []
        for _ in range(3):
            self.press("enter")
            modes.append(self.app.control["merge_mode"])
        self.assertEqual(modes, ["always", "asked", "branches"])

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
        self.assertTrue(rows[0]["cols"][2].startswith("⚑ has questions for you: Which VPC"))
        self.assertEqual(rows[0]["style"], "warn")


class TestRowStatus(unittest.TestCase):
    NOW = None

    def setUp(self):
        import time
        lt = time.localtime()
        self.at = lambda h, m, s=0: time.mktime(lt[:3] + (h, m, s) + lt[6:9])

    def test_a_wait_with_no_headline_still_says_what_it_asks_of_you(self):
        self.assertIn("stopped on an error — reply to retry", wait_summary({"kind": "failure"}))
        self.assertIn("QA is still failing", wait_summary({"kind": "qa"}))
        self.assertIn("waiting on a reply from you", wait_summary({"kind": "?"}))

    def test_a_run_shows_its_step_what_it_waits_on_and_for_how_long(self):
        log = ["━━ 2026-10-02 10:00:00 · start-task ━━", "10:00:00  Fetching task", "  HCI-1 — x",
               "10:01:00  Implementing", "  implement: calling claude-cli"]
        step = tui.last_step(log, self.at(10, 13))
        self.assertEqual(step[:2], ("Implementing", "agent at work"))
        self.assertEqual(round(step[2]), 12 * 60)

    def test_a_finished_call_is_no_longer_at_work(self):
        log = ["10:01:00  Implementing", "  implement: calling claude-cli",
               "  implement: claude-cli · claude-opus-5 · 29 turns · 397.8s"]
        self.assertIsNone(tui.last_step(log, self.at(10, 9))[1])

    def test_qa_shows_the_gate_still_running(self):
        log = ["10:01:00  QA", "  backend: make verify", "  backend ok",
               "  frontend: [ -d node_modules ] || npm ci; npm run verify (in apps/frontend)"]
        self.assertEqual(tui.last_step(log, self.at(10, 4))[1],
                         "[ -d node_modules ] || npm ci; npm run verify")

    def test_a_pending_command_comes_first_then_the_daemons_work_then_the_run(self):
        pending = [{"id": 9, "op": "retarget", "gid": "1", "base": "feature/m1"}]
        self.assertEqual(tui.row_activity({"phase": "pr_open"}, pending, None, None, 0),
                         "base branch change to feature/m1 asked — waiting for the daemon")
        self.assertEqual(tui.row_activity({"phase": "pr_open"}, [], "removing HCI-1's worktree",
                                          None, 0), "removing HCI-1's worktree…")
        running = tui.row_activity({"phase": "running"}, [], None,
                                   ["10:01:00  Shipping"], self.at(10, 2))
        self.assertEqual(running, "running — Shipping · 1m")
        self.assertIsNone(tui.row_activity({"phase": "pr_open"}, [], None, None, 0))

    def test_a_revising_row_says_what_it_is_revising(self):
        status = tui.row_activity({"phase": "revising", "revise_why": "fixing failing checks (e2e), to merge"},
                                  [], None, ["10:01:00  Applying the feedback",
                                             "  revise: calling claude-cli"], self.at(10, 4))
        self.assertEqual(status, "revising: fixing failing checks (e2e) — Applying the feedback · "
                                 "agent at work · 3m")

    def test_a_run_sitting_out_a_limit_says_so_and_when_it_resumes(self):
        import time
        until = self.at(21, 11)
        status = tui.row_activity({"phase": "revising"}, [], None, ["18:08:00  Applying the feedback"],
                                  self.at(18, 9), {"reason": "You've hit your session limit", "until": until})
        self.assertEqual(status, "paused — You've hit your session limit · resumes by itself at 21:11")

    def test_a_running_row_shows_the_tokens_so_far(self):
        status = tui.row_activity({"phase": "running"}, [], None, ["10:01:00  QA"], self.at(10, 2),
                                  usage={"input": 0, "output": 400, "cache_read": 12000, "cache_write": 0})
        self.assertEqual(status, "running — QA · 1m · 12.4k tokens so far")

    def test_rows_use_it_and_an_open_pr_says_what_it_waits_for(self):
        control = {"queue": [{"gid": "1"}, {"gid": "2"}]}
        data = {"tasks": {"1": {"key": "A-1", "name": "one", "deps": []},
                          "2": {"key": "A-2", "name": "two", "deps": []}},
                "records": {"1": {"phase": "pr_open"}, "2": {"phase": "pr_open"}}}
        rows = run_rows(control, data, [], activity={"2": "changing A-2's PR base branch…"})
        self.assertEqual(rows[0]["cols"][2], "PR open — waiting for review; m merges")
        self.assertEqual(rows[1]["cols"][2], "changing A-2's PR base branch…")


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
        self.press("ctrl-a", "ctrl-k", *"use nonprod", "alt-b", "ctrl-k")
        self.assertEqual(self.app.compose["text"], "use ")
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

    def test_the_palette_moves_a_pr_counting_what_it_brings_then_asking(self):
        st.State(self.root, "A-2").write("context.json", {"git": {
            "branch": "A-2/x", "base": "origin/main", "pr_url": "https://github.com/o/r/pull/7"}})
        with dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        self.app.snapshot()
        seen = []
        tui.extra_commits, saved = (lambda root, branch, old, new: seen.append((branch, old, new)) or 0,
                                    tui.extra_commits)
        self.addCleanup(setattr, tui, "extra_commits", saved)
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index("2")
        self.press(":", *"move", "enter")
        for _ in range(100):
            self.app.sync()
            if self.app.confirm:
                break
            tui.time.sleep(0.01)
        self.assertEqual(seen, [("A-2/x", "main", "feature/m1")])
        self.assertIn("move A-2's PR from main onto feature/m1? (y/n)", self.app.message)
        self.press("y")
        self.assertEqual(self.app.control["commands"][-1],
                         {"id": 1, "op": "retarget", "gid": "2", "base": "feature/m1"})

    def palette_titles(self):
        return [c["title"] for c in tui.palette_matches(self.app.palette["commands"],
                                                        self.app.palette["query"])]

    def select(self, gid):
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index(gid)

    def test_the_palette_has_only_what_no_key_below_does(self):
        st.State(self.root, "A-2").write("context.json", {"git": {"base": "origin/main"}})
        with dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        self.app.snapshot()
        self.select("2")
        self.press(":")
        self.assertEqual(self.palette_titles(),
                         ["Change A-2's PR base branch to feature/m1", "Make A-2 a checkpoint",
                          "Undo A-2", "Hide done tasks",
                          "Start this repo's daemon"])

    def test_c_continues_past_a_merged_checkpoint(self):
        with dm.control_file(self.root) as c:
            dm.set_checkpoint(c, "2", True)
        state = dm.read_json(os.path.join(dm.queue_dir(self.root), "state.json"))
        state["records"]["2"] = {"phase": "merged"}
        dm.write_json(os.path.join(dm.queue_dir(self.root), "state.json"), state)
        self.app.snapshot()
        self.press("c")
        self.assertIn("continue past checkpoint A-2", self.app.message)
        self.press("y")
        self.assertEqual(self.app.control["commands"][-1], {"id": 1, "op": "continue", "gid": "2"})

    def test_c_does_nothing_before_the_checkpoint_merged(self):
        with dm.control_file(self.root) as c:
            dm.set_checkpoint(c, "2", True)
        self.app.snapshot()
        self.press("c")
        self.assertFalse(self.app.control.get("commands"))

    def test_c_on_a_held_back_task_offers_to_drop_the_checkpoint(self):
        with dm.control_file(self.root) as c:
            dm.set_checkpoint(c, "1", True)
        self.app.snapshot()
        self.select("2")
        self.press("c")
        self.assertIn("checkpoint A-1 has not merged yet — drop it", self.app.message)
        self.press("y")
        self.assertFalse(dm.planned_checkpoints(dm.read_control(self.root)))

    def test_a_stopped_checkpoint_can_still_be_dropped(self):
        with dm.control_file(self.root) as c:
            dm.set_checkpoint(c, "2", True)
        state = dm.read_json(os.path.join(dm.queue_dir(self.root), "state.json"))
        state["records"]["2"] = {"phase": "stopped"}
        dm.write_json(os.path.join(dm.queue_dir(self.root), "state.json"), state)
        self.app.snapshot()
        self.select("2")
        self.press(":", *"checkpoint")
        self.assertEqual(self.palette_titles(), ["A-2 is no longer a checkpoint"])

    def test_it_is_found_by_the_words_you_would_use(self):
        st.State(self.root, "A-2").write("context.json", {"git": {"base": "origin/main"}})
        with dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        self.app.snapshot()
        self.select("2")
        for query in ("branch", "retarget", "update", "move pr"):
            self.press(":", *query)
            self.assertEqual(self.palette_titles()[:1], ["Change A-2's PR base branch to feature/m1"],
                             query)
            self.press("esc")

    def test_a_pr_already_on_the_target_offers_no_move(self):
        st.State(self.root, "A-2").write("context.json", {"git": {"base": "origin/feature/m1"}})
        with dm.control_file(self.root) as c:
            c["base"] = "feature/m1"
        self.app.snapshot()
        self.select("2")
        self.press(":")
        self.assertNotIn("base branch", " ".join(self.palette_titles()))

    def test_typing_in_the_palette_does_not_trigger_hotkeys(self):
        self.press(":", *"xq2m")
        self.assertEqual(self.app.palette["query"], "xq2m")
        self.assertEqual(tui.TABS[self.app.tab], "Runs")
        self.assertEqual(self.app.control.get("commands") or [], [])
        self.press("esc")
        self.assertIsNone(self.app.palette)

    def test_the_palette_line_takes_editing_keys(self):
        self.press(":", *"daemon", "ctrl-a", "ctrl-k")
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
        self.press("1", "home", "enter")
        self.assertEqual(self.app.goal_view, gid)
        lines = self.frame()
        self.assertIn("Runs › goal A-9 Queue", lines[2])
        self.assertTrue(any("No call has started yet." in l for l in lines))
        self.press("l")
        self.assertEqual(self.app.log_path, tui.gl.Goal(self.root, gid).log)
        self.press("esc")
        self.assertEqual((self.app.log_path, self.app.goal_view), (None, gid))
        self.press("esc")
        self.assertIsNone(self.app.goal_view)

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

    def finished_setup(self):
        path = os.path.join(dm.queue_dir(self.root), "state.json")
        data = dm.read_json(path)
        data["records"]["2"] = {"phase": "merged", "actual_hours": 0.5}
        dm.write_json(path, data)
        self.app.snapshot()

    def test_x_on_a_finished_task_only_removes_it(self):
        self.finished_setup()
        self.select("2")
        self.press("x")
        self.assertIsNone(self.app.confirm)
        self.assertEqual([q["gid"] for q in self.app.control["queue"]], ["1"])
        self.assertEqual(self.app.control.get("commands") or [], [])

    def test_x_on_a_live_task_still_stops_it_after_asking(self):
        self.select("1")
        self.press("x")
        self.assertIn("stop and unqueue", self.app.message)

    def test_the_palette_clears_every_finished_task_at_once(self):
        self.finished_setup()
        self.press(":", *"clear", "enter")
        self.assertEqual([q["gid"] for q in self.app.control["queue"]], ["1"])
        self.assertEqual(self.app.control.get("commands") or [], [])
        self.assertIn("removed A-2 from the list", self.app.message)

    def test_undo_says_what_it_will_do_and_asks_first(self):
        st.State(self.root, "A-2").write("context.json", {"git": {
            "branch": "A-2/x", "base": "origin/main", "worktree": "/wt"}})
        self.app.snapshot()
        self.select("2")
        self.press(":", *"undo", "enter")
        self.assertIn("undo A-2: close its PR and delete the branch, remove its worktree and "
                      "saved state, take it off the sprint and unassign it? (y/n)", self.app.message)
        self.assertEqual(self.app.control.get("commands") or [], [])
        self.press("y")
        self.assertEqual(self.app.control["commands"][-1]["op"], "undo")

    def test_undoing_a_merged_task_offers_a_revert_and_warns_of_started_dependents(self):
        path = os.path.join(dm.queue_dir(self.root), "state.json")
        data = dm.read_json(path)
        data["records"]["2"] = {"phase": "merged", "pr_url": "https://github.com/o/r/pull/7"}
        data["tasks"]["1"]["deps"] = [{"ref": "2", "completed": True}]
        data["records"]["1"]["phase"] = "running"
        dm.write_json(path, data)
        st.State(self.root, "A-2").write("context.json", {"git": {"base": "origin/feature/m1"}})
        self.app.snapshot()
        self.select("2")
        self.press(":", *"revert", "enter")
        self.assertIn("open a PR reverting it from feature/m1 (it waits for you to merge it)",
                      self.app.message)
        self.assertIn("A-1, which waits on it, already started", self.app.message)

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
        self.assertIn("a to say what to do, m to just try again", wait_summary(self.app.waits["2"]))

    def test_a_merge_that_went_through_anyway_waits_on_nothing(self):
        path = os.path.join(dm.queue_dir(self.root), "state.json")
        data = dm.read_json(path)
        data["records"]["2"].update(phase="merged", merge={"blocked": "gh pr merge refused: timed out"})
        dm.write_json(path, data)
        self.app.snapshot()
        self.assertNotIn("2", self.app.waits)

    def test_a_on_a_blocked_merge_sends_your_instructions(self):
        path = os.path.join(dm.queue_dir(self.root), "state.json")
        data = dm.read_json(path)
        data["records"]["2"]["merge"] = {"blocked": "checks still failing after 2 fix(es): verify"}
        dm.write_json(path, data)
        self.app.snapshot()
        self.select("2")
        self.press("a", *"bump source-map-js with npm audit fix", "enter")
        self.assertEqual(self.app.control["commands"][-1],
                         {"id": 1, "op": "instruct", "gid": "2",
                          "text": "bump source-map-js with npm audit fix"})

    def test_a_on_a_parked_conflict_asks_then_requests_a_resolve(self):
        asked = []
        self.app.resolve = lambda gid, url: asked.append((gid, url))
        rows = self.app.view()
        self.app.cursor["Runs"] = [r["id"] for r in rows].index("2")
        self.press("a")
        self.assertIn("please resolve", self.app.message)
        self.press("y")
        self.assertEqual(asked, [("2", "https://github.com/o/r/pull/7")])


class TestCodeVersion(unittest.TestCase):
    def test_changes_when_a_file_changes(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "engine.py")
        with open(path, "w") as f:
            f.write("x")
        before = dm.code_version([path])
        self.assertEqual(dm.code_version([path]), before)
        os.utime(path, ns=(1, 1))
        self.assertNotEqual(dm.code_version([path]), before)


class TestCommandFeedback(unittest.TestCase):
    SENT = {"id": 4, "op": "merge", "key": "HCI-26", "at": 100}

    def test_applied_and_understood(self):
        self.assertEqual(dm.command_feedback(self.SENT, 4, [{"id": 4, "ok": True}], True, 101),
                         ("merging HCI-26 — the Runs tab shows each step", True))

    def test_applied_but_not_understood_says_so(self):
        message, settled = dm.command_feedback(
            self.SENT, 4, [{"id": 4, "ok": False, "note": "this daemon does not know 'merge'"}],
            True, 101)
        self.assertTrue(settled)
        self.assertIn("did not act on merge for HCI-26", message)

    def test_a_busy_daemon_says_what_it_is_doing(self):
        message, settled = dm.command_feedback(self.SENT, 3, [], True, 130,
                                               ["removing HCI-26's worktree"])
        self.assertFalse(settled)
        self.assertIn("busy (removing HCI-26's worktree) — merge for HCI-26 is next", message)

    def test_waiting_then_overdue_then_no_daemon(self):
        self.assertEqual(dm.command_feedback(self.SENT, 3, [], True, 101),
                         ("merge asked for HCI-26…", False))
        self.assertIn("has not picked up", dm.command_feedback(self.SENT, 3, [], True, 130)[0])
        self.assertIn("not running", dm.command_feedback(self.SENT, 3, [], False, 101)[0])


class TestUnknownCommands(unittest.TestCase):
    def test_a_command_the_daemon_does_not_know_is_recorded_not_dropped(self):
        import subprocess
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        with dm.control_file(root) as c:
            dm.add_command(c, "frobnicate", "1")
            dm.add_command(c, "merge-cancel", "1")
        run = dm.QueueRun(root, [])
        run.apply_control()
        self.assertEqual(run.data["applied"], 2)
        self.assertEqual([(r["id"], r["ok"]) for r in run.data["results"]], [(1, False), (2, True)])


class TestContinue(unittest.TestCase):
    def test_continue_is_remembered_and_lifts_the_hold(self):
        import subprocess
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        run = dm.QueueRun(root, [])
        run.refresh = lambda only=None: None
        run.data["tasks"] = {"1": {"key": "A-1", "deps": []}, "2": {"key": "A-2", "deps": []}}
        with dm.control_file(root) as c:
            dm.queue_add(c, [{"gid": "1"}, {"gid": "2"}])
            dm.set_checkpoint(c, "1", True)
        run.apply_control()
        run.records["1"] = {"phase": "merged"}
        self.assertEqual(run.held_back(), {"2"})
        with dm.control_file(root) as c:
            dm.add_command(c, "continue", "1")
        run.apply_control()
        self.assertEqual(run.data["continued"], ["1"])
        self.assertEqual(run.held_back(), set())


class TestPullInDependencies(unittest.TestCase):
    def test_queueing_a_task_queues_its_whole_open_tree_ahead_of_it(self):
        import subprocess
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        asana = {"9": {"key": "T-9", "deps": [{"ref": "5", "name": "five", "completed": False}]},
                 "5": {"key": "T-5", "deps": [{"ref": "3", "name": "three", "completed": False},
                                              {"ref": "2", "name": "two", "completed": True}]},
                 "3": {"key": "T-3", "deps": []},
                 "1": {"key": "T-1", "deps": []}}
        run = dm.QueueRun(root, [])

        def refresh(only=None):
            for gid in (only or [q["gid"] for q in run.control["queue"]]):
                run.data["tasks"][gid] = asana[gid]
        run.refresh = refresh
        with dm.control_file(root) as c:
            dm.queue_add(c, [{"gid": "1"}, {"gid": "9"}])
        run.apply_control()
        queue = dm.read_control(root)["queue"]
        self.assertEqual([q["gid"] for q in queue], ["1", "3", "5", "9"])
        self.assertEqual([q.get("needed_by") for q in queue], [None, "T-5", "T-9", None])


class TestQueueingDoesNotRelaunch(unittest.TestCase):
    def test_a_run_just_launched_is_not_started_again_when_more_is_queued(self):
        import subprocess
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        run = dm.QueueRun(root, [])
        run.refresh = lambda only=None: run.data["tasks"].update(
            {g: {"key": "A-" + g, "deps": []} for g in (only or [])})
        with dm.control_file(root) as c:
            dm.queue_add(c, [{"gid": "1"}])
        run.apply_control()
        proc = subprocess.Popen(["sleep", "5"])
        self.addCleanup(proc.kill)
        run.children["1"] = proc
        run.records["1"] = {"phase": "running", "pid": proc.pid, "since": 1}
        with dm.control_file(root) as c:
            dm.queue_add(c, [{"gid": "2"}])
        run.apply_control()
        self.assertEqual(run.records["1"], {"phase": "running", "pid": proc.pid, "since": 1})


class TestRunRowsCheckpoint(unittest.TestCase):
    def test_held_back_tasks_say_which_checkpoint_holds_them(self):
        control = {"queue": [{"gid": "1", "checkpoint": True}, {"gid": "2"},
                             {"gid": "3", "needed_by": "A-2"}]}
        data = {"me": {"gid": "42"}, "sprint": {"gid": "s"},
                "tasks": {g: {"key": "A-" + g, "name": "n" + g, "completed": False,
                              "status": "Unassigned", "deps": []} for g in "123"},
                "records": {"1": {"phase": "running"}}}
        rows = run_rows(control, data, [])
        self.assertEqual(rows[0]["cols"][1], "◆ n1")
        self.assertEqual(rows[1]["cols"][2], "held back until checkpoint A-1")
        self.assertEqual(rows[2]["cols"][2], "held back until checkpoint A-1 · queued for A-2")


class TestSetup(unittest.TestCase):
    def test_rows_say_what_is_set(self):
        rows = setup_rows({"sprint": {"name": "Sprint 26/2"}, "base": None, "merge_mode": "always"},
                          "main")
        self.assertEqual([r["cols"][0] for r in rows],
                         ["Sprint", "Queue into", "Merging", "Done tasks", "Usage limit", "Task model", "Goal lead",
                          "Goal sub-agents", "Goal checker", "Checker effort"])
        self.assertEqual([r["cols"][1].split(" — ")[0] for r in rows[4:]],
                         ["75%", "sonnet", "opus", "sonnet", "fable", "xhigh"])
        self.assertEqual(rows[1]["cols"][1], "the default branch (main)")
        self.assertIn("always", rows[2]["cols"][1])
        self.assertEqual(setup_rows({}, None)[0]["style"], "warn")

    def test_a_model_row_moves_to_the_next_choice(self):
        self.assertEqual(tui.next_setting("model-task", "claude-sonnet-5-5"), "claude-opus-5-5")
        self.assertEqual(tui.next_setting("model-task", "claude-fable-5-1"), "claude-haiku-4-5-20251001")
        self.assertEqual(tui.next_setting("effort-check", "xhigh"), "max")
        self.assertEqual(tui.next_setting("effort-check", "max"), "low")

    def test_merging_defaults_to_the_recommended_mode(self):
        for control in ({}, {"merge_mode": "never"}):
            self.assertIn("unless it targets the default branch (recommended)",
                          setup_rows(control, "main")[2]["cols"][1])

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

    def test_features_with_work_come_first_and_say_how_they_stand(self):
        rows = branch_rows(["main", "develop", "f/x"], "main", "", "f/x",
                           {"f/x": "2 running", "main": "1 merged"})
        self.assertEqual([r["id"] for r in rows], ["+new", "f/x", "main", "develop"])
        self.assertEqual(rows[1]["cols"][1], "2 running · ← queueing here")
        self.assertEqual(rows[2]["cols"][1], "default · 1 merged")

    def test_queueing_goes_into_the_active_feature_and_switching_moves_nothing(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        isolate_cache(self)
        with dm.control_file(root) as c:
            dm.queue_add(c, [{"gid": "1", "board": "9", "name": "one"}])
        app = App(root, [])
        app.ensure_daemon = lambda: None
        app.default_branch = "main"
        app.set_base("feature/b")
        app.queue([{"gid": "2", "board": "9", "name": "two"}])
        app.set_base("main")
        app.queue([{"gid": "3", "board": "9", "name": "three"}])
        queue = dm.read_control(root)["queue"]
        self.assertEqual([(q["gid"], q["base"]) for q in queue],
                         [("1", None), ("2", "feature/b"), ("3", None)])

    def test_the_daemon_launches_each_task_onto_its_own_feature(self):
        import subprocess
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        with dm.control_file(root) as c:
            c["base"] = "feature/b"
            dm.queue_add(c, [{"gid": "1"}, {"gid": "2", "base": None}, {"gid": "3", "base": "feature/a"}])
        run = dm.QueueRun(root, [])
        run.control = dm.read_control(root)
        self.assertEqual([run.launch_base(g) for g in "123"], ["feature/b", None, "feature/a"])

    def test_branch_names(self):
        for good in ("release/1.2", "milestone-m1", "HGM-1/x"):
            self.assertTrue(valid_branch_name(good), good)
        for bad in ("", "-x", "a..b", "a b", "x.lock", "a//b", "/x", "x/"):
            self.assertFalse(valid_branch_name(bad), bad)


class TestExtraCommits(unittest.TestCase):
    """Moving a PR to another base can drag in commits the old base had and the
    new one does not; that has to be counted before anyone says yes."""

    def git(self, cwd, *args):
        import subprocess
        subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True)

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        origin, work = os.path.join(self.root, "o.git"), os.path.join(self.root, "w")
        self.git(self.root, "init", "-q", "--bare", "-b", "main", origin)
        self.git(self.root, "clone", "-q", origin, work)
        for args in (["commit", "--allow-empty", "-qm", "c1"], ["push", "-q", "origin", "main"],
                     ["push", "-q", "origin", "main:feature/old"],
                     ["push", "-q", "origin", "main:feature/same"],
                     ["commit", "--allow-empty", "-qm", "c2 on main"], ["push", "-q", "origin", "main"],
                     ["push", "-q", "origin", "main:feature/same"],
                     ["checkout", "-qb", "task"], ["commit", "--allow-empty", "-qm", "c3 the task"],
                     ["push", "-q", "origin", "task"]):
            self.git(work, *args)
        self.work = work

    def test_a_base_behind_the_old_one_brings_its_commits(self):
        self.assertEqual(tui.extra_commits(self.work, "task", "main", "feature/old"), 1)

    def test_a_base_level_with_the_old_one_brings_nothing(self):
        self.assertEqual(tui.extra_commits(self.work, "task", "main", "feature/same"), 0)


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

    def test_palette_commands_and_checkpoints_are_explained(self):
        text = " ".join(t for _, t, _ in tui.help_lines(100, "Runs"))
        for words in ("Checkpoints", "Make HCI-8 a checkpoint", "Undo HCI-8", "Queue into"):
            self.assertIn(words, text)

    def test_keys_and_text_are_separate_columns_and_long_text_wraps_under_itself(self):
        lines = tui.help_lines(60, "Runs")
        merge = [i for i, (k, t, s) in enumerate(lines) if k == "m"][0]
        self.assertTrue(lines[merge][1].startswith("merge:"))
        self.assertEqual(lines[merge + 1][0], "")          # the wrap has no key of its own
        self.assertTrue(all(len(t) <= 60 - tui.HELP_KEYS_WIDTH - 6
                            for _, t, style in lines if style != "bold"))


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
