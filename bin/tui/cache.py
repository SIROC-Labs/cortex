#!/usr/bin/env python3
#
# cache.py — what the TUI last read from Asana, and the background loads that
# keep it current.
#
# Stale-while-revalidate: a view shows its cached copy at once, says how old it
# is, and re-reads Asana in a thread behind it when the copy is older than that
# view tolerates. Nothing waits on the network to draw.
#
# Lives in $XDG_CACHE_HOME/cortex (~/.cache/cortex by default): it is only ever
# a copy, safe to delete.

import json
import os
import re
import threading
import time

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "cortex", "asana")


# --- pure helpers (unit-tested) ---------------------------------------------

def age_label(at, now):
    """How old a copy is, the way a person says it."""
    if at is None:
        return "not loaded yet"
    seconds = max(0, now - at)
    if seconds < 10:
        return "updated just now"
    if seconds < 60:
        return "updated %ds ago" % seconds
    if seconds < 3600:
        return "updated %dm ago" % (seconds // 60)
    if seconds < 86400:
        return "updated %dh ago" % (seconds // 3600)
    return "updated %dd ago" % (seconds // 86400)


def is_stale(at, now, max_age):
    return at is None or now - at > max_age


def spinner(now):
    return SPINNER[int(now * 10) % len(SPINNER)]


# --- the cache --------------------------------------------------------------

class Cache(object):
    def __init__(self, root=None):
        self.root = root or cache_dir()

    def path(self, name):
        return os.path.join(self.root, re.sub(r"[^A-Za-z0-9._-]", "_", name) + ".json")

    def get(self, name):
        """(data, saved at), or (None, None) when there is no copy."""
        try:
            with open(self.path(name)) as f:
                entry = json.load(f)
            return entry.get("data"), entry.get("at")
        except (IOError, OSError, ValueError, AttributeError):
            return None, None

    def put(self, name, data, at=None):
        os.makedirs(self.root, exist_ok=True)
        path = self.path(name)
        tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
        with open(tmp, "w") as f:
            json.dump({"at": at or time.time(), "data": data}, f)
        os.replace(tmp, path)


# --- background loads -------------------------------------------------------

class Loader(object):
    """Runs loads in threads, one per key at a time, and hands back what they
    produced. The UI polls `take` each frame; nothing blocks it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = {}
        self.results = {}

    def start(self, key, label, fn):
        """Begin a load unless one for `key` is already going."""
        with self.lock:
            if key in self.running:
                return False
            self.running[key] = label

        def work():
            try:
                outcome = (fn(), None)
            except Exception as e:  # a failed load is reported, never fatal
                outcome = (None, str(e) or type(e).__name__)
            with self.lock:
                self.results[key] = outcome
                self.running.pop(key, None)

        threading.Thread(target=work, daemon=True).start()
        return True

    def take(self, key):
        """(data, error) of a finished load for `key`, once; None while none."""
        with self.lock:
            return self.results.pop(key, None)

    def busy(self, key=None):
        with self.lock:
            return key in self.running if key else list(self.running.values())
