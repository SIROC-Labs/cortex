import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402


class TmCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.key = helpers.cache_key(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def tm(self, *args, stdin=None, env_extra=None):
        return helpers.run_tm(list(args), self.home, stdin=stdin, env_extra=env_extra)


class AuthStatusTest(TmCase):
    def test_default_env_var_present_exits_0_and_prints_name(self):
        code, out, _ = self.tm("auth", "status", self.key,
                               env_extra={"ASANA_PERSONAL_ACCESS_TOKEN": "x"})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ASANA_PERSONAL_ACCESS_TOKEN")

    def test_cached_env_var_name_is_honoured(self):
        helpers.write_cache(self.home, self.key, {"provider": "asana", "asana_token_env": "ASANA_TOKEN_WORK"})
        code, out, _ = self.tm("auth", "status", self.key, env_extra={"ASANA_TOKEN_WORK": "x"})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ASANA_TOKEN_WORK")

    def test_no_token_exits_4_and_names_both_transports(self):
        code, out, err = self.tm("auth", "status", self.key)
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        self.assertIn("ASANA_PERSONAL_ACCESS_TOKEN", err)
        self.assertIn("MCP", err)


PROJECTS = [
    {"gid": "1", "name": "ENG | Sprint 26.16", "completed": False, "due_on": "2099-01-01", "archived": False},
    {"gid": "2", "name": "ENG | Sprint 26.15", "completed": False, "due_on": "2000-01-01", "archived": False},
    {"gid": "3", "name": "ENG | Bugs & Issues", "completed": False, "due_on": None, "archived": False},
    {"gid": "4", "name": "ENG | Old Backlog", "completed": False, "due_on": None, "archived": True},
    {"gid": "5", "name": "Personal", "completed": False, "due_on": None, "archived": False},
]


class BoardIngestTest(TmCase):
    def test_ingest_classifies_and_writes_cache(self):
        path = helpers.write_json(self.home, "projects.json", PROJECTS)
        code, out, err = self.tm("board", "ingest", self.key, "--from-json", path, "--workspace-gid", "w1")
        self.assertEqual(code, 0, err)
        cache = helpers.read_cache(self.home, self.key)
        self.assertEqual(cache["provider"], "asana")
        self.assertEqual(cache["workspace_gid"], "w1")
        self.assertEqual(cache["active_sprint"]["gid"], "1")
        self.assertEqual([b["gid"] for b in cache["backlog_boards"]], ["3"])
        self.assertNotIn("asana_token_env", cache)

    def test_ingest_accepts_data_wrapper_on_stdin(self):
        code, _, err = self.tm("board", "ingest", self.key, "--from-json", "-", "--workspace-gid", "w1",
                               stdin=json.dumps({"data": PROJECTS}))
        self.assertEqual(code, 0, err)

    def test_ingest_preserves_patterns_fields_and_token_env(self):
        helpers.write_cache(self.home, self.key, {
            "provider": "asana", "workspace_gid": "w1", "asana_token_env": "ASANA_TOKEN_WORK",
            "sprint_patterns": ["^Sprint Board"], "fields_schema_version": 2,
            "fields": {"3": {"Assignee": {"native": True, "type": "assignee"}}},
        })
        projects = [{"gid": "9", "name": "Sprint Board 26/13", "completed": False, "due_on": None, "archived": False},
                    {"gid": "8", "name": "Sprint Board 26/2", "completed": False, "due_on": None, "archived": False}]
        path = helpers.write_json(self.home, "projects.json", projects)
        code, _, err = self.tm("board", "ingest", self.key, "--from-json", path)
        self.assertEqual(code, 0, err)
        cache = helpers.read_cache(self.home, self.key)
        self.assertEqual(cache["active_sprint"]["gid"], "9")
        self.assertEqual(cache["sprint_patterns"], ["^Sprint Board"])
        self.assertEqual(cache["asana_token_env"], "ASANA_TOKEN_WORK")
        self.assertIn("3", cache["fields"])

    def test_ingest_without_workspace_anywhere_exits_4(self):
        path = helpers.write_json(self.home, "projects.json", PROJECTS)
        code, _, _ = self.tm("board", "ingest", self.key, "--from-json", path)
        self.assertEqual(code, 4)


class BoardResolveOfflineTest(TmCase):
    def test_miss_exits_4_without_network(self):
        code, _, err = self.tm("board", "resolve", self.key, "backlog", "--offline")
        self.assertEqual(code, 4)
        self.assertIn("board ingest", err)

    def test_stale_exits_3_without_refresh(self):
        helpers.write_cache(self.home, self.key, {"provider": "asana", "workspace_gid": "w1",
                                                  "active_sprint": {"gid": "2", "name": "old", "due_on": "2000-01-01"},
                                                  "backlog_boards": []})
        code, _, err = self.tm("board", "resolve", self.key, "active-sprint", "--offline")
        self.assertEqual(code, 3)
        self.assertIn("board ingest", err)

    def test_no_active_sprint_recorded_exits_3(self):
        helpers.write_cache(self.home, self.key, {"provider": "asana", "workspace_gid": "w1",
                                                  "active_sprint": None, "backlog_boards": []})
        code, _, _ = self.tm("board", "resolve", self.key, "active-sprint", "--offline")
        self.assertEqual(code, 3)

    def test_fresh_cache_resolves_from_cache(self):
        helpers.write_cache(self.home, self.key, {"provider": "asana", "workspace_gid": "w1",
                                                  "active_sprint": {"gid": "1", "name": "s", "due_on": "2099-01-01"},
                                                  "backlog_boards": [{"gid": "3", "name": "b"}]})
        code, out, _ = self.tm("board", "resolve", self.key, "backlog", "--offline")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [{"gid": "3", "name": "b"}])


