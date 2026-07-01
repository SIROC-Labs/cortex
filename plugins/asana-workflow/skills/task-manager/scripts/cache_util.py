#!/usr/bin/env python3
#
# cache_util.py — neutral, provider-agnostic board-cache lifecycle helpers.
#
# This is the shared "lifecycle" layer of the multi-provider board-cache system.
# It owns ONLY provider-neutral concerns: deriving a stable project key, locating
# and reading/writing the cache file, timestamping, and date-staleness math.
# It knows nothing about Asana, Jira, any HTTP API, or the shape of the cached
# payload beyond two conventions:
#
#   1. cached_at — write_cache stamps an ISO-8601 UTC timestamp if the caller
#      did not set one.
#   2. provider — a cache MAY carry a top-level "provider" string identifying
#      which provider produced it (e.g. "asana", "jira"). Providers stamp this
#      when they write the cache and check it when they read, so one provider
#      never misreads another provider's payload.
#
#      provider_matches(obj, provider) semantics:
#        - marker present and EQUAL to provider   -> True  (mine)
#        - marker present and DIFFERENT            -> False (someone else's)
#        - marker MISSING / not a string           -> True  (legacy cache; treat
#          as a match so it self-heals — the provider rewrites it with the marker
#          on the next discover/refresh)
#
# Importing this module has no side effects: it defines helpers only, runs no
# code at import time, and has no __main__.
#
# Dependencies: Python 3 stdlib + git (for project_key). No network.

import datetime
import json
import os
import re
import subprocess


CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cortex", "asana-workflow")


def _git_output(args):
    try:
        proc = subprocess.run(["git"] + args, capture_output=True)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def project_key():
    """Derive a stable cache key for the current repo.

    git remote origin URL -> non-alnum replaced with '-', repeats collapsed,
    lowercased. Falls back to the repo top-level basename, else the cwd basename.
    """
    remote = _git_output(["remote", "get-url", "origin"])
    if remote:
        s = re.sub(r"[^a-zA-Z0-9]", "-", remote)
        s = re.sub(r"-{2,}", "-", s)
        return s.lower()
    toplevel = _git_output(["rev-parse", "--show-toplevel"])
    base = toplevel if toplevel else os.getcwd()
    return os.path.basename(base)


def cache_path(key):
    """Absolute path of the cache file for a given key."""
    return os.path.join(CACHE_DIR, key + ".json")


def read_cache(key):
    """Parse and return the cache dict for key, or None if missing/unreadable."""
    file = cache_path(key)
    try:
        with open(file, "r") as f:
            return json.load(f)
    except Exception:
        return None


def write_cache(key, obj):
    """Write obj as pretty JSON to the cache file for key.

    Creates CACHE_DIR if needed. Stamps cached_at (ISO-8601 UTC) when the caller
    did not already set it.
    """
    if isinstance(obj, dict) and not obj.get("cached_at"):
        obj["cached_at"] = now_iso()
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)
    file = cache_path(key)
    text = json.dumps(obj, indent=2)
    with open(file, "w") as f:
        f.write(text + "\n")


def now_iso():
    """Current UTC time as ISO-8601, e.g. 2026-06-22T13:45:01Z."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_utc():
    """Current UTC date as YYYY-MM-DD."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def is_date_stale(date_str):
    """True iff date_str (a YYYY-MM-DD) is non-empty AND lexically < today_utc().

    Empty / None -> False (nothing to be stale about).
    """
    if not date_str:
        return False
    return date_str < today_utc()


def cache_provider(obj):
    """Return the cache's top-level provider marker, or None if absent/non-string."""
    if not isinstance(obj, dict):
        return None
    v = obj.get("provider")
    if isinstance(v, str) and v:
        return v
    return None


def provider_matches(obj, provider):
    """True if obj belongs to provider.

    A missing marker is treated as a match (legacy cache, self-heals); a present
    marker that differs is NOT a match.
    """
    marker = cache_provider(obj)
    if marker is None:
        return True
    return marker == provider
