#!/usr/bin/env python3
#
# repos.py — the repositories conductor runs goals in, for the service to list.
# A repo is added when a goal starts in it, or by hand.

import os

import control as dm


def home():
    return os.environ.get("COND_HOME") or os.path.join(os.path.expanduser("~"), ".cortex", "cli")


def repos_file():
    return os.path.join(home(), "repos.json")


def paths():
    """The registered repos' roots that still exist, in the order they came."""
    return [p for p in (dm.read_json(repos_file(), {}) or {}).get("repos") or [] if os.path.isdir(p)]


def add(root):
    """Register a repo's root. Never fails a goal: an unwritable file is skipped."""
    try:
        data = dm.read_json(repos_file(), {}) or {}
        known = data.get("repos") or []
        if root not in known:
            data["repos"] = known + [root]
            dm.write_json(repos_file(), data)
    except (IOError, OSError):
        pass
