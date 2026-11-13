#!/usr/bin/env python3
#
# Unit tests for start_task.py's pure functions — the half that can be tested
# offline. Phases that shell out to claude, gh, git or Asana are validated by
# running them.
#
#   python3 tests/test_pure.py

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import AgentResult, get_backend  # noqa: E402

import core as start_task  # noqa: E402
from core import (  # noqa: E402
    BOT_MARK,
    Awaiting,
    State,
    ensure_cortex_dir,
    is_marked,
    made_by_goal,
    live_run_pid,
    mark,
    parse_agent_questions,
    pending_kind,
    poll_interval,
    select_answer,
    slugify,
    task_key,
    worktree_path,
)


def task(**overrides):
    base = {
        "ref": "1209876",
        "name": "Add CSV export",
        "status": "Assigned",
        "assignee": "Justin",
        "assignee_gid": "42",
        "fields": {"Estimate": "3h"},
        "board": [{"project": "ENG | Sprint 26.16", "section": "Assigned"}],
    }
    base.update(overrides)
    return base


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Add CSV export"), "add-csv-export")

    def test_strips_punctuation_and_case(self):
        self.assertEqual(slugify("Fix: Login FAILS (silently)!"),
                         "fix-login-fails-silently")

    def test_truncates_to_max_words(self):
        self.assertEqual(
            slugify("one two three four five six seven eight"),
            "one-two-three-four-five-six")

    def test_empty_and_unsluggable_fall_back(self):
        self.assertEqual(slugify(""), "task")
        self.assertEqual(slugify("!!! ???"), "task")
        self.assertEqual(slugify(None), "task")

    def test_digits_survive(self):
        self.assertEqual(slugify("Bump to v2 API"), "bump-to-v2-api")


class TestTaskKey(unittest.TestCase):
    def test_prefers_human_key(self):
        self.assertEqual(task_key({"task_id": "MT251-47", "ref": "12"}), "MT251-47")

    def test_falls_back_to_gid(self):
        self.assertEqual(task_key({"ref": "12"}), "12")


class TestStateLocation(unittest.TestCase):
    """Everything the tool writes belongs under `.cortex/`, which ignores itself.
    The repo being worked in should never see a conductor file in its own diff."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_state_lives_under_cortex(self):
        self.assertEqual(State(self.root, "HGM-1").dir,
                         os.path.join(self.root, ".cortex", "state", "HGM-1"))

    def test_the_directory_ignores_itself_before_anything_is_written(self):
        State(self.root, "HGM-1").write("state.json", {"done": []})
        ignore = os.path.join(self.root, ".cortex", ".gitignore")
        self.assertTrue(os.path.isfile(ignore))
        with open(ignore) as f:
            self.assertIn("*", f.read())

    def test_a_run_leaves_nothing_else_at_the_repo_root(self):
        State(self.root, "HGM-1").write("state.json", {"done": []})
        self.assertEqual(os.listdir(self.root), [".cortex"])


class TestStateMigration(unittest.TestCase):
    """State written before the move is relocated, not stranded — a task in
    flight keeps its phases rather than being told it never started."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def legacy(self, task_id, done):
        path = os.path.join(self.root, ".start-task", task_id)
        os.makedirs(path)
        with open(os.path.join(path, "state.json"), "w") as f:
            json.dump({"done": done}, f)
        return path

    def test_legacy_state_is_found_and_moved(self):
        self.legacy("HGM-1", ["prologue", "implement"])
        state = State.find(self.root, "HGM-1")
        self.assertEqual(state.dir,
                         os.path.join(self.root, ".cortex", "state", "HGM-1"))
        self.assertEqual(state.phases_done(), {"prologue", "implement"})

    def test_the_old_directory_is_cleaned_up_once_it_is_empty(self):
        self.legacy("HGM-1", ["prologue"])
        State.find(self.root, "HGM-1")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".start-task")))

    def test_another_task_still_in_the_old_place_is_left_alone(self):
        self.legacy("HGM-1", ["prologue"])
        self.legacy("HGM-2", ["prologue"])
        State.find(self.root, "HGM-1")
        self.assertTrue(os.path.isdir(
            os.path.join(self.root, ".start-task", "HGM-2")))

    def test_current_state_is_never_overwritten_by_a_stale_legacy_copy(self):
        current = os.path.join(self.root, ".cortex", "state", "HGM-1")
        os.makedirs(current)
        with open(os.path.join(current, "state.json"), "w") as f:
            json.dump({"done": ["prologue", "implement", "qa", "ship"]}, f)
        self.legacy("HGM-1", ["prologue"])

        state = State.find(self.root, "HGM-1")
        self.assertEqual(state.phases_done(),
                         {"prologue", "implement", "qa", "ship"})
        # The stale copy is left where it is rather than silently deleted.
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".start-task", "HGM-1")))


