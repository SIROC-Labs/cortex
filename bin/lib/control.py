#!/usr/bin/env python3
#
# control.py — the repo's settings file, `.cortex/queue/control.json`, and stopping
# a goal's processes.

import contextlib
import fcntl
import json
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core as st  # noqa: E402


QUEUE_DIRNAME = "queue"


def empty_control():
    return {}


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
    """The control file, read and written back under a lock."""
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


def kill_tree(pid):
    """Stop a run and everything it started. A run launched here leads its own
    process group, so its agent and QA commands go with it; anything else gets
    the signal on its own. Returns whether there was something to stop."""
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False
