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


if __name__ == "__main__":
    unittest.main()