class TestStateWriteText(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_write_text_roundtrips_and_returns_the_path(self):
        state = State(self.root, "HGM-1")
        state.ensure()
        path = state.write_text("implement.failure.log", "raw output")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(f.read(), "raw output")


class TestParseAgentQuestions(unittest.TestCase):
    """The implement contract has two terminal shapes. Telling them apart is the
    whole trigger for the ask cycle, so it must not guess."""

    def test_a_summary_block_is_not_a_question(self):
        self.assertIsNone(parse_agent_questions(
            {"summary": "did the thing", "files_changed": [], "notes": ""}))

    def test_none_and_junk_are_not_questions(self):
        self.assertIsNone(parse_agent_questions(None))
        self.assertIsNone(parse_agent_questions("questions"))
        self.assertIsNone(parse_agent_questions({"questions": []}))
        self.assertIsNone(parse_agent_questions({"questions": "which vpc"}))

    def test_extracts_question_and_reason(self):
        qs = parse_agent_questions(
            {"questions": [{"q": "Which VPC?", "why": "tfvars defines two"}]})
        self.assertEqual(qs, [{"q": "Which VPC?", "why": "tfvars defines two"}])

    def test_accepts_bare_strings(self):
        self.assertEqual(parse_agent_questions({"questions": ["Which VPC?"]}),
                         [{"q": "Which VPC?", "why": ""}])

    def test_drops_empty_entries_and_reports_none_if_all_empty(self):
        self.assertIsNone(parse_agent_questions({"questions": ["", {"q": "  "}]}))


class TestSelectAnswer(unittest.TestCase):
    """The watermark is the question comment's own created_at, minted by the task
    manager — never a local clock, which would drift against it."""

    ASKED = "2026-09-15T12:00:00.000Z"

    def c(self, at, text="answer", author="Justin"):
        return {"created_at": at, "text": text, "author": author}

    def test_nothing_after_the_watermark_is_no_answer(self):
        self.assertIsNone(select_answer(
            [self.c("2026-09-15T11:00:00.000Z")], self.ASKED))

    def test_our_own_question_comment_is_excluded_by_the_watermark(self):
        self.assertIsNone(select_answer([self.c(self.ASKED)], self.ASKED))

    def test_first_later_comment_wins(self):
        later = self.c("2026-09-15T12:05:00.000Z", "use nonprod")
        latest = self.c("2026-09-15T12:09:00.000Z", "actually shared")
        self.assertEqual(select_answer([later, latest], self.ASKED)["text"],
                         "use nonprod")

    def test_the_operators_own_reply_counts(self):
        # The run posts with the operator's token, so author-matching would
        # discard the very reply it waits for.
        reply = self.c("2026-09-15T12:05:00.000Z", "nonprod", author="Justin")
        self.assertIsNotNone(select_answer([reply], self.ASKED))

    def test_the_runs_own_marked_posts_are_not_answers(self):
        bot = self.c("2026-09-15T12:05:00.000Z", mark("🚀 Shipped — x"))
        real = self.c("2026-09-15T12:06:00.000Z", "nonprod")
        self.assertEqual(select_answer([bot, real], self.ASKED)["text"], "nonprod")
        self.assertIsNone(select_answer([bot], self.ASKED))

    def test_blank_and_undated_comments_are_skipped(self):
        blank = self.c("2026-09-15T12:05:00.000Z", "   ")
        undated = {"text": "hi", "author": "X"}
        real = self.c("2026-09-15T12:06:00.000Z", "nonprod")
        self.assertEqual(select_answer([blank, undated, real], self.ASKED)["text"],
                         "nonprod")


class TestPollInterval(unittest.TestCase):
    def test_backs_off_from_start_to_cap(self):
        seq = [poll_interval(n, start=30, cap=120) for n in range(1, 7)]
        self.assertEqual(seq, [30, 60, 120, 120, 120, 120])

    def test_never_returns_zero(self):
        self.assertGreater(poll_interval(0, start=30, cap=120), 0)


class TestLiveRunPid(unittest.TestCase):
    """A recorded pid whose process is gone is a crashed run, not a live one."""

    def test_live_process_is_reported(self):
        self.assertEqual(live_run_pid({"pid": 4242}, is_alive=lambda p: True), 4242)

    def test_dead_process_is_not(self):
        self.assertIsNone(live_run_pid({"pid": 4242}, is_alive=lambda p: False))

    def test_missing_or_malformed_record(self):
        for rec in (None, {}, {"pid": "abc"}, "nope"):
            self.assertIsNone(live_run_pid(rec, is_alive=lambda p: True))


class TestWorktreePath(unittest.TestCase):
    """The directory name carries the slug as well as the id, matching the
    `<id>+<slug>` convention already in these repos — a human reading a list of
    worktrees can tell what each one is for without opening it."""

    def test_lives_under_cortex_worktrees_named_id_plus_slug(self):
        self.assertEqual(
            worktree_path("/repos/humanus-mono", "HGM-32", "i20-deploy-the-api"),
            "/repos/humanus-mono/.cortex/worktrees/HGM-32+i20-deploy-the-api")

    def test_falls_back_to_the_bare_id_without_a_slug(self):
        for slug in (None, "", "   "):
            self.assertEqual(worktree_path("/repos/r", "HGM-32", slug),
                             "/repos/r/.cortex/worktrees/HGM-32")

    def test_is_absolute_and_normalised(self):
        path = worktree_path("/repos/humanus-mono/", "HGM-32", "slug")
        self.assertTrue(os.path.isabs(path))
        self.assertNotIn("//", path)

    def test_a_slug_with_a_separator_cannot_escape_the_directory(self):
        path = worktree_path("/repos/r", "HGM-32", "a/../../etc")
        self.assertTrue(path.startswith("/repos/r/.cortex/worktrees/"))


class TestEnsureCortexDir(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_creates_the_tree_and_a_self_ignoring_gitignore(self):
        ensure_cortex_dir(self.root)
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".cortex", "worktrees")))
        with open(os.path.join(self.root, ".cortex", ".gitignore")) as f:
            body = f.read()
        # `*` covers the .gitignore itself, so the whole directory is invisible and
        # the repo's own .gitignore is never touched.
        self.assertIn("*", body.split())

    def test_does_not_overwrite_an_existing_gitignore(self):
        os.makedirs(os.path.join(self.root, ".cortex"))
        path = os.path.join(self.root, ".cortex", ".gitignore")
        with open(path, "w") as f:
            f.write("mine\n")
        ensure_cortex_dir(self.root)
        with open(path) as f:
            self.assertEqual(f.read(), "mine\n")

    def test_is_idempotent(self):
        ensure_cortex_dir(self.root)
        ensure_cortex_dir(self.root)
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".cortex", "worktrees")))


