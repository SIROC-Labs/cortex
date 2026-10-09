import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import cache_util  # noqa: E402


class ProjectKeyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        self._env = os.environ.pop("CORTEX_PROJECT", None)
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        if self._env is not None:
            os.environ["CORTEX_PROJECT"] = self._env
        else:
            os.environ.pop("CORTEX_PROJECT", None)
        self._tmp.cleanup()

    def test_environment_profile_wins_over_git(self):
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], check=True)
        os.environ["CORTEX_PROJECT"] = "humanus"
        self.assertEqual(cache_util.project_key(), "humanus")

    def test_environment_profile_is_normalised(self):
        os.environ["CORTEX_PROJECT"] = "My Project!"
        self.assertEqual(cache_util.project_key(), "my-project-")

    def test_empty_environment_profile_is_ignored(self):
        os.environ["CORTEX_PROJECT"] = ""
        self.assertEqual(cache_util.project_key(), os.path.basename(os.path.realpath(self._tmp.name)))

    def test_git_remote_key_without_profile(self):
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], check=True)
        self.assertEqual(cache_util.project_key(), "git-github-com-org-repo-git")


if __name__ == "__main__":
    unittest.main()
