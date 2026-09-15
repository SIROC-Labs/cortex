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

from agent import AgentResult  # noqa: E402

from start_task import (  # noqa: E402
    State,
    checkpoint_problems,
    ensure_cortex_dir,
    evaluate_gate,
    extract_external_links,
    extract_last_json_block,
    failure_detail,
    format_questions_comment,
    live_run_pid,
    parse_agent_questions,
    phases_to_run,
    poll_interval,
    select_answer,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)


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
