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

    def test_user_filter_keeps_unassigned_and_own_drops_others(self):
        payload = {"tasks": [
            {"ref": "a", "name": "A", "index": 0, "priority": "P0", "assignee": {"ref": "u2", "name": "Other"}},
            {"ref": "b", "name": "B", "index": 1, "priority": "P1", "assignee": None},
            {"ref": "c", "name": "C", "index": 2, "priority": "P2", "assignee": {"ref": "u1", "name": "Me"}},
            {"ref": "d", "name": "D", "index": 3, "priority": "P3", "assignee": "u2"},
        ], "priority_order": ["P0", "P1", "P2", "P3"]}
        code, out, err = self.run_cmd(["order", "--user", "u1", "--from-json", "-"], stdin=json.dumps(payload))
        self.assertEqual(code, 0, err)
        self.assertEqual([t["ref"] for t in json.loads(out)], ["b", "c"])

    def test_without_user_flag_assignee_is_ignored(self):
        payload = {"tasks": [
            {"ref": "a", "name": "A", "index": 0, "priority": "P0", "assignee": {"ref": "u2"}},
            {"ref": "b", "name": "B", "index": 1, "priority": "P1", "assignee": None},
        ], "priority_order": ["P0", "P1"]}
        code, out, _ = self.run_cmd(["order", "--from-json", "-"], stdin=json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual([t["ref"] for t in json.loads(out)], ["a", "b"])

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

    def test_in_review_by_ref_blocks(self):
        r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": [
            {"board": {"ref": "b3", "name": "agent"}, "column": {"ref": "c4", "name": "Pending PR Review"}}]}])
        self.assertFalse(r["pass"])
        self.assertIn("Pending PR Review", r["blocking"][0]["reason"])

    def test_in_review_by_name_on_other_board_blocks(self):
        r = self.gate([{"ref": "x", "name": "X", "completed": False, "memberships": [
            {"board": {"ref": "team", "name": "ENG | Sprint 26.16"}, "column": {"ref": "zz", "name": "Pending PR Review"}}]}])
        self.assertFalse(r["pass"])

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


    def test_open_milestone_work_item_blocks_until_completed(self):
        open_item = {"ref": "s", "name": "S", "completed": False, "memberships": []}
        self.assertFalse(self.gate([open_item])["pass"])
        self.assertTrue(self.gate([dict(open_item, completed=True)])["pass"])


ME = {"ref": "u1", "name": "Me"}
OTHER = {"ref": "u2", "name": "Other"}


def item(ref, created, completed=False, assignee=None, marker=None):
    return {"ref": ref, "name": ref.upper(), "created_at": created, "completed": completed,
            "assignee": assignee, "marker": marker}


class MarkerTest(AgentLoopCase):
    def marker(self, comments):
        code, out, err = self.run_cmd(["marker", "--from-json", "-"], stdin=json.dumps(comments))
        self.assertEqual(code, 0, err)
        return json.loads(out)["marker"]

    def test_latest_step_naming_comment_wins_by_created_at(self):
        comments = [
            {"text": "🤖 [AGENT] Ready for review\nPR: https://x/1", "created_at": "2026-01-02T00:00:00Z"},
            {"text": "🤖 [AGENT] started", "created_at": "2026-01-01T00:00:00Z"},
        ]
        self.assertEqual(self.marker(comments), "ready_for_review")

    def test_human_and_unknown_bot_comments_name_no_step(self):
        comments = [
            {"text": "🤖 [AGENT] Needs clarification\n1. which?", "created_at": "2026-01-01T00:00:00Z"},
            {"text": "Answered: use the old one", "created_at": "2026-01-02T00:00:00Z"},
            {"text": "🤖 [AGENT] note to self", "created_at": "2026-01-03T00:00:00Z"},
        ]
        self.assertEqual(self.marker(comments), "needs_clarification")

    def test_each_marker_maps_to_its_step(self):
        cases = {
            "🤖 [AGENT] rework started": "started",
            "🤖 [AGENT] previous run was interrupted — resuming": "started",
            "🤖 [AGENT] Blocked — run stopped": "blocked",
            "🤖 [REVIEW] started · PR: u": "review_started",
            "🤖 [REVIEW] Merged into milestone/x": "merged",
            "🤖 [REVIEW] Changes requested": "changes_requested",
            "🤖 [REVIEW] Blocked — no way": "blocked",
        }
        for text, step in cases.items():
            self.assertEqual(self.marker([{"text": text}]), step, text)

    def test_no_comments_is_no_marker(self):
        self.assertIsNone(self.marker([]))


