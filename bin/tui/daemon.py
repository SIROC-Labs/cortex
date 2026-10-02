#!/usr/bin/env python3
#
# daemon.py — the background half of `cortex tui`: one daemon per repo that works
# whatever is queued through the shared engine.
#
# The TUI and the daemon share nothing but files under `<repo>/.cortex/queue/`:
#
#   control.json  written by the TUI — the queue, the sprint, and commands
#                 (stop, retry) the daemon applies once each
#   state.json    written by the daemon — the engine's tasks and records
#   daemon.json   written by the daemon — its pid and a heartbeat
#   daemon.log    the daemon's own output; each run logs under logs/
#
# Every live daemon also registers in `~/.cortex/cli/daemons/`, so a TUI opened in
# any terminal can find every one of them — and every start-task run still going
# shows up in its repo whether or not a daemon owns it. Nothing runs unseen.

import contextlib
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "run-milestone"))
from engine import Engine, Stop, kill_tree, log, st  # noqa: E402

QUEUE_DIRNAME = "queue"
REGISTRY = os.path.join(os.path.expanduser("~"), ".cortex", "cli", "daemons")
SERVE_TICK = 2
# A daemon whose heartbeat is older than this is alive but not looping — stuck in
# a slow call, or wedged.
STALE_AFTER = 120


# The code a daemon runs in-process. When any of it changes, the daemon restarts
# onto the new code at the first moment no run is in flight.
CODE_FILES = (
    os.path.join(HERE, "daemon.py"),
    os.path.join(os.path.dirname(HERE), "run-milestone", "engine.py"),
    os.path.join(os.path.dirname(HERE), "start-task", "start_task.py"),
)
COMMANDS = ("stop", "retry", "merge", "merge-cancel")


# --- pure helpers (unit-tested) ---------------------------------------------

def code_version(paths=CODE_FILES):
    """A short fingerprint of the daemon's code, from the files' change times."""
    digest = hashlib.sha1()
    for path in paths:
        try:
            digest.update(("%s:%d;" % (path, os.stat(path).st_mtime_ns)).encode())
        except OSError:
            digest.update(("%s:missing;" % path).encode())
    return digest.hexdigest()[:12]


def command_feedback(sent, applied, results, alive, now, busy=()):
    """What to tell the person about a command they sent: (message, settled).
    `sent` is {id, op, key, at}; `results` the daemon's record of what it did."""
    result = next((r for r in results or [] if r.get("id") == sent["id"]), None)
    if applied >= sent["id"]:
        if result and not result.get("ok"):
            return ("the daemon did not act on %s for %s: %s"
                    % (sent["op"], sent["key"], result.get("note") or "unknown command"), True)
        return ({"merge": "merging %s — the Runs tab shows each step" % sent["key"],
                 "merge-cancel": "no longer merging %s" % sent["key"],
                 "stop": "stopped %s" % sent["key"],
                 "retry": "%s will start again when it is ready" % sent["key"]}
                .get(sent["op"], "done"), True)
    if not alive:
        return ("the daemon is not running, so %s for %s is waiting — s on the Daemons "
                "tab starts it" % (sent["op"], sent["key"]), False)
    if busy:
        return ("the daemon is busy (%s) — %s for %s is next"
                % ("; ".join(busy), sent["op"], sent["key"]), False)
    if now - sent["at"] > 15:
        return "the daemon has not picked up %s for %s yet…" % (sent["op"], sent["key"]), False
    return "%s asked for %s…" % (sent["op"], sent["key"]), False

def empty_control():
    return {"queue": [], "sprint": None, "commands": []}


def queue_add(control, items):
    """Append tasks to the queue, skipping any already in it. `items` are
    {gid, board, name}. Returns the gids actually added."""
    have = {q["gid"] for q in control["queue"]}
    added = []
    for item in items:
        if item["gid"] in have:
            continue
        control["queue"].append({"gid": item["gid"], "board": item.get("board"),
                                 "name": item.get("name"), "added": time.time()})
        have.add(item["gid"])
        added.append(item["gid"])
    return added


def queue_remove(control, gids):
    gids = set(gids)
    control["queue"] = [q for q in control["queue"] if q["gid"] not in gids]


def add_command(control, op, gid, applied=0):
    """Queue a command for the daemon. Ids only grow, so the daemon applies each
    once; commands it has already applied are dropped as new ones are added."""
    commands = [c for c in control.get("commands") or [] if c["id"] > applied]
    next_id = max([applied] + [c["id"] for c in commands]) + 1
    commands.append({"id": next_id, "op": op, "gid": gid})
    control["commands"] = commands
    return next_id


def pending_commands(control, applied):
    return sorted((c for c in control.get("commands") or [] if c["id"] > applied),
                  key=lambda c: c["id"])