class TestMarker(unittest.TestCase):
    def test_marked_posts_are_recognised(self):
        self.assertTrue(is_marked(mark("hello")))
        self.assertTrue(is_marked("\n  " + mark("hello")))

    def test_posts_from_before_the_rename_are_still_the_runs(self):
        self.assertTrue(is_marked("\U0001f916 cortex \u00b7 hello"))
        self.assertTrue(made_by_goal({"name": "Plan", "description": "x\n_Planned by a cortex goal._"}))
        self.assertTrue(made_by_goal({"name": "Plan", "description": "x\n_Planned by a conductor goal._"}))
        self.assertFalse(made_by_goal({"name": "Plan", "description": "Theirs."}))

    def test_a_human_quoting_the_bot_is_not_the_bot(self):
        self.assertFalse(is_marked("> %s hello\n\nno, do it the other way" % BOT_MARK))
        self.assertFalse(is_marked("thanks"))
        self.assertFalse(is_marked(None))


class TestPendingKind(unittest.TestCase):
    def test_kind_is_read(self):
        self.assertEqual(pending_kind({"kind": "qa"}), "qa")

    def test_a_record_from_before_kinds_is_questions(self):
        self.assertEqual(pending_kind({"questions": [{"q": "x"}]}), "questions")

    def test_nothing_pending(self):
        self.assertIsNone(pending_kind(None))
        self.assertIsNone(pending_kind({}))


