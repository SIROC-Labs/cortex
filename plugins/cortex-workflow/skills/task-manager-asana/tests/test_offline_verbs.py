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


if __name__ == "__main__":
    unittest.main()
