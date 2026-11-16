#!/usr/bin/env python3
#
# serve.py — the conductor service: goals over REST and MCP, on this machine only.
#
#   cond serve [--port 4747] [--repo PATH]...   # run it in the foreground
#   cond serve install                          # run it at login, through launchd
#   cond serve restart | status | uninstall
#
# It listens on 127.0.0.1 only. Goals run in processes of their own, so stopping
# or restarting the service leaves them working. See README.md for the API.

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import actions as ac  # noqa: E402
import mcp  # noqa: E402

DEFAULT_PORT = 4747
MAX_BODY = 100 * 1024 * 1024
LABEL = "com.siroc.conductor"
WEB_DIR = os.path.join(HERE, "web")

ROUTES = []


def route(method, pattern):
    def add(fn):
        ROUTES.append((method, re.compile("^%s$" % pattern), fn))
        return fn
    return add


# --- the API -------------------------------------------------------------------

@route("GET", r"/api/repos")
def get_repos(req):
    return ac.repos()


@route("POST", r"/api/repos")
def post_repo(req):
    return ac.add_repo(req.json().get("path") or "")


@route("GET", r"/api/goals")
def get_all_goals(req):
    return ac.all_goals()


@route("GET", r"/api/repos/(?P<repo>[^/]+)/goals")
def get_goals(req, repo):
    return ac.goals(ac.repo(repo)["path"])


@route("POST", r"/api/repos/(?P<repo>[^/]+)/goals")
def post_goal(req, repo):
    body = req.json()
    return {"goal": ac.start(ac.repo(repo)["path"], body.get("prompt"),
                             [f for f in body.get("files") or [] if isinstance(f, dict)],
                             body.get("base"))}


@route("GET", r"/api/repos/(?P<repo>[^/]+)/goals/(?P<goal>[^/]+)")
def get_goal(req, repo, goal):
    return ac.detail(ac.repo(repo)["path"], goal)


@route("GET", r"/api/repos/(?P<repo>[^/]+)/goals/(?P<goal>[^/]+)/log")
def get_log(req, repo, goal):
    try:
        start = int(req.query.get("from", ["0"])[0])
    except ValueError:
        raise ac.Problem(400, "from is a number")
    return ac.log(ac.repo(repo)["path"], goal, start)


@route("GET", r"/api/repos/(?P<repo>[^/]+)/goals/(?P<goal>[^/]+)/files/(?P<rel>.+)")
def get_file(req, repo, goal, rel):
    path, body = ac.state_file(ac.repo(repo)["path"], goal, urllib.parse.unquote(rel))
    return RawBody(body, mimetypes.guess_type(path)[0] or "application/octet-stream")


ACTIONS = {"stop": ac.stop, "resume": ac.resume, "approve": ac.approve, "done": ac.mark_done,
           "clear": ac.clear, "undo": ac.undo}


@route("POST", r"/api/repos/(?P<repo>[^/]+)/goals/(?P<goal>[^/]+)/(?P<action>[a-z]+)")
def post_action(req, repo, goal, action):
    root = ac.repo(repo)["path"]
    if action == "answer":
        return {"result": ac.answer(root, goal, req.json().get("text"))}
    if action not in ACTIONS:
        raise ac.Problem(404, "no action %s" % action)
    return {"result": ACTIONS[action](root, goal)}


@route("GET", r"/api/repos/(?P<repo>[^/]+)/settings")
def get_settings(req, repo):
    return ac.settings(ac.repo(repo)["path"])


@route("PUT", r"/api/repos/(?P<repo>[^/]+)/settings")
def put_settings(req, repo):
    return ac.set_settings(ac.repo(repo)["path"], req.json())


class RawBody(object):
    def __init__(self, body, content_type):
        self.body, self.content_type = body, content_type


# --- HTTP ----------------------------------------------------------------------

def local_origins(port):
    return {"http://127.0.0.1:%d" % port, "http://localhost:%d" % port}


def allowed(headers, port):
    """Only this machine's own pages: the Host must be this service, and a browser's
    Origin, when it sends one, too. That keeps other sites, and DNS rebinding, out."""
    host = (headers.get("Host") or "").lower()
    if host not in {"127.0.0.1:%d" % port, "localhost:%d" % port}:
        return False
    origin = headers.get("Origin")
    return origin is None or origin.lower() in local_origins(port)