class TestEscalate(unittest.TestCase):
    """The wait must survive a restart: a question already posted is not posted
    again, and a reply that arrived while nothing was running still counts."""

    class Args(object):
        no_wait = False

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = State(self.root, "HCI-1")
        self.state.ensure()
        self.posted, self.comments = [], []
        self.saved = start_task.asana, start_task.time.sleep
        self.addCleanup(self.restore)
        start_task.asana = self.fake_asana
        start_task.time.sleep = lambda s: None

    def restore(self):
        start_task.asana, start_task.time.sleep = self.saved

    def fake_asana(self, args, cwd):
        if args[:2] == ["comment", "add"]:
            self.posted.append(args[3])
            return {"created_at": "2026-10-01T10:00:00.000Z"}
        if args[:2] == ["comment", "list"]:
            return self.comments
        raise AssertionError(args)

    def test_posts_marked_and_returns_the_first_human_reply(self):
        self.comments = [
            {"created_at": "2026-10-01T10:00:00.000Z", "text": "the question"},
            {"created_at": "2026-10-01T10:05:00.000Z", "text": mark("bot noise")},
            {"created_at": "2026-10-01T10:06:00.000Z", "text": "go ahead"},
        ]
        answer = start_task.escalate(self.state, "1", "/", self.Args(), "qa", "QA red")
        self.assertEqual(answer, "go ahead")
        self.assertEqual(len(self.posted), 1)
        self.assertTrue(is_marked(self.posted[0]))
        self.assertIsNone(self.state.read("awaiting.json"))

    def test_a_pending_wait_of_the_same_kind_is_not_posted_again(self):
        self.state.write("awaiting.json", {"kind": "qa", "asked_at": "2026-10-01T09:00:00.000Z"})
        self.comments = [{"created_at": "2026-10-01T09:30:00.000Z", "text": "fixed it"}]
        answer = start_task.escalate(self.state, "1", "/", self.Args(), "qa", "QA red")
        self.assertEqual(answer, "fixed it")
        self.assertEqual(self.posted, [])

    def test_a_pending_wait_of_another_kind_is_replaced(self):
        self.state.write("awaiting.json", {"kind": "push", "asked_at": "2026-10-01T09:00:00.000Z"})
        self.comments = [{"created_at": "2026-10-01T10:01:00.000Z", "text": "ok"}]
        start_task.escalate(self.state, "1", "/", self.Args(), "qa", "QA red")
        self.assertEqual(len(self.posted), 1)

    def test_an_answer_handed_over_locally_lands_without_an_asana_reply(self):
        self.state.write("awaiting.json", {"kind": "questions", "asked_at": "T1"})
        self.state.write("answer.json", {"asked_at": "T1", "text": " use nonprod "})
        answer = start_task.escalate(self.state, "1", "/", self.Args(), "questions", "Q")
        self.assertEqual(answer, "use nonprod")
        self.assertIsNone(self.state.read("answer.json"))
        self.assertIsNone(self.state.read("awaiting.json"))

    def test_a_local_answer_to_another_question_is_not_taken(self):
        self.state.write("awaiting.json", {"kind": "questions", "asked_at": "T2"})
        self.state.write("answer.json", {"asked_at": "T1", "text": "old"})
        self.comments = [{"created_at": "T3", "text": "the real answer"}]
        answer = start_task.escalate(self.state, "1", "/", self.Args(), "questions", "Q")
        self.assertEqual(answer, "the real answer")

    def test_no_wait_posts_and_stops_leaving_the_record(self):
        args = self.Args()
        args.no_wait = True
        with self.assertRaises(Awaiting):
            start_task.escalate(self.state, "1", "/", args, "qa", "QA red")
        self.assertEqual(self.state.read("awaiting.json")["kind"], "qa")


