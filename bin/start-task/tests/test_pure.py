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

import start_task  # noqa: E402
from start_task import (  # noqa: E402
    BOT_MARK,
    Awaiting,
    State,
    build_outcome,
    checkpoint_problems,
    ensure_cortex_dir,
    evaluate_gate,
    extract_external_links,
    extract_last_json_block,
    failure_detail,
    format_questions_comment,
    is_marked,
    live_run_pid,
    mark,
    parse_agent_questions,
    path_matches,
    pending_kind,
    phases_to_run,
    poll_interval,
    record_session,
    select_answer,
    select_gates,
    should_continue,
    slugify,
    task_key,
    worktree_for_branch,
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


class TestExtractExternalLinks(unittest.TestCase):
    def test_finds_and_dedupes_preserving_order(self):
        links = extract_external_links(
            "see https://figma.com/file/abc and https://notion.so/page",
            "again https://figma.com/file/abc")
        self.assertEqual(links, ["https://figma.com/file/abc",
                                 "https://notion.so/page"])

    def test_skips_asana_and_github(self):
        links = extract_external_links(
            "https://app.asana.com/0/1/2 https://github.com/o/r/pull/1 "
            "https://figma.com/x")
        self.assertEqual(links, ["https://figma.com/x"])

    def test_strips_trailing_punctuation(self):
        self.assertEqual(extract_external_links("see https://notion.so/page."),
                         ["https://notion.so/page"])

    def test_tolerates_none_and_empty(self):
        self.assertEqual(extract_external_links(None, "", 42), [])


class TestEvaluateGate(unittest.TestCase):
    def test_happy_path(self):
        verdict = evaluate_gate(task(), [], "42")
        self.assertEqual(verdict["blocking"], [])
        self.assertEqual(verdict["warnings"], [])
        self.assertFalse(verdict["self_assign"])

    def test_started_status_blocks(self):
        verdict = evaluate_gate(task(status="In Progress"), [], "42")
        self.assertEqual(len(verdict["blocking"]), 1)
        self.assertIn("not a not-yet-started state", verdict["blocking"][0])

    def test_status_match_is_case_insensitive(self):
        self.assertEqual(evaluate_gate(task(status="ASSIGNED"), [], "42")["blocking"], [])

    def test_missing_status_blocks(self):
        self.assertTrue(evaluate_gate(task(status=None), [], "42")["blocking"])

    def test_incomplete_dependency_blocks(self):
        deps = [{"name": "Build the API", "completed": False},
                {"name": "Design it", "completed": True}]
        verdict = evaluate_gate(task(), deps, "42")
        self.assertEqual(len(verdict["blocking"]), 1)
        self.assertIn("Build the API", verdict["blocking"][0])
        self.assertNotIn("Design it", verdict["blocking"][0])

    def test_completed_dependencies_pass(self):
        deps = [{"name": "Done thing", "completed": True}]
        self.assertEqual(evaluate_gate(task(), deps, "42")["blocking"], [])

    def test_incomplete_dependency_warns_under_ignore_deps(self):
        deps = [{"name": "Build the API", "completed": False}]
        verdict = evaluate_gate(task(), deps, "42", ignore_deps=True)
        self.assertEqual(verdict["blocking"], [])
        self.assertIn("Build the API", verdict["warnings"][0])
        self.assertIn("ignored", verdict["warnings"][0])

    def test_ignore_deps_does_not_rescue_other_preconditions(self):
        deps = [{"name": "Build the API", "completed": False}]
        verdict = evaluate_gate(task(status="Done"), deps, "42", ignore_deps=True)
        self.assertTrue(any("Done" in b for b in verdict["blocking"]))
        self.assertFalse(any("Build the API" in b for b in verdict["blocking"]))

    def test_unassigned_requests_self_assign_not_block(self):
        verdict = evaluate_gate(task(assignee=None, assignee_gid=None), [], "42")
        self.assertTrue(verdict["self_assign"])
        self.assertEqual(verdict["blocking"], [])

    def test_assigned_to_someone_else_blocks(self):
        verdict = evaluate_gate(task(assignee="Maria", assignee_gid="99"), [], "42")
        self.assertIn("Maria", verdict["blocking"][0])

    def test_missing_estimate_warns_by_default(self):
        verdict = evaluate_gate(task(fields={}), [], "42")
        self.assertEqual(verdict["blocking"], [])
        self.assertEqual(verdict["warnings"], ["no Estimate set"])

    def test_missing_estimate_blocks_under_strict(self):
        verdict = evaluate_gate(task(fields={}), [], "42", strict=True)
        self.assertIn("no Estimate set", verdict["blocking"])

    def test_sprint_membership_only_checked_under_strict(self):
        off_sprint = task(board=[{"project": "ENG | Backlog", "section": "New"}])
        self.assertEqual(evaluate_gate(off_sprint, [], "42")["blocking"], [])
        strict = evaluate_gate(off_sprint, [], "42", strict=True)["blocking"]
        self.assertTrue(any("sprint" in b for b in strict))

    def test_a_resumed_run_passes_its_own_started_status(self):
        gate = evaluate_gate(task(status="In Progress"), [], "42", resuming=True)
        self.assertEqual(gate["blocking"], [])
        self.assertTrue(any("resuming" in w for w in gate["warnings"]))

    def test_resuming_does_not_excuse_incomplete_dependencies(self):
        gate = evaluate_gate(task(status="In Progress"),
                             [{"name": "dep", "completed": False}], "42", resuming=True)
        self.assertEqual(len(gate["blocking"]), 1)

    def test_reports_every_failure_at_once(self):
        verdict = evaluate_gate(
            task(status="Done", assignee="Maria", assignee_gid="99"),
            [{"name": "Blocker", "completed": False}], "42")
        self.assertEqual(len(verdict["blocking"]), 3)


class TestExtractLastJsonBlock(unittest.TestCase):
    def test_extracts_fenced_json(self):
        text = 'Did the thing.\n\n```json\n{"summary": "ok"}\n```'
        self.assertEqual(extract_last_json_block(text), {"summary": "ok"})

    def test_takes_the_last_block(self):
        text = '```json\n{"n": 1}\n```\nthen\n```json\n{"n": 2}\n```'
        self.assertEqual(extract_last_json_block(text), {"n": 2})

    def test_skips_unparseable_trailing_block(self):
        text = '```json\n{"n": 1}\n```\n```json\nnot json\n```'
        self.assertEqual(extract_last_json_block(text), {"n": 1})

    def test_unfenced_language_tag_optional(self):
        self.assertEqual(extract_last_json_block('```\n{"n": 3}\n```'), {"n": 3})

    def test_ignores_non_object_json(self):
        self.assertIsNone(extract_last_json_block('```json\n[1, 2]\n```'))

    def test_no_block_returns_none(self):
        self.assertIsNone(extract_last_json_block("just prose"))
        self.assertIsNone(extract_last_json_block(None))


class TestTaskKey(unittest.TestCase):
    def test_prefers_human_key(self):
        self.assertEqual(task_key({"task_id": "MT251-47", "ref": "12"}), "MT251-47")

    def test_falls_back_to_gid(self):
        self.assertEqual(task_key({"ref": "12"}), "12")


class TestShouldContinue(unittest.TestCase):
    """The turn ceiling is a checkpoint, so a call that hits it gets resumed. The
    guard is progress: a run that burns another whole ceiling without touching the
    worktree is looping, and resuming it again would only cost more."""

    def result(self, stop_reason="max_turns", resume_token="abc123"):
        return AgentResult(backend="claude-cli", stop_reason=stop_reason,
                           resume_token=resume_token)

    def test_resumes_when_the_ceiling_was_hit_and_work_advanced(self):
        go, reason = should_continue(self.result(), " M start_task.py", "")
        self.assertTrue(go)
        self.assertIsNone(reason)

    def test_stops_when_nothing_changed_since_the_last_attempt(self):
        go, reason = should_continue(self.result(), " M start_task.py",
                                     " M start_task.py")
        self.assertFalse(go)
        self.assertIn("without changing anything", reason)

    def test_stops_when_the_backend_cannot_resume(self):
        go, reason = should_continue(self.result(resume_token=None), "a", "b")
        self.assertFalse(go)
        self.assertIn("cannot resume", reason)

    def test_a_finished_call_is_not_resumed(self):
        go, reason = should_continue(self.result(stop_reason="complete"), "a", "b")
        self.assertFalse(go)
        self.assertIsNone(reason)

    def test_an_unreported_stop_reason_is_not_resumed(self):
        go, reason = should_continue(self.result(stop_reason=None), "a", "b")
        self.assertFalse(go)
        self.assertIsNone(reason)


class TestRecordSession(unittest.TestCase):
    """The run keeps the agent's session so a person can take the conversation
    over. Only the newest one, because that is the live conversation."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = State(self.root, "HGM-1")
        self.state.ensure()
        self.backend = get_backend("claude-cli")

    def result(self, token="abc123"):
        return AgentResult(backend="claude-cli", resume_token=token)

    def test_records_the_command_a_human_would_run(self):
        record_session(self.state, "implement", "/tmp/wt", self.backend,
                       self.result())
        session = self.state.read("session.json")
        self.assertEqual(session["label"], "implement")
        self.assertEqual(session["token"], "abc123")
        self.assertIn("claude --resume abc123", session["command"])

    def test_the_newest_call_wins(self):
        record_session(self.state, "implement", "/tmp/wt", self.backend,
                       self.result("first"))
        record_session(self.state, "qa-repair-1", "/tmp/wt", self.backend,
                       self.result("second"))
        session = self.state.read("session.json")
        self.assertEqual(session["token"], "second")
        self.assertEqual(session["label"], "qa-repair-1")

    def test_a_call_with_no_session_records_nothing(self):
        record_session(self.state, "implement", "/tmp/wt", self.backend,
                       self.result(token=None))
        self.assertIsNone(self.state.read("session.json"))

    def test_a_backend_with_no_interactive_form_records_no_command(self):
        record_session(self.state, "implement", "/tmp/wt", get_backend("echo"),
                       self.result())
        self.assertIsNone(self.state.read("session.json")["command"])


class TestStateLocation(unittest.TestCase):
    """Everything the tool writes belongs under `.cortex/`, which ignores itself.
    The repo being worked in should never see a cortex file in its own diff."""

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


class TestFailureDetail(unittest.TestCase):
    """A backend that exits non-zero with an empty stderr told us nothing. The
    reason is in whatever it printed, so that is what must reach the operator."""

    def result(self, **kw):
        class R(object):
            pass
        r = R()
        r.error = kw.get("error")
        r.text = kw.get("text", "")
        return r

    def test_uses_the_error_when_the_backend_gave_one(self):
        detail = failure_detail(self.result(error="model overloaded", text="noise"))
        self.assertIn("model overloaded", detail)

    def test_falls_back_to_the_tail_of_stdout_when_error_is_empty(self):
        detail = failure_detail(self.result(error="", text="line one\nthe real reason"))
        self.assertIn("the real reason", detail)

    def test_tail_is_bounded(self):
        detail = failure_detail(self.result(error=None, text="x" * 9000), tail=100)
        self.assertLessEqual(len(detail), 400)
        self.assertIn("x", detail)

    def test_says_unknown_when_there_is_nothing_at_all(self):
        self.assertIn("unknown", failure_detail(self.result(error=None, text="")))


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


class TestPhasesToRun(unittest.TestCase):
    """Resume is subtraction: a phase already recorded done is not repeated."""

    PHASES = ("implement", "qa", "ship")

    def test_nothing_done_runs_everything(self):
        self.assertEqual(phases_to_run(self.PHASES, set()),
                         ["implement", "qa", "ship"])

    def test_skips_what_is_done_and_keeps_order(self):
        self.assertEqual(phases_to_run(self.PHASES, {"implement"}), ["qa", "ship"])

    def test_all_done_runs_nothing(self):
        self.assertEqual(phases_to_run(self.PHASES, {"implement", "qa", "ship"}), [])

    def test_a_done_phase_that_no_longer_exists_is_ignored(self):
        self.assertEqual(phases_to_run(self.PHASES, {"implement", "deploy"}),
                         ["qa", "ship"])

    def test_done_out_of_order_does_not_resurrect_an_earlier_phase(self):
        # qa recorded but implement not: implement still runs, qa does not.
        self.assertEqual(phases_to_run(self.PHASES, {"qa"}), ["implement", "ship"])


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


class TestFormatQuestionsComment(unittest.TestCase):
    def test_includes_every_question_its_reason_and_how_to_reply(self):
        body = format_questions_comment(
            [{"q": "Which VPC?", "why": "two in tfvars"},
             {"q": "Fail closed?", "why": ""}], branch="HGM-32/x")
        self.assertIn("Which VPC?", body)
        self.assertIn("two in tfvars", body)
        self.assertIn("Fail closed?", body)
        self.assertIn("HGM-32/x", body)
        self.assertIn("reply", body.lower())


class TestLiveRunPid(unittest.TestCase):
    """A recorded pid whose process is gone is a crashed run, not a live one."""

    def test_live_process_is_reported(self):
        self.assertEqual(live_run_pid({"pid": 4242}, is_alive=lambda p: True), 4242)

    def test_dead_process_is_not(self):
        self.assertIsNone(live_run_pid({"pid": 4242}, is_alive=lambda p: False))

    def test_missing_or_malformed_record(self):
        for rec in (None, {}, {"pid": "abc"}, "nope"):
            self.assertIsNone(live_run_pid(rec, is_alive=lambda p: True))


class TestCheckpointProblems(unittest.TestCase):
    """Resume trusts state.json; this is the check that reality still matches."""

    def ctx(self, worktree="/tmp/wt"):
        return {"git": {"worktree": worktree, "branch": "b"}}

    def test_no_problems_when_the_worktree_is_there(self):
        self.assertEqual(checkpoint_problems(self.ctx(), isdir=lambda p: True), [])

    def test_missing_worktree_is_a_problem(self):
        problems = checkpoint_problems(self.ctx(), isdir=lambda p: False)
        self.assertEqual(len(problems), 1)
        self.assertIn("/tmp/wt", problems[0])

    def test_empty_context_is_a_problem(self):
        self.assertTrue(checkpoint_problems({}, isdir=lambda p: True))


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


class TestWorktreeForBranch(unittest.TestCase):
    """A branch can only be checked out in one worktree. Finding an existing one is
    what lets the worktree location change without stranding work in flight."""

    PORCELAIN = (
        "worktree /repos/humanus-mono\n"
        "HEAD 1111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repos/humanus-mono-HGM-32\n"
        "HEAD 2222222\n"
        "branch refs/heads/HGM-32/i20-deploy\n"
        "\n"
        "worktree /repos/detached\n"
        "HEAD 3333333\n"
        "detached\n"
    )

    def test_finds_a_worktree_at_its_old_location(self):
        self.assertEqual(worktree_for_branch(self.PORCELAIN, "HGM-32/i20-deploy"),
                         "/repos/humanus-mono-HGM-32")

    def test_returns_none_for_a_branch_not_checked_out(self):
        self.assertIsNone(worktree_for_branch(self.PORCELAIN, "HGM-99/other"))

    def test_handles_the_main_worktree_and_detached_heads(self):
        self.assertEqual(worktree_for_branch(self.PORCELAIN, "main"),
                         "/repos/humanus-mono")

    def test_empty_input(self):
        self.assertIsNone(worktree_for_branch("", "main"))


class TestMarker(unittest.TestCase):
    def test_marked_posts_are_recognised(self):
        self.assertTrue(is_marked(mark("hello")))
        self.assertTrue(is_marked("\n  " + mark("hello")))

    def test_a_human_quoting_the_bot_is_not_the_bot(self):
        self.assertFalse(is_marked("> %s hello\n\nno, do it the other way" % BOT_MARK))
        self.assertFalse(is_marked("thanks"))
        self.assertFalse(is_marked(None))


class TestSelectGates(unittest.TestCase):
    CONFIG = {"gates": [
        {"name": "backend", "run": "make verify",
         "paths": ["apps/api/", "apps/core/", "apps/worker/", "tools/",
                   "pyproject.toml", "uv.lock", "Makefile"]},
        {"name": "frontend", "run": "npm run verify", "cwd": "apps/frontend",
         "paths": ["apps/frontend/"]},
    ]}

    def names(self, changed, config=None):
        return [g[0] for g in select_gates(config or self.CONFIG, changed)]

    def test_backend_only_change_runs_only_the_backend_gate(self):
        self.assertEqual(self.names(["apps/api/src/x.py"]), ["backend"])

    def test_frontend_only_change_runs_only_the_frontend_gate_in_its_dir(self):
        gates = select_gates(self.CONFIG, ["apps/frontend/src/a.tsx"])
        self.assertEqual(gates, [("frontend", "npm run verify", "apps/frontend")])

    def test_both_sides_run_both(self):
        self.assertEqual(self.names(["uv.lock", "apps/frontend/package.json"]),
                         ["backend", "frontend"])

    def test_docs_only_runs_nothing(self):
        self.assertEqual(self.names(["docs/notes.md", "README.md"]), [])

    def test_unknown_diff_runs_everything(self):
        self.assertEqual(self.names(None), ["backend", "frontend"])

    def test_a_gate_without_paths_always_runs(self):
        self.assertEqual(self.names(["docs/x.md"], {"gates": [{"run": "true"}]}), ["true"])

    def test_flat_keys_still_work_and_always_run(self):
        self.assertEqual(self.names(["docs/x.md"], {"lint": "l", "test": "t"}),
                         ["lint", "test"])

    def test_a_gate_without_a_command_is_an_error(self):
        with self.assertRaises(ValueError):
            select_gates({"gates": [{"name": "x", "paths": ["a/"]}]}, ["a/b"])


class TestPathMatches(unittest.TestCase):
    def test_directory_prefix_with_or_without_slash(self):
        self.assertTrue(path_matches("apps/api/x.py", "apps/api/"))
        self.assertTrue(path_matches("apps/api/x.py", "apps/api"))

    def test_a_sibling_with_the_same_prefix_does_not_match(self):
        self.assertFalse(path_matches("apps/api-docs/x.md", "apps/api"))

    def test_exact_file(self):
        self.assertTrue(path_matches("Makefile", "Makefile"))
        self.assertFalse(path_matches("docs/Makefile", "Makefile"))

    def test_blank_pattern_matches_nothing(self):
        self.assertFalse(path_matches("x", "  "))


class TestBuildOutcome(unittest.TestCase):
    def test_carries_what_a_launcher_needs(self):
        context = {"task": {"id": "HCI-24", "gid": "123"},
                   "git": {"pr_url": "https://github.com/o/r/pull/7", "branch": "HCI-24/x",
                           "worktree": "/wt"}}
        out = build_outcome("shipped", "url", context,
                            {"token": "s1", "backend": "claude-cli", "command": "c"})
        self.assertEqual(out["status"], "shipped")
        self.assertEqual(out["task"], "HCI-24")
        self.assertEqual(out["gid"], "123")
        self.assertEqual(out["pr_url"], "https://github.com/o/r/pull/7")
        self.assertEqual(out["branch"], "HCI-24/x")
        self.assertEqual(out["session"]["token"], "s1")

    def test_a_run_that_failed_before_any_state_still_says_so(self):
        out = build_outcome("failed", "https://app.asana.com/0/1/2", None, None, "boom")
        self.assertEqual(out["task"], "https://app.asana.com/0/1/2")
        self.assertIsNone(out["pr_url"])
        self.assertIsNone(out["session"])
        self.assertEqual(out["reason"], "boom")


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

    def test_a_run_records_monotonic_time_minus_its_waits(self):
        import time
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        state = State(root, "T-1")
        state.ensure()
        clock = iter([1000.0, 1000.0 + 600])     # ten minutes awake

        class Args(object):
            task, repo, task_key = "T-1", root, "T-1"
            backends = status = False
        saved = (start_task.time.monotonic, start_task.run_task, start_task.main_repo_root,
                 start_task.build_parser)
        self.addCleanup(lambda: (setattr(start_task.time, "monotonic", saved[0]),
                                 setattr(start_task, "run_task", saved[1]),
                                 setattr(start_task, "main_repo_root", saved[2]),
                                 setattr(start_task, "build_parser", saved[3])))
        start_task.time.monotonic = lambda: next(clock)
        start_task.main_repo_root = lambda cwd: root
        start_task.run_task = lambda args: 0
        start_task.build_parser = lambda: type("P", (), {"parse_args": lambda self, a: Args()})()
        start_task.WAITED[0] = 120.0
        self.addCleanup(lambda: start_task.WAITED.__setitem__(0, 0.0))
        start_task.main([])
        self.assertEqual(state.read("timing.json")["worked_seconds"], 480.0)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
