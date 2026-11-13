import importlib.util
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("migrate", os.path.join(HERE, "migrate.py"))
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


class TestRewrite(unittest.TestCase):
    def test_paths_under_the_old_folder_move(self):
        text = '{"worktree": "/r/m/.cortex/worktrees/HCI-4+x", "allow": "//r/m/.cortex/state/g/**"}'
        self.assertEqual(migrate.rewrite(text, "/r/m"),
                         '{"worktree": "/r/m/.conductor/worktrees/HCI-4+x", '
                         '"allow": "//r/m/.conductor/state/g/**"}')

    def test_claude_folders_move(self):
        self.assertEqual(migrate.rewrite("projects/-r-m--cortex-worktrees-g-1", "/r/m"),
                         "projects/-r-m--conductor-worktrees-g-1")

    def test_other_repos_and_lookalikes_stay(self):
        text = "/r/other/.cortex/state /r/m/.cortex-old /r/m/.cortexes ~/.cortex/cortex-workflow"
        self.assertEqual(migrate.rewrite(text, "/r/m"), text)


class TestRenamedFolder(unittest.TestCase):
    def test_worktree_folders_of_the_repo(self):
        self.assertEqual(migrate.renamed_folder("-r-m--cortex-worktrees-g-1", "/r/m"),
                         "-r-m--conductor-worktrees-g-1")
        self.assertEqual(migrate.renamed_folder("-r-m--cortex", "/r/m"), "-r-m--conductor")

    def test_anything_else_is_left(self):
        self.assertIsNone(migrate.renamed_folder("-r-m", "/r/m"))
        self.assertIsNone(migrate.renamed_folder("-r-m--cortexes", "/r/m"))
        self.assertIsNone(migrate.renamed_folder("-r-other--cortex-worktrees-g", "/r/m"))


class TestLiveness(unittest.TestCase):
    def test_only_running_daemons_count(self):
        records = [{"pid": 1}, {"pid": 2}, {"pid": True}, {}, "junk"]
        self.assertEqual(migrate.live_pids(records, lambda pid: pid == 2), [2])

    def test_processes_working_in_old_state(self):
        lines = ["12 claude -p --add-dir /r/m/.cortex/worktrees/g", "13 vim /r/m/README.md"]
        self.assertEqual(migrate.processes_in(lines, ["/r/m"]), lines[:1])


class TestPlanRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "repo")
        self.projects = os.path.join(base, "projects")
        os.makedirs(self.projects)
        git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", "-b", "main", self.root], check=True)
        subprocess.run(git + ["-C", self.root, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        self.wt = os.path.join(self.root, ".cortex", "worktrees", "g")
        subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "-b", "g", self.wt], check=True)
        os.makedirs(os.path.join(self.root, ".cortex", "state", "g"))
        with open(os.path.join(self.root, ".cortex", "state", "g", "goal.json"), "w") as f:
            f.write('{"worktree": "%s"}' % self.wt)
        self.session = os.path.join(self.projects, migrate.claude_folder(self.wt))
        os.makedirs(self.session)

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self):
        for _, action in migrate.plan_repo(self.root, self.projects):
            action()

    def test_state_worktrees_and_sessions_move_together(self):
        self.apply()
        new_wt = os.path.join(self.root, ".conductor", "worktrees", "g")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".cortex")))
        with open(os.path.join(self.root, ".conductor", "state", "g", "goal.json")) as f:
            self.assertEqual(f.read(), '{"worktree": "%s"}' % new_wt)
        listed = subprocess.run(["git", "-C", self.root, "worktree", "list", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout
        self.assertIn("worktree %s\n" % new_wt, listed)
        self.assertNotIn("prunable", listed)
        status = subprocess.run(["git", "-C", new_wt, "status", "--porcelain"],
                                capture_output=True, text=True)
        self.assertEqual(status.returncode, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.projects, migrate.claude_folder(new_wt))))
        self.assertFalse(os.path.exists(self.session))

    def test_a_repo_already_migrated_is_skipped(self):
        os.makedirs(os.path.join(self.root, ".conductor"))
        steps = migrate.plan_repo(self.root, self.projects)
        self.assertEqual([action for _, action in steps], [None])

    def test_a_repo_without_old_state_has_nothing_to_do(self):
        self.apply()
        self.assertEqual(migrate.plan_repo(self.root, self.projects), [])


if __name__ == "__main__":
    unittest.main()