class TestActualField(unittest.TestCase):
    """The Actual field is a number in hours; asana.py has to know it and write
    it as one."""

    def test_actual_is_a_known_field_and_does_not_steal_estimate(self):
        import asana
        self.assertEqual(asana.match_canonical("Actual"), "Actual")
        self.assertEqual(asana.match_canonical("Actual time"), "Actual")
        self.assertEqual(asana.match_canonical("Estimate"), "Estimate")

    def test_number_values_are_numbers_at_the_fields_precision(self):
        import asana
        self.assertEqual(asana.number_value("3.256", {"precision": 2}), 3.26)
        self.assertEqual(asana.number_value("3.6", {"precision": 0}), 4)
        with self.assertRaises(ValueError):
            asana.number_value("soon", {"precision": 2})


class TestFieldsCacheVersion(unittest.TestCase):
    """The schema version is stamped on the whole cache; a map written in an
    older shape must not be kept under a newer stamp."""

    def setUp(self):
        import asana
        import cache_util
        self.asana, self.cache_util = asana, cache_util
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.saved = cache_util.CACHE_DIR
        cache_util.CACHE_DIR = self.root
        self.addCleanup(setattr, cache_util, "CACHE_DIR", self.saved)

    def test_an_old_version_drops_every_projects_map(self):
        self.cache_util.write_cache("k", {"provider": "asana", "fields_schema_version": 2,
                                          "fields": {"old": {"Estimate": {}}}})
        self.asana.write_fields_map("k", "new", {"Actual": {"id": "1"}})
        self.assertIsNone(self.asana.cached_fields_map("k", "old"))
        self.assertEqual(self.asana.cached_fields_map("k", "new"), {"Actual": {"id": "1"}})

    def test_the_current_version_keeps_other_maps(self):
        self.asana.write_fields_map("k", "a", {"x": {}})
        self.asana.write_fields_map("k", "b", {"y": {}})
        self.assertEqual(self.asana.cached_fields_map("k", "a"), {"x": {}})


class TestRunTimeClock(unittest.TestCase):
    """Run time must not count the machine being asleep: a closed lid once put
    two and a half hours of sleep into a task's Actual."""

    def test_the_clock_used_stops_while_the_system_sleeps(self):
        import time
        info = time.get_clock_info("monotonic")
        self.assertTrue(info.monotonic)
        self.assertFalse(info.adjustable)



class TestBaseRef(unittest.TestCase):
    """A base given by name must reach git as the remote-tracking ref: given a
    bare `feature/x`, `git worktree add -b T/x feature/x` checks out a new local
    `feature/x` instead of creating T/x."""

    def test_names_get_origin(self):
        self.assertEqual(start_task.base_ref("feature/candidate-intake-M1"),
                         "origin/feature/candidate-intake-M1")
        self.assertEqual(start_task.base_ref("main"), "origin/main")

    def test_an_origin_ref_is_left_as_it_is(self):
        self.assertEqual(start_task.base_ref("origin/feature/x"), "origin/feature/x")

    def test_git_makes_the_branch_asked_for_off_a_remote_only_base(self):
        import subprocess
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        def git(*args, cwd=root):
            return subprocess.run(["git"] + list(args), cwd=cwd, check=True,
                                  capture_output=True, text=True).stdout.strip()
        git("init", "-q", "--bare", "-b", "main", "o.git")
        git("clone", "-q", "o.git", "w")
        work = os.path.join(root, "w")
        git("commit", "-q", "--allow-empty", "-m", "c1", cwd=work)
        git("push", "-q", "origin", "main", "main:feature/x", cwd=work)
        git("fetch", "-q", cwd=work)
        wt = os.path.join(root, "wt")
        git("worktree", "add", wt, "-b", "T-1/task", start_task.base_ref("feature/x"), cwd=work)
        self.assertEqual(git("branch", "--show-current", cwd=wt), "T-1/task")