SETTINGS = [
    {"gid": "s1", "custom_field": {"gid": "f1", "name": "IT Priority", "type": "enum",
                                   "enum_options": [{"gid": "o0", "name": "P0"}, {"gid": "o1", "name": "P1"}]}},
    {"gid": "s2", "custom_field": {"gid": "f2", "name": "Estimated time", "type": "number",
                                   "format": "duration", "precision": 0}},
    {"gid": "s3", "custom_field": {"gid": "f3", "name": "Product Status", "type": "enum",
                                   "enum_options": [{"gid": "o8", "name": "Assigned"}, {"gid": "o9", "name": "Ready"}]}},
]


class FieldsIngestTest(TmCase):
    def test_ingest_from_settings_array(self):
        path = helpers.write_json(self.home, "settings.json", SETTINGS)
        code, out, err = self.tm("fields", "ingest", "p1", "--from-json", path)
        self.assertEqual(code, 0, err)
        fm = json.loads(out)
        self.assertEqual(fm["Priority"]["id"], "f1")
        self.assertEqual(fm["Estimate"]["format"], "duration")
        self.assertTrue(fm["Assignee"]["native"])
        cache = helpers.read_cache(self.home, self.key)
        self.assertEqual(cache["fields"]["p1"]["Priority"]["id"], "f1")

    def test_ingest_from_project_object(self):
        path = helpers.write_json(self.home, "project.json",
                                  {"data": {"gid": "p1", "name": "Board", "custom_field_settings": SETTINGS}})
        code, out, err = self.tm("fields", "ingest", "p1", "--from-json", path)
        self.assertEqual(code, 0, err)
        self.assertIn("Product Status", json.loads(out))


class FieldsOfflineTest(TmCase):
    def test_list_offline_miss_exits_2(self):
        code, _, err = self.tm("fields", "list", "p1", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("fields ingest", err)

    def test_resolve_offline_hit(self):
        path = helpers.write_json(self.home, "settings.json", SETTINGS)
        self.tm("fields", "ingest", "p1", "--from-json", path)
        code, out, _ = self.tm("fields", "resolve", "p1", "Priority", "--offline")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["id"], "f1")

    def test_resolve_offline_field_absent_exits_2(self):
        path = helpers.write_json(self.home, "settings.json", SETTINGS)
        self.tm("fields", "ingest", "p1", "--from-json", path)
        code, out, _ = self.tm("fields", "resolve", "p1", "Platform", "--offline")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


