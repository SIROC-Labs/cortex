import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import control  # noqa: E402


class TestControlFile(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_changes_are_written_back_and_cortex_ignores_itself(self):
        with control.control_file(self.root) as c:
            c["base"] = "feature/x"
        self.assertEqual(control.read_control(self.root), {"base": "feature/x"})
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".cortex", ".gitignore")))

    def test_no_file_reads_as_empty(self):
        self.assertEqual(control.read_control(self.root), {})

    def test_keys_from_before_are_kept(self):
        with control.control_file(self.root) as c:
            c.update(queue=[{"gid": "1"}], sprint={"gid": "9"})
        with control.control_file(self.root) as c:
            c["base"] = "main"
        self.assertEqual(control.read_control(self.root)["queue"], [{"gid": "1"}])


if __name__ == "__main__":
    unittest.main()