class CandidatesTest(AgentLoopCase):
    def candidates(self, payload, kind, user="u1"):
        code, out, err = self.run_cmd(["candidates", "--user", user, "--for", kind, "--from-json", "-"],
                                      stdin=json.dumps(payload))
        self.assertEqual(code, 0, err)
        return [c["ref"] for c in json.loads(out)]

    PAYLOAD = {
        "priority_order": ["P0", "P1", "P2"],
        "tasks": [
            {"ref": "t-p2", "name": "T", "index": 0, "priority": "P2", "assignee": None},
            {"ref": "t-p0", "name": "T", "index": 1, "priority": "P0", "assignee": None},
            {"ref": "t-other", "name": "T", "index": 2, "priority": "P0", "assignee": OTHER},
        ],
        "milestones": [
            {"ref": "mq", "name": "Queued", "role": "queue", "index": 3, "priority": "P1", "executor": "Agent",
             "subtasks": [item("q2", "2026-01-02"), item("q1", "2026-01-01")]},
            {"ref": "mp", "name": "Started", "role": "in_progress", "index": 0, "priority": None, "executor": "Agent",
             "subtasks": [item("p-done", "2026-01-01", completed=True),
                          item("p-held", "2026-01-02", assignee=OTHER, marker="started"),
                          item("p-open", "2026-01-03")]},
            {"ref": "mh", "name": "Human", "role": "queue", "index": 4, "priority": "P0", "executor": "Human",
             "subtasks": [item("h1", "2026-01-01")]},
        ],
    }

    def test_build_order_started_milestones_then_column_by_priority(self):
        self.assertEqual(self.candidates(self.PAYLOAD, "build"), ["p-open", "t-p0", "q1", "q2", "t-p2"])

    def test_build_takes_only_open_unassigned_work_items(self):
        payload = {"tasks": [], "milestones": [
            {"ref": "m", "name": "M", "role": "in_progress", "executor": "agent", "subtasks": [
                item("mine", "1", assignee=ME, marker="changes_requested"),
                item("done", "2", completed=True),
                item("free", "3", marker="changes_requested")]}]}
        self.assertEqual(self.candidates(payload, "build"), ["free"])

    def test_orphan_takes_own_held_items_with_no_verdict(self):
        payload = {"tasks": [{"ref": "t-mine", "name": "T", "index": 0, "assignee": ME},
                             {"ref": "t-other", "name": "T", "index": 1, "assignee": OTHER}],
                   "milestones": [{"ref": "m", "name": "M", "role": "in_progress", "executor": "Agent", "subtasks": [
                       item("started", "1", assignee=ME, marker="started"),
                       item("claimed", "2", assignee=ME),
                       item("shipped", "3", assignee=ME, marker="ready_for_review"),
                       item("theirs", "4", assignee=OTHER, marker="started"),
                       item("free", "5")]}]}
        self.assertEqual(self.candidates(payload, "orphan"), ["started", "claimed", "t-mine"])

    def test_review_takes_ready_for_review_items_mine_or_unassigned(self):
        payload = {"tasks": [{"ref": "t-rev", "name": "T", "index": 0, "assignee": None}],
                   "milestones": [{"ref": "m", "name": "M", "role": "in_progress", "executor": "Agent", "subtasks": [
                       item("r-mine", "1", assignee=ME, marker="ready_for_review"),
                       item("r-flight", "2", assignee=ME, marker="review_started"),
                       item("r-theirs", "3", assignee=OTHER, marker="ready_for_review"),
                       item("blocked", "4", assignee=ME, marker="blocked"),
                       item("merged", "5", completed=True, marker="merged")]}]}
        self.assertEqual(self.candidates(payload, "review"), ["r-mine", "r-flight", "t-rev"])

    def test_candidate_names_its_milestone(self):
        code, out, _ = self.run_cmd(["candidates", "--user", "u1", "--for", "build", "--from-json", "-"],
                                    stdin=json.dumps(self.PAYLOAD))
        first = json.loads(out)[0]
        self.assertEqual(first["milestone"], {"ref": "mp", "name": "Started"})
        single = [c for c in json.loads(out) if c["ref"] == "t-p0"][0]
        self.assertIsNone(single["milestone"])

    def test_unknown_kind_exits_1(self):
        code, _, _ = self.run_cmd(["candidates", "--user", "u1", "--for", "lane", "--from-json", "-"], stdin="{}")
        self.assertEqual(code, 1)


