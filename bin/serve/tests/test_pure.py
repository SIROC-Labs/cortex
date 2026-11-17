import base64
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import actions as ac  # noqa: E402
import mcp  # noqa: E402
import serve  # noqa: E402


class Repo(unittest.TestCase):
    """A git repo, conductor's home in a temp folder, and goals that never launch."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        old = os.environ.get("COND_HOME")
        os.environ["COND_HOME"] = self.home
        self.addCleanup(lambda: os.environ.__setitem__("COND_HOME", old) if old
                        else os.environ.pop("COND_HOME", None))
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.launched = []
        launch = ac.gl.launch
        ac.gl.launch = lambda root, gid: self.launched.append(gid)
        self.addCleanup(setattr, ac.gl, "launch", launch)

    def wait_on(self, gid, record):
        goal = ac.gl.Goal(self.root, gid)
        goal.state.write("awaiting.json", dict(record, asked_at="2026-11-16T10:00:00.000000Z"))
        return goal


class TestRepos(Repo):
    def test_repos_are_named_by_their_folder_and_unique(self):
        self.assertEqual([r["id"] for r in ac.repo_ids(["/a/web", "/b/web", "/c/My Repo"])],
                         ["web", "web-2", "my-repo"])

    def test_a_repo_is_added_once_by_any_folder_in_it(self):
        os.makedirs(os.path.join(self.root, "sub"))
        first = ac.add_repo(os.path.join(self.root, "sub"))
        ac.add_repo(self.root)
        self.assertEqual(ac.repos(), [first])
        self.assertEqual(first["path"], self.root)
        with self.assertRaises(ac.Problem):
            ac.add_repo(self.home)


class TestActions(Repo):
    def test_a_goal_starts_from_a_prompt_and_uploaded_files(self):
        gid = ac.start(self.root, "Make the badge red", [
            {"name": "../shot.png", "data": base64.b64encode(b"png").decode()}])
        self.assertEqual(self.launched, [gid])
        self.assertEqual(ac.repos()[0]["path"], self.root)
        detail = ac.detail(self.root, gid)
        self.assertEqual((detail["name"], detail["files"], detail["waiting"]),
                         ("Make the badge red", ["inputs/shot.png"], False))
        self.assertEqual(ac.state_file(self.root, gid, "inputs/shot.png")[1], b"png")

    def test_a_goal_goes_into_the_queue_into_branch_unless_another_is_named(self):
        ac.set_settings(self.root, {"base": "feature/m1"})
        first = ac.start(self.root, "One")
        second = ac.start(self.root, "Two", base="feature/x")
        self.assertEqual([ac.detail(self.root, g)["base"] for g in (first, second)],
                         ["feature/m1", "feature/x"])

    def test_bad_starts_are_refused(self):
        for prompt, files in (("  ", []), ("x", [{"name": "a", "data": "%%%"}]), ("x", ["/no/such"])):
            with self.assertRaises(ac.Problem):
                ac.start(self.root, prompt, files)
        self.assertEqual(self.launched, [])

    def test_only_the_goal_s_own_files_are_readable(self):
        gid = ac.start(self.root, "x")
        goal = ac.gl.Goal(self.root, gid)
        goal.state.write("secret.json", {})
        for rel in ("goal.json", "../../x", "inputs/../goal.json", "secret.json"):
            with self.assertRaises(ac.Problem):
                ac.state_file(self.root, gid, rel)
        with self.assertRaises(ac.Problem):
            ac.detail(self.root, "../etc")

    def test_an_answer_reaches_the_question_it_answers(self):
        gid = ac.start(self.root, "x")
        with self.assertRaises(ac.Problem):
            ac.answer(self.root, gid, "Blue")
        goal = self.wait_on(gid, {"kind": "questions", "questions": [{"q": "Colour?"}]})
        self.assertTrue(ac.detail(self.root, gid)["waiting"])
        with self.assertRaises(ac.Problem):
            ac.approve(self.root, gid)
        ac.answer(self.root, gid, " Blue ")
        self.assertEqual(ac.st.local_answer(goal.state.read(ac.st.ANSWER_FILE),
                                            "2026-11-16T10:00:00.000000Z"), "Blue")

    def test_approving_a_plan_answers_it_with_an_approval(self):
        gid = ac.start(self.root, "x")
        goal = self.wait_on(gid, {"kind": "plan", "detail": "- API"})
        ac.approve(self.root, gid)
        text = goal.state.read(ac.st.ANSWER_FILE)["text"]
        self.assertTrue(ac.gl.approves(text))

    def test_stop_and_resume_follow_whether_it_runs(self):
        gid = ac.start(self.root, "x")
        self.launched.clear()
        with self.assertRaises(ac.Problem):
            ac.stop(self.root, gid)
        ac.resume(self.root, gid)
        self.assertEqual(self.launched, [gid])
        ac.gl.Goal(self.root, gid).update(status="done", phase="merged", pr_url="u")
        with self.assertRaises(ac.Problem):
            ac.resume(self.root, gid)

    def test_the_log_reads_on_from_where_it_left_off(self):
        gid = ac.start(self.root, "x")
        with open(ac.gl.Goal(self.root, gid).log, "w") as f:
            f.write("one\ntwo\n")
        first = ac.log(self.root, gid)
        self.assertEqual(first, {"text": "one\ntwo\n", "next": 8})
        self.assertEqual(ac.log(self.root, gid, first["next"]), {"text": "", "next": 8})
        self.assertEqual(ac.log(self.root, gid, -4)["text"], "two\n")

    def test_settings_have_defaults_and_bad_values_are_refused(self):
        self.assertEqual(ac.settings(self.root)["models"]["check"], ac.gl.DEFAULT_CHECK_MODEL)
        self.assertIsNone(ac.settings(self.root)["base"])
        for bad in ({"colour": 1}, {"usage_threshold": 0}, {"goal_gate": "never"},
                    {"models": {"check_effort": "huge"}}, {"models": {"lead": ""}},
                    {"base": "a b"}, {"models": {"judge": "x"}}):
            with self.assertRaises(ac.Problem):
                ac.set_settings(self.root, bad)
        done = ac.set_settings(self.root, {"usage_threshold": 60, "models": {"lead": "openai/gpt-x"}})
        self.assertEqual((done["usage_threshold"], done["models"]["lead"], done["models"]["subagent"]),
                         (60, "openai/gpt-x", ac.gl.DEFAULT_SUBAGENT_MODEL))


class TestDescribe(unittest.TestCase):
    def test_what_waits_on_you_comes_first_unless_the_goal_is_stopped(self):
        plan = {"asked_at": "t", "kind": "plan"}
        self.assertEqual(ac.describe({"status": "waiting", "alive": True, "awaiting": plan}),
                         ("the plan waits on your review", "warn", "waiting on you"))
        self.assertEqual(ac.describe({"status": "waiting", "alive": True, "awaiting": {
            "asked_at": "t", "questions": [{"q": "a"}, {"q": "b"}]}})[0], "has 2 questions for you")
        self.assertEqual(ac.describe({"status": "stopped", "alive": False, "awaiting": plan})[2], "stopped")

    def test_a_live_status_without_its_process_is_a_crash(self):
        self.assertEqual(ac.describe({"status": "working", "alive": False})[1:], ("bad", "stopped"))
        self.assertEqual(ac.describe({"status": "working", "alive": True, "phase": "planning"})[2], "analysing")
        self.assertEqual(ac.describe({"status": "done", "phase": "merged"}), ("merged", "", "merged"))


class TestTimeline(unittest.TestCase):
    def test_the_log_becomes_steps_with_their_lines_and_costs(self):
        import time
        created = time.mktime((2026, 11, 16, 13, 0, 0, 0, 0, -1))
        text = ("13:21:42  Reading the ask\n  1 file(s)\n\n13:22:00  Round 1\n  lead: calling claude\n"
                "Traceback: raw output\n\n23:59:00  Round 2\n\n01:40:22  Review comments on the PR\n")
        steps = ac.timeline(text, created, [{"started": created + 22 * 60 + 5, "cost": 2.5},
                                            {"started": created + 22 * 60 + 9, "cost": 0.5},
                                            {"started": None, "cost": 9}])
        self.assertEqual([s["title"] for s in steps],
                         ["Reading the ask", "Round 1", "Round 2", "Review comments on the PR"])
        self.assertEqual(steps[1]["lines"], ["lead: calling claude", "Traceback: raw output"])
        self.assertEqual(steps[1]["cost"], 3.0)
        self.assertEqual(steps[0]["at"], created + 21 * 60 + 42)
        self.assertEqual(steps[3]["at"] - steps[2]["at"], 60 + 100 * 60 + 22)
        self.assertEqual(ac.timeline("", created), [])


class TestCards(unittest.TestCase):
    def step(self, title, lines=(), at=0, cost=0.0):
        return {"title": title, "lines": list(lines), "at": at, "cost": cost}

    def test_a_round_takes_the_tasks_it_handed_out_and_phases_follow_the_work(self):
        steps = [self.step("Reading the ask"), self.step("Round 1", ["lead: calling claude", "Planned it."], 10, 1.0),
                 self.step("Reviewing the acceptance criteria", ["review: calling claude", "review: 26 turns",
                                                                 "review: 2 problem(s), 0 question(s)", "- gap"], 20),
                 self.step("The plan is ready for your review", ["answered", "the plan is approved"], 30),
                 self.step("Round 2", ["Wave 1."], 40, 0.5),
                 self.step("Running 2 task(s) from the lead", ["task: API on sonnet", "question: E1 where on sonnet",
                                                              "API: done · merged", "E1 where: done"], 50, 2.0),
                 self.step("Syncing with main", [], 60), self.step("Checking against the ask", ["verdict: 1 gap(s), 0 question(s)"], 70),
                 self.step("Round 3", [], 80), self.step("Watching the PR for review comments and the merge", [], 90),
                 self.step("Review comments on the PR", [], 100), self.step("Round 4", [], 110)]
        cs = ac.cards(steps)
        self.assertEqual([(c["title"], c["phase"]) for c in cs], [
            ("Reading the ask", "Setup"), ("Round 1", "Analysis and plan"),
            ("Reviewing the acceptance criteria", "Analysis and plan"),
            ("The plan is ready for your review", "Analysis and plan"), ("Round 2", "Build"),
            ("Syncing with main", "Verify and ship"), ("Checking against the ask", "Verify and ship"),
            ("Round 3", "Build"), ("Watching the PR for review comments and the merge", "PR review"),
            ("Review comments on the PR", "Revision 1"), ("Round 4", "Revision 1")])
        round2 = cs[4]
        self.assertEqual((round2["cost"], round2["until"]), (2.5, 60))
        self.assertEqual(round2["tasks"], [
            {"kind": "code", "name": "API", "model": "sonnet", "result": "done · merged"},
            {"kind": "explore", "name": "E1 where", "model": "sonnet", "result": "done"}])
        self.assertEqual(round2["summary"], "Running 2 task(s) · Wave 1.")
        self.assertEqual(cs[1]["summary"], "Planned it.")
        self.assertEqual(cs[2]["summary"], "2 problem(s), 0 question(s)")
        self.assertEqual(cs[3]["summary"], "answered")
        self.assertEqual(ac.card_summary({"kind": "check", "lines": ["check: 3 turns", "verdict: done"]}), "clean")
        self.assertIsNone(cs[-1]["until"])


class TestHTTP(Repo):
    def setUp(self):
        Repo.setUp(self)
        self.server = serve.make_server(0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.rid = ac.add_repo(self.root)["id"]

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, payload, dict({"Content-Type": "application/json"},
                                                 **(headers or {})))
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(data) if data else None
        except ValueError:
            return resp.status, data

    def test_a_goal_through_the_api(self):
        status, body = self.call("POST", "/api/repos/%s/goals" % self.rid, {
            "prompt": "Fix the badge", "files": [{"name": "a.txt", "data": base64.b64encode(b"hi").decode()}]})
        self.assertEqual(status, 200)
        gid = body["goal"]
        status, goals = self.call("GET", "/api/goals")
        self.assertEqual([(g["repo"], g["id"]) for g in goals], [(self.rid, gid)])
        status, goal = self.call("GET", "/api/repos/%s/goals/%s" % (self.rid, gid))
        self.assertEqual((status, goal["files"]), (200, ["inputs/a.txt"]))
        status, raw = self.call("GET", "/api/repos/%s/goals/%s/files/inputs/a.txt" % (self.rid, gid))
        self.assertEqual((status, raw), (200, b"hi"))
        self.wait_on(gid, {"kind": "plan"})
        self.assertEqual(self.call("POST", "/api/repos/%s/goals/%s/approve" % (self.rid, gid)),
                         (200, {"result": "approved"}))
        self.assertEqual(self.call("POST", "/api/repos/%s/goals/%s/stop" % (self.rid, gid))[0], 409)
        self.assertEqual(self.call("POST", "/api/repos/%s/goals/%s/fly" % (self.rid, gid))[0], 404)
        self.assertEqual(self.call("GET", "/api/repos/nope/goals")[0], 404)
        status, settings = self.call("PUT", "/api/repos/%s/settings" % self.rid, {"goal_gate": "auto"})
        self.assertEqual((status, settings["goal_gate"]), (200, "auto"))
        self.assertEqual(self.call("PUT", "/api/repos/%s/settings" % self.rid, {"goal_gate": "x"})[0], 400)

    def test_other_sites_and_other_hosts_are_refused(self):
        self.assertEqual(self.call("GET", "/api/repos", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("GET", "/api/repos", headers={"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.call("GET", "/api/repos", headers={
            "Origin": "http://localhost:%d" % self.port})[0], 200)

    def test_mcp_lists_and_calls_tools(self):
        status, init = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                  "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual((status, init["result"]["protocolVersion"]), (200, "2025-03-26"))
        self.assertEqual(self.call("POST", "/mcp", {"jsonrpc": "2.0",
                                                    "method": "notifications/initialized"})[0], 202)
        status, tools = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("start_goal", [t["name"] for t in tools["result"]["tools"]])
        status, started = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                     "params": {"name": "start_goal", "arguments": {
                                                         "repo": self.rid, "prompt": "Do it"}}})
        gid = json.loads(started["result"]["content"][0]["text"])["goal"]
        self.assertEqual(self.launched, [gid])
        status, refused = self.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                     "params": {"name": "approve_plan", "arguments": {
                                                         "repo": self.rid, "goal": gid}}})
        self.assertTrue(refused["result"]["isError"])
        self.assertEqual(self.call("GET", "/mcp")[0], 405)


class TestMCP(unittest.TestCase):
    def test_bad_messages_get_json_rpc_errors(self):
        self.assertEqual(mcp.handle(b"{")[1]["error"]["code"], -32700)
        self.assertEqual(mcp.handle(b'{"jsonrpc": "2.0", "id": 1, "method": "x"}')[1]["error"]["code"],
                         -32601)
        status, replies = mcp.handle(b'[{"jsonrpc": "2.0", "id": 1, "method": "ping"},'
                                     b' {"jsonrpc": "2.0", "method": "notifications/x"}]')
        self.assertEqual((status, replies), (200, [{"jsonrpc": "2.0", "id": 1, "result": {}}]))

    def test_every_tool_has_a_closed_schema(self):
        for tool in mcp.TOOLS:
            self.assertFalse(tool["inputSchema"]["additionalProperties"], tool["name"])
            for name in tool["inputSchema"]["required"]:
                self.assertIn(name, tool["inputSchema"]["properties"], tool["name"])


class TestLaunchd(unittest.TestCase):
    def test_the_job_loads_zshrc_and_runs_the_service(self):
        text = serve.plist("/x/cond", 4747, "/h/serve.log")
        self.assertIn("<string>/bin/zsh</string><string>-i</string><string>-c</string>"
                      "<string>exec /x/cond serve --port 4747</string>", text)
        self.assertIn("<key>KeepAlive</key><true/>", text)


if __name__ == "__main__":
    unittest.main()