class TestTokenUsage(unittest.TestCase):
    ENVELOPE = {"subtype": "success", "result": "ok", "total_cost_usd": 0.0816502,
                "usage": {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 10811,
                          "cache_creation_input_tokens": 19861}}

    def test_the_envelope_reports_tokens_and_cost(self):
        from agent.claude_cli import parse_envelope
        _, t = parse_envelope(json.dumps(self.ENVELOPE))
        self.assertEqual(t["usage"], {"input": 2, "output": 4, "cache_read": 10811,
                                      "cache_write": 19861, "cost_usd": 0.0816502})

    def test_no_usage_is_none_not_zero(self):
        from agent.claude_cli import parse_envelope
        _, t = parse_envelope(json.dumps({"subtype": "success", "result": "ok"}))
        self.assertIsNone(t["usage"])

    def test_readable_totals(self):
        from agent.base import tokens_text, usage_summary
        self.assertEqual([tokens_text(n) for n in (940, 12400, 1240000)], ["940", "12.4k", "1.24M"])
        self.assertEqual(usage_summary({"input": 2, "output": 4, "cache_read": 10811,
                                        "cache_write": 19861, "cost_usd": 0.0816502}),
                         "30.7k tokens · ≈$0.08")

    def test_calls_add_up_across_runs_and_by_kind(self):
        call = {"input": 10, "output": 5, "cache_read": 100, "cache_write": 0, "cost_usd": 0.5}
        total = start_task.add_usage(None, call, "implement")
        total = start_task.add_usage(total, call, "qa-repair-1")
        total = start_task.add_usage(total, call, "qa-repair-2")
        self.assertEqual((total["output"], total["calls"], total["cost_usd"]), (15, 3, 1.5))
        self.assertEqual(total["by_call"], {"implement": 115, "qa-repair": 230})

    def test_each_call_is_kept_on_its_own_with_its_model_and_time(self):
        call = {"input": 10, "output": 5, "cache_read": 100, "cache_write": 2, "cost_usd": 0.5}
        total = start_task.add_usage(None, call, "qa-repair-2", "claude-sonnet-5-5", "2026-10-05T09:00:00Z")
        self.assertEqual(total["calls_log"], [{
            "input": 10, "output": 5, "cache_read": 100, "cache_write": 2, "at": "2026-10-05T09:00:00Z",
            "kind": "qa-repair", "label": "qa-repair-2", "model": "claude-sonnet-5-5", "cost_usd": 0.5}])

class TestGithubRefused(unittest.TestCase):
    def test_creating_a_pr_says_what_gh_said(self):
        calls = []

        def fake_run(argv, cwd=None, check=True):
            calls.append(argv)
            return 1, "", "HTTP 401: Bad credentials"
        real, start_task.run = start_task.run, fake_run
        try:
            self.assertEqual(start_task.create_draft_pr("T-1", "n", "u", "origin/main", "T-1/n", "/r"),
                             (None, "HTTP 401: Bad credentials"))
        finally:
            start_task.run = real
        self.assertIn("--base", calls[0])
        self.assertEqual(calls[0][calls[0].index("--base") + 1], "main")


class TestAsanaTimeout(unittest.TestCase):
    def test_every_asana_request_gives_up_on_a_stalled_connection(self):
        import asana
        from unittest import mock
        seen = []

        def urlopen(req, timeout=None):
            seen.append(timeout)
            raise OSError("timed out")
        with mock.patch.object(asana.urllib.request, "urlopen", urlopen):
            for call in (lambda: asana.api_get("https://x/a", "t"),
                         lambda: asana.api_json("https://x/a", "t", "PUT", {}),
                         lambda: asana.api_delete("https://x/a", "t")):
                with self.assertRaises(SystemExit):
                    call()
        self.assertEqual(seen, [asana.HTTP_TIMEOUT] * 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