def daemon_health(info, alive, now):
    """What a daemon record says: "running", "busy" (looping, but in the middle of
    something slow it names), "stale" (alive, not looping), "crashed" (recorded,
    process gone) or "stopped" (no record)."""
    if not info:
        return "stopped"
    if not alive:
        return "crashed"
    if now - (info.get("loop_at") or info.get("beat") or 0) > STALE_AFTER:
        return "stale"
    if info.get("busy"):
        return "busy"
    return "running"


def unmanaged(live_runs, managed_pids):
    """start-task runs with a live pid that no daemon here launched or adopted:
    [(task_id, pid)]. A hand run, a run-milestone loop, or a dead daemon's orphan —
    all of them shown, so none is a ghost."""
    managed = set(managed_pids)
    return sorted((tid, pid) for tid, pid in live_runs if pid not in managed)


def orphan_agents(rows, worktrees_dir, owners):
    """Processes working in this repo's worktrees that no live run owns:
    [(worktree, pid)]. An agent whose run was killed keeps editing unseen; this is
    how it is found. Only the topmost such process of a tree is listed — stopping
    it is what matters. `rows` is [(pid, ppid, command)]."""
    parent = {pid: ppid for pid, ppid, _ in rows}
    marker = worktrees_dir.rstrip("/") + "/"
    working = {pid: cmd for pid, _, cmd in rows if marker in cmd}
    owners = set(owners)
    out = []
    for pid, cmd in working.items():
        seen, up, owned = set(), parent.get(pid), False
        while up and up not in seen:
            if up in owners or up in working:
                owned = True
                break
            seen.add(up)
            up = parent.get(up)
        if not owned:
            tree = cmd.split(marker, 1)[1].split("/")[0].split()[0]
            out.append((tree, pid))
    return sorted(out)


# --- files ------------------------------------------------------------------

def queue_dir(main_root):
    return os.path.join(main_root, st.CORTEX_DIRNAME, QUEUE_DIRNAME)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


@contextlib.contextmanager
def control_file(main_root):
    """The control file, read and written back under a lock — the TUI and the
    daemon both touch it."""
    qdir = queue_dir(main_root)
    st.ensure_cortex_dir(main_root)
    os.makedirs(qdir, exist_ok=True)
    with open(os.path.join(qdir, "control.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        control = read_json(os.path.join(qdir, "control.json")) or empty_control()
        yield control
        write_json(os.path.join(qdir, "control.json"), control)


def read_control(main_root):
    return read_json(os.path.join(queue_dir(main_root), "control.json")) or empty_control()


def registry_path(main_root):
    return os.path.join(REGISTRY, hashlib.sha1(main_root.encode()).hexdigest()[:16] + ".json")


def registered():
    """Every daemon on this machine: [(path, info, alive)]."""
    out = []
    try:
        names = sorted(os.listdir(REGISTRY))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(REGISTRY, name)
        info = read_json(path)
        if isinstance(info, dict):
            out.append((path, info, bool(st.live_run_pid(info))))
    return out


def daemon_info(main_root):
    """(daemon.json, its pid is alive)."""
    info = read_json(os.path.join(queue_dir(main_root), "daemon.json"))
    return info, bool(info and st.live_run_pid(info))


def live_runs(main_root):
    """Every start-task run in the repo whose pid is alive: [(task_id, pid)]."""
    root = os.path.join(main_root, st.CORTEX_DIRNAME, st.STATE_DIRNAME)
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for tid in names:
        pid = st.live_run_pid(read_json(os.path.join(root, tid, "run.json")))
        if pid:
            out.append((tid, pid))
    return out


def start_daemon(main_root, forward):
    """Start the repo's daemon in its own session, so closing the terminal does
    not take it down. Returns its pid."""
    qdir = queue_dir(main_root)
    os.makedirs(qdir, exist_ok=True)
    logfile = open(os.path.join(qdir, "daemon.log"), "a")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "tui.py"), "--serve", "--repo", main_root]
        + list(forward), cwd=main_root, stdin=subprocess.DEVNULL, stdout=logfile,
        stderr=subprocess.STDOUT, start_new_session=True)
    logfile.close()
    return proc.pid


def stop_daemon(info):
    try:
        os.kill(info["pid"], signal.SIGTERM)
        return True
    except (OSError, KeyError, TypeError):
        return False