class FieldsPlanTest(TmCase):
    def ingest(self):
        path = helpers.write_json(self.home, "settings.json", SETTINGS)
        self.tm("fields", "ingest", "p1", "--from-json", path)

    def test_plan_resolves_enum_estimate_assignee_and_skips_absent(self):
        self.ingest()
        code, out, err = self.tm("fields", "plan", "p1", "Priority=p1", "Estimate=1h 30m",
                                 "Assignee=me", "Platform=Backend")
        self.assertEqual(code, 0, err)
        plan = json.loads(out)
        self.assertEqual(plan["assignee"], "me")
        self.assertEqual(plan["custom_fields"]["f1"], "o1")
        self.assertEqual(plan["custom_fields"]["f2"], 90)
        self.assertEqual(plan["skipped"], ["Platform"])

    def test_plan_bad_enum_value_exits_1(self):
        self.ingest()
        code, _, err = self.tm("fields", "plan", "p1", "Priority=P9")
        self.assertEqual(code, 1)
        self.assertIn("P9", err)

    def test_plan_without_cache_exits_2(self):
        code, _, err = self.tm("fields", "plan", "p1", "Priority=P0")
        self.assertEqual(code, 2)
        self.assertIn("fields ingest", err)


RAW_TASK = {"data": {
    "gid": "t1", "name": "Do it", "notes": "body", "resource_subtype": "default_task",
    "assignee": {"name": "Me"},
    "memberships": [{"project": {"gid": "p1", "name": "Board"}, "section": {"gid": "s1", "name": "Backlog"}}],
    "custom_fields": [
        {"gid": "f1", "name": "IT Priority", "type": "enum", "display_value": "P1", "enum_value": {"name": "P1"}},
        {"gid": "f3", "name": "Product Status", "type": "enum", "display_value": "Assigned"},
        {"gid": "f9", "name": "PD268", "type": "text", "display_value": "PD268-72"},
    ],
}}


class TaskProjectTest(TmCase):
    def test_projection_from_wrapped_task(self):
        path = helpers.write_json(self.home, "task.json", RAW_TASK)
        code, out, err = self.tm("task", "project", "--from-json", path)
        self.assertEqual(code, 0, err)
        p = json.loads(out)
        self.assertEqual(p["ref"], "t1")
        self.assertEqual(p["kind"], "task")
        self.assertEqual(p["status"], "Assigned")
        self.assertEqual(p["fields"]["Priority"], "P1")
        self.assertEqual(p["board"], [{"project": "Board", "section": "Backlog"}])
        self.assertEqual(p["task_id"], "PD268-72")

    def test_non_object_exits_1(self):
        code, _, _ = self.tm("task", "project", "--from-json", "-", stdin="[1,2]")
        self.assertEqual(code, 1)


class StatusPlanTest(TmCase):
    SECTIONS = [{"gid": "s1", "name": "Backlog"}, {"gid": "s2", "name": "In Progress"}]

    def ingest(self):
        path = helpers.write_json(self.home, "settings.json", SETTINGS)
        self.tm("fields", "ingest", "p1", "--from-json", path)

    def test_field_axis_wins(self):
        self.ingest()
        path = helpers.write_json(self.home, "sections.json", self.SECTIONS)
        code, out, err = self.tm("status", "plan", "p1", "Assigned", "--sections-from-json", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"axis": "field", "field_gid": "f3", "option_gid": "o8"})

    def test_section_axis(self):
        self.ingest()
        path = helpers.write_json(self.home, "sections.json", {"data": {"sections": self.SECTIONS}})
        code, out, err = self.tm("status", "plan", "p1", "in progress", "--sections-from-json", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"axis": "section", "section_gid": "s2"})

    def test_neither_exits_1(self):
        self.ingest()
        path = helpers.write_json(self.home, "sections.json", self.SECTIONS)
        code, _, _ = self.tm("status", "plan", "p1", "Nowhere", "--sections-from-json", path)
        self.assertEqual(code, 1)

    def test_no_fields_cache_exits_2(self):
        path = helpers.write_json(self.home, "sections.json", self.SECTIONS)
        code, _, _ = self.tm("status", "plan", "p1", "Backlog", "--sections-from-json", path)
        self.assertEqual(code, 2)


class RenderBodyTest(TmCase):
    def test_markdown_comment_renders_html_text(self):
        code, out, err = self.tm("render", "body", "Hello **there**\n\n- a\n- b", "--for", "comment")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertIn("html_text", payload)
        self.assertTrue(payload["html_text"].startswith("<body>"))
        self.assertIn("<strong>there</strong>", payload["html_text"])
        self.assertNotIn("<br>", payload["html_text"])

    def test_plain_notes_from_body_file(self):
        path = os.path.join(self.home, "body.md")
        with open(path, "w") as f:
            f.write("plain words only")
        code, out, err = self.tm("render", "body", "--body-file", path, "--for", "notes")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(set(payload.keys()) & {"notes", "html_notes"}, set(payload.keys()))

    def test_empty_body_exits_1(self):
        code, _, _ = self.tm("render", "body", "   ")
        self.assertEqual(code, 1)