class AggregateTest(AgentLoopCase):
    def role(self, subtasks):
        code, out, err = self.run_cmd(["aggregate", "--from-json", "-"], stdin=json.dumps({"subtasks": subtasks}))
        self.assertEqual(code, 0, err)
        return json.loads(out)["role"]

    def test_none_held_is_ready_to_execute(self):
        self.assertEqual(self.role([item("a", "1"), item("b", "2")]), "queue")
        self.assertEqual(self.role([]), "queue")
        self.assertEqual(self.role([item("a", "1", completed=True), item("b", "2", marker="changes_requested")]), "queue")

    def test_any_held_is_in_progress(self):
        self.assertEqual(self.role([item("a", "1", assignee=ME, marker="ready_for_review"), item("b", "2")]),
                         "in_progress")

    def test_held_needs_clarification_or_blocked_is_needs_input(self):
        for marker in ("needs_clarification", "blocked"):
            self.assertEqual(self.role([item("a", "1", assignee=ME, marker=marker),
                                        item("b", "2", completed=True)]), "blocked", marker)

    def test_released_after_an_answer_is_not_needs_input(self):
        self.assertEqual(self.role([item("a", "1", marker="needs_clarification"),
                                    item("b", "2", assignee=ME, marker="started")]), "in_progress")

    def test_all_complete_is_ready_for_qa(self):
        self.assertEqual(self.role([item("a", "1", completed=True), item("b", "2", completed=True)]), "ready")


DESCRIPTION = """## Source
Something.

## Cards
| Ref | Title | Repo | State | PR |
|---|---|---|---|---|
| 1 | First | org/a | waiting |  |
| 2 | Second | org/b | waiting |  |

## Closing
Done when merged."""


class CardsTest(AgentLoopCase):
    def cards(self, description, row):
        code, out, err = self.run_cmd(["cards", "--from-json", "-"],
                                      stdin=json.dumps({"description": description, "row": row}))
        self.assertEqual(code, 0, err)
        return out

    def test_updates_named_columns_of_one_row_and_keeps_the_rest(self):
        out = self.cards(DESCRIPTION, {"ref": "2", "state": "in review", "pr": "https://x/9"})
        self.assertIn("| 2 | Second | org/b | in review | https://x/9 |", out)
        self.assertIn("| 1 | First | org/a | waiting |  |", out)
        self.assertTrue(out.startswith("## Source"))
        self.assertIn("## Closing\nDone when merged.", out)

    def test_unknown_ref_appends_a_row_inside_the_table(self):
        out = self.cards(DESCRIPTION, {"ref": "3", "title": "Third", "repo": "org/c", "state": "waiting"})
        lines = out.split("\n")
        self.assertEqual(lines[lines.index("| 2 | Second | org/b | waiting |  |") + 1],
                         "| 3 | Third | org/c | waiting |  |")

    def test_missing_section_is_created_at_the_end(self):
        out = self.cards("## Source\nX", {"ref": "1", "title": "T", "repo": "org/a", "state": "waiting"})
        self.assertTrue(out.endswith("## Cards\n| Ref | Title | Repo | State | PR |\n|---|---|---|---|---|\n"
                                     "| 1 | T | org/a | waiting |  |\n"))

    def test_row_without_ref_exits_1(self):
        code, _, _ = self.run_cmd(["cards", "--from-json", "-"], stdin=json.dumps({"description": "", "row": {}}))
        self.assertEqual(code, 1)


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

    def test_kind_review_writes_separate_file(self):
        self.seed()
        code, _, err = self.run_cmd(["last-run", "asana", "start", "--kind", "review"])
        self.assertEqual(code, 0, err)
        code, out, err = self.run_cmd(["last-run", "asana", "write", "ready", "--kind", "review", "--task", "t2"])
        self.assertEqual(code, 0, err)
        review_path = os.path.join(self.home, ".cortex", "agent-loop", "asana.review.last-run.json")
        with open(review_path) as f:
            rec = json.load(f)
        self.assertEqual(rec["outcome"], "ready")
        self.assertEqual(rec["task"], "t2")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".cortex", "agent-loop", "asana.last-run.json")))

    def test_unknown_kind_exits_1(self):
        code, _, err = self.run_cmd(["last-run", "asana", "start", "--kind", "nightly"])
        self.assertEqual(code, 1)
        self.assertIn("kind", err)


if __name__ == "__main__":
    unittest.main()