def ps_rows():
    """[(pid, ppid, command)] for every process on the machine."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    except OSError:
        return []
    rows = []
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def live_agents(main_root, owners):
    worktrees = os.path.join(main_root, st.CORTEX_DIRNAME, st.WORKTREES_DIRNAME)
    return orphan_agents(ps_rows(), worktrees, owners)


def kill_pid(pid):
    """Stop a stray process and what it started. One left in the group of a run
    that is gone takes the rest of that group with it."""
    try:
        group = os.getpgid(pid)
    except OSError:
        return False
    if group != pid and not st.live_run_pid({"pid": group}):
        try:
            os.killpg(group, signal.SIGTERM)
            return True
        except OSError:
            pass
    return kill_tree(pid)


# --- the daemon -------------------------------------------------------------

class QueueRun(Engine):
    """The engine over whatever is queued, into whichever sprint was picked."""

    def __init__(self, repo, forward):
        Engine.__init__(self, queue_dir, repo, forward)
        self.control = empty_control()

    def scope(self):
        return [{"gid": q["gid"], "board": q.get("board")} for q in self.control["queue"]]

    def apply_control(self):
        control = read_control(self.main_root)
        before = {q["gid"] for q in self.control["queue"]}
        self.control = control
        self.data["sprint"] = control.get("sprint")
        self.data["base"] = control.get("base")
        self.data["merge_mode"] = control.get("merge_mode") or "off"
        new = [q["gid"] for q in control["queue"] if q["gid"] not in before]
        gone = before - {q["gid"] for q in control["queue"]}
        if new or gone:
            self.refresh(only=set(new))
            if new:
                self.reconcile_all()
        applied = self.data.get("applied", 0)
        results = self.data.setdefault("results", [])
        for command in pending_commands(control, applied):
            gid = command["gid"]
            if command["op"] not in COMMANDS:
                log("ignored a command this daemon does not know: %s" % command["op"])
                results.append({"id": command["id"], "ok": False,
                                "note": "this daemon does not know %r" % command["op"]})
            elif command["op"] == "merge" and self.data["merge_mode"] == "never":
                results.append({"id": command["id"], "ok": False,
                                "note": "merging is set to never (Setup tab)"})
            else:
                results.append({"id": command["id"], "ok": True})
            if command["op"] == "stop":
                self.stop(gid, "stopped from the TUI")
            elif command["op"] == "merge":
                self.request_merge(gid)
            elif command["op"] == "merge-cancel":
                self.cancel_merge(gid)
            elif command["op"] == "retry":
                record = self.records.get(gid) or {}
                if record.get("phase") in ("failed", "stopped"):
                    self.set_phase(gid, None, reason=None)
            applied = command["id"]
        self.data["applied"] = applied
        self.data["results"] = results[-20:]

    def heartbeat(self, started, version):
        write_json(os.path.join(self.dir, "daemon.json"), {
            "pid": os.getpid(), "main_root": self.main_root, "started": started,
            "beat": time.time(), "loop_at": self.loop_at, "forward": self.forward,
            "code": version, "busy": sorted(set(self.busy.values())),
        })

    def beat_forever(self, started, version):
        """Publish the heartbeat — and what is taking long — every second, from
        its own thread, so a slow step in the loop is shown, not mistaken for a
        hang."""
        while True:
            try:
                self.heartbeat(started, version)
            except OSError:
                pass
            time.sleep(1)

    def idle(self):
        """No run in flight — launched or adopted — so restarting loses nothing."""
        return not self.children and not any(
            st.live_run_pid({"pid": r.get("pid")}) for r in self.records.values() if r.get("pid"))

    def reload(self):
        """Become a fresh daemon on the current code: the same pid, the same files,
        nothing interrupted. Only called when idle."""
        log("code changed — restarting onto it")
        self.save()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def serve(self):
        info, alive = daemon_info(self.main_root)
        if alive and info.get("pid") != os.getpid():
            raise Stop("a daemon is already running for %s (pid %s)"
                       % (self.main_root, info["pid"]))
        started = time.time()
        version = code_version()
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        self.loop_at = time.time()
        self.heartbeat(started, version)
        write_json(registry_path(self.main_root),
                   {"pid": os.getpid(), "main_root": self.main_root, "started": started})
        log("daemon up for %s (pid %d)" % (self.main_root, os.getpid()))
        try:
            threading.Thread(target=self.beat_forever, args=(started, version),
                             daemon=True).start()
            self.resolve_me()
            self.apply_control()
            self.refresh()
            self.reconcile_all()
            while True:
                self.loop_at = time.time()
                if code_version() != version and self.idle() and not self.busy:
                    self.reload()
                self.apply_control()
                self.save()
                if self.control["queue"] or self.children:
                    self.tick()
                time.sleep(SERVE_TICK)
        finally:
            self.kill_all()
            self.save()
            for path in (registry_path(self.main_root),
                         os.path.join(self.dir, "daemon.json")):
                try:
                    os.remove(path)
                except OSError:
                    pass
            log("daemon down")