class MilestoneClassifyTest(TmCase):
    def test_classify_milestones_with_subtasks(self):
        groups = [
            {"milestone": {"gid": "a", "name": "M1"}, "subtasks": [{"gid": "b", "name": "T1"}]},
            {"gid": "c", "name": "M2", "resource_subtype": "milestone", "subtasks": []},
        ]
        path = helpers.write_json(self.home, "groups.json", groups)
        code, out, err = self.tm("milestone", "classify", "--from-json", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), [
            {"name": "M1", "ref": "a", "expanded": True},
            {"name": "M2", "ref": "c", "expanded": False},
        ])

    def test_non_array_exits_1(self):
        code, _, _ = self.tm("milestone", "classify", "--from-json", "-", stdin="{}")
        self.assertEqual(code, 1)


RAW_SUBTASK = {"data": {
    "gid": "s1", "name": "BE: add field", "resource_subtype": "default_task",
    "completed": False, "assignee": None, "memberships": [],
    "parent": {"gid": "m1", "name": "Milestone", "resource_subtype": "milestone"},
    "custom_fields": [],
}}
RAW_PARENT = {"data": {
    "gid": "m1", "name": "Milestone", "resource_subtype": "milestone",
    "memberships": [{"project": {"gid": "ow", "name": "ENG | Ongoing Work"}, "section": {"gid": "q", "name": "Ready to execute"}}],
}}


class TaskProjectSubtaskTest(TmCase):
    def test_subtask_projection_carries_parent_and_its_boards(self):
        task = helpers.write_json(self.home, "sub.json", RAW_SUBTASK)
        parent = helpers.write_json(self.home, "parent.json", RAW_PARENT)
        code, out, err = self.tm("task", "project", "--from-json", task, "--parent-from-json", parent)
        self.assertEqual(code, 0, err)
        p = json.loads(out)
        self.assertEqual(p["board"], [])
        self.assertFalse(p["completed"])
        self.assertEqual(p["parent"], {"ref": "m1", "name": "Milestone", "kind": "milestone",
                                       "board": [{"project": "ENG | Ongoing Work", "section": "Ready to execute"}]})

    def test_subtask_without_parent_read_names_parent_with_no_boards(self):
        task = helpers.write_json(self.home, "sub.json", RAW_SUBTASK)
        code, out, err = self.tm("task", "project", "--from-json", task)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["parent"]["board"], [])

    def test_top_level_task_has_no_parent_key(self):
        path = helpers.write_json(self.home, "task.json", RAW_TASK)
        code, out, err = self.tm("task", "project", "--from-json", path)
        self.assertEqual(code, 0, err)
        self.assertNotIn("parent", json.loads(out))


def _import_tm():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    import tm
    return tm


class FakeAsana:
    """Records every request tm.py makes and answers from canned routes."""

    def __init__(self, gets):
        self.gets = gets
        self.calls = []

    def get(self, url, token):
        self.calls.append(("GET", url, None))
        for prefix, body in self.gets:
            if prefix in url:
                return body
        raise AssertionError("unexpected GET " + url)

    def send(self, url, token, method, payload):
        self.calls.append((method, url, payload))
        if url.endswith("/tasks") and method == "POST":
            return {"data": {"gid": "new1", "name": payload["data"].get("name")}}
        return {"data": {}}

    def writes(self):
        return [(m, u.split("/api/1.0")[-1], p) for m, u, p in self.calls if m != "GET"]


class InProcessCase(unittest.TestCase):
    def run_verb(self, fn, args, fake):
        tm = _import_tm()
        saved = (tm.api_get, tm.api_json, tm.resolve_token, tm.workspace_gid_from, tm.cache_util.project_key)
        tm.api_get, tm.api_json = fake.get, fake.send
        tm.resolve_token = lambda key: "t"
        tm.workspace_gid_from = lambda key: "w1"
        tm.cache_util.project_key = lambda: "k"
        out = io.StringIO()
        saved_out, sys.stdout = sys.stdout, out
        try:
            with self.assertRaises(SystemExit) as ctx:
                fn(args)
        finally:
            sys.stdout = saved_out
            tm.api_get, tm.api_json, tm.resolve_token, tm.workspace_gid_from, tm.cache_util.project_key = saved
        return ctx.exception.code, out.getvalue()