class Handler(BaseHTTPRequestHandler):
    server_version = "conductor"

    def log_message(self, fmt, *args):
        if os.environ.get("COND_SERVE_LOG"):
            BaseHTTPRequestHandler.log_message(self, fmt, *args)

    def json(self):
        try:
            value = json.loads(self.body or b"{}")
        except ValueError:
            raise ac.Problem(400, "the body is not JSON")
        if not isinstance(value, dict):
            raise ac.Problem(400, "the body is not a JSON object")
        return value

    def send(self, status, value, content_type="application/json"):
        if isinstance(value, RawBody):
            body, content_type = value.body, value.content_type
        elif content_type == "application/json":
            body = (json.dumps(value, default=str) + "\n").encode()
        else:
            body = value if isinstance(value, bytes) else str(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def dispatch(self):
        port = self.server.server_address[1]
        if not allowed(self.headers, port):
            return self.send(403, {"error": "only this machine's own pages may use conductor"})
        url = urllib.parse.urlsplit(self.path)
        self.query = urllib.parse.parse_qs(url.query)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.send(413, {"error": "the body is too large"})
        self.body = self.rfile.read(length) if length else b""
        if url.path == "/mcp":
            if self.command != "POST":
                return self.send(405, {"error": "POST JSON-RPC to /mcp"})
            status, reply = mcp.handle(self.body)
            return self.send(status, reply) if reply is not None else self.send(status, b"", "text/plain")
        if not url.path.startswith("/api/"):
            return self.static(url.path)
        for method, pattern, fn in ROUTES:
            m = pattern.match(url.path)
            if m and method == self.command:
                try:
                    return self.send(200, fn(self, **m.groupdict()))
                except ac.Problem as e:
                    return self.send(e.status, {"error": str(e)})
                except Exception as e:  # noqa: BLE001 — the service must answer, not die
                    return self.send(500, {"error": "%s: %s" % (type(e).__name__, e)})
        return self.send(404 if not any(p.match(url.path) for _, p, _ in ROUTES) else 405,
                         {"error": "no %s %s" % (self.command, url.path)})

    def static(self, path):
        if self.command not in ("GET", "HEAD"):
            return self.send(405, {"error": "no %s %s" % (self.command, path)})
        rel = os.path.normpath(path.lstrip("/") or "index.html")
        full = os.path.join(WEB_DIR, rel)
        if rel.startswith("..") or not os.path.isfile(full):
            full = os.path.join(WEB_DIR, "index.html")
        if not os.path.isfile(full):
            return self.send(200, "conductor: the API is under /api, MCP at /mcp\n", "text/plain")
        with open(full, "rb") as f:
            return self.send(200, f.read(), mimetypes.guess_type(full)[0] or "text/html")

    do_GET = do_POST = do_PUT = do_HEAD = dispatch


def make_server(port):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


# --- launchd -------------------------------------------------------------------

def plist_path():
    return os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)


def plist(cond, port, log):
    """The launchd job: the service through an interactive zsh, which loads
    ~/.zshrc and with it the tokens; kept alive, and started at login."""
    command = "exec %s serve --port %d" % (cond, port)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-i</string><string>-c</string><string>%s</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict>
</plist>
""" % (LABEL, esc(command), esc(log), esc(log))


def launchctl(*args):
    proc = subprocess.run(["launchctl"] + list(args), capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def service(cmd, port):
    domain = "gui/%d" % os.getuid()
    if cmd == "install":
        os.makedirs(ac.home(), exist_ok=True)
        os.makedirs(os.path.dirname(plist_path()), exist_ok=True)
        cond = os.path.join(os.path.dirname(HERE), "cond")
        with open(plist_path(), "w") as f:
            f.write(plist(cond, port, os.path.join(ac.home(), "serve.log")))
        launchctl("bootout", "%s/%s" % (domain, LABEL))
        code, out = launchctl("bootstrap", domain, plist_path())
        print("installed: http://127.0.0.1:%d — it starts at login" % port if code == 0
              else "launchctl refused it: %s" % out)
        return code
    if cmd == "uninstall":
        launchctl("bootout", "%s/%s" % (domain, LABEL))
        if os.path.exists(plist_path()):
            os.remove(plist_path())
        print("uninstalled; goals that run carry on")
        return 0
    if cmd == "restart":
        code, out = launchctl("kickstart", "-k", "%s/%s" % (domain, LABEL))
        print("restarted" if code == 0 else "not installed: %s" % out)
        return code
    code, out = launchctl("print", "%s/%s" % (domain, LABEL))
    state = re.search(r"^\s*state = (.+)$", out, re.M)
    print("%s — log: %s" % (state.group(1) if code == 0 and state else "not installed",
                           os.path.join(ac.home(), "serve.log")))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="cond serve", description=(
        "The conductor service: goals over REST and MCP, on 127.0.0.1 only."))
    parser.add_argument("cmd", nargs="?", default="run",
                        choices=("run", "install", "uninstall", "restart", "status"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("COND_PORT") or DEFAULT_PORT))
    parser.add_argument("--repo", action="append", default=[],
                        help="register a repo, by any folder in it; repeat for more")
    args = parser.parse_args(argv)
    if args.cmd != "run":
        return service(args.cmd, args.port)
    for path in args.repo:
        try:
            print("repo %s" % ac.add_repo(path)["id"])
        except ac.Problem as e:
            parser.error(str(e))
    server = make_server(args.port)
    print("conductor on http://127.0.0.1:%d — MCP at /mcp" % args.port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