class TaskCreateMilestoneTest(InProcessCase):
    GETS = [
        ("/tasks/ms1?opt_fields=projects.gid", {"data": {"projects": [{"gid": "ow"}]}}),
        ("/tasks/ms1?opt_fields=name", RAW_PARENT),
        ("/tasks/new1?", {"data": {"gid": "new1", "name": "Card", "completed": False,
                                   "parent": {"gid": "ms1", "name": "Milestone"}}}),
    ]

    def test_creates_subtask_without_joining_the_milestone_board(self):
        tm = _import_tm()
        fake = FakeAsana(self.GETS)
        code, out = self.run_verb(tm.task_create, ["--title", "Card", "--milestone", "ms1"], fake)
        self.assertEqual(code, 0)
        writes = fake.writes()
        self.assertEqual(writes, [("POST", "/tasks", {"data": {"name": "Card", "workspace": "w1", "parent": "ms1"}})])
        self.assertEqual(json.loads(out)["parent"]["ref"], "m1")

    def test_product_board_is_added(self):
        tm = _import_tm()
        fake = FakeAsana(self.GETS)
        code, _ = self.run_verb(tm.task_create, ["pd254", "--title", "Card", "--milestone", "ms1"], fake)
        self.assertEqual(code, 0)
        self.assertIn(("POST", "/tasks/new1/addProject", {"data": {"project": "pd254"}}), fake.writes())

    def test_milestone_board_is_refused_before_any_write(self):
        tm = _import_tm()
        fake = FakeAsana(self.GETS)
        code, _ = self.run_verb(tm.task_create, ["ow", "--title", "Card", "--milestone", "ms1"], fake)
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes(), [])

    def test_no_board_and_no_milestone_is_a_usage_error(self):
        tm = _import_tm()
        fake = FakeAsana([])
        code, _ = self.run_verb(tm.task_create, ["--title", "Card"], fake)
        self.assertEqual(code, 1)
        self.assertEqual(fake.calls, [])


class MilestoneEnsureTest(InProcessCase):
    def board(self, tasks):
        return [("/projects/ow/tasks", {"data": tasks})]

    def test_reuses_milestone_by_exact_name_without_writing(self):
        tm = _import_tm()
        fake = FakeAsana(self.board([{"gid": "m9", "name": "Ship X", "resource_subtype": "milestone"},
                                     {"gid": "t1", "name": "Ship X", "resource_subtype": "default_task"}]))
        code, out = self.run_verb(tm.milestone_ensure, ["ow", "Ship X"], fake)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"name": "Ship X", "ref": "m9", "created": False})
        self.assertEqual(fake.writes(), [])

    def test_creates_milestone_type_board_member(self):
        tm = _import_tm()
        fake = FakeAsana(self.board([{"gid": "t1", "name": "Ship X", "resource_subtype": "default_task"}]))
        code, out = self.run_verb(tm.milestone_ensure, ["ow", "Ship X"], fake)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["created"], True)
        self.assertEqual(fake.writes(), [
            ("POST", "/tasks", {"data": {"name": "Ship X", "workspace": "w1", "resource_subtype": "milestone"}}),
            ("POST", "/tasks/new1/addProject", {"data": {"project": "ow"}}),
        ])


class MilestonePureTest(unittest.TestCase):
    def test_project_subtask_shape(self):
        tm = _import_tm()
        self.assertEqual(tm.project_subtask({"gid": "s", "name": "N", "created_at": "2026-01-01T00:00:00Z",
                                             "completed": True, "assignee": {"gid": "u", "name": "U"}}),
                         {"ref": "s", "name": "N", "created_at": "2026-01-01T00:00:00Z", "completed": True,
                          "assignee": {"ref": "u", "name": "U"}})

    def test_executor_is_a_canonical_field(self):
        tm = _import_tm()
        self.assertEqual(tm.match_canonical("Executor"), "Executor")


class MembershipProjectionTest(unittest.TestCase):
    def test_projection_shape(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import tm
        out = tm._membership_projection([
            {"project": {"gid": "p", "name": "Board"}, "section": {"gid": "s", "name": "Backlog"}},
            "junk",
        ])
        self.assertEqual(out, [{"board": {"ref": "p", "name": "Board"}, "column": {"ref": "s", "name": "Backlog"}}])


if __name__ == "__main__":
    unittest.main()
