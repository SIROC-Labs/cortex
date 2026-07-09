#!/usr/bin/env python3
#
# resolve_provider.py — neutral seam helper: detect which task-manager provider a
# repo uses. Detection-only: there is no committed selector file. Resolution relies
# purely on the machine-local per-repo cache provider-marker, task-URL detection, and
# asking the operator. The seam (../SKILL.md "Resolution") runs this and branches on
# its exit code.
#
# Usage:
#   resolve_provider.py [--url <task-url-or-ref>]
#   resolve_provider.py --set <provider>
#
# Precedence (detection-only):
#   1. Cache provider-marker present (cache_util.read_cache(project_key()) ->
#      cache_provider)?
#        - If --url is ALSO given and a DIFFERENT installed provider's `ref parse`
#          recognizes it -> exit 3 (conflict; surface cached vs detected, do NOT
#          auto-flip — the seam asks the operator and persists via --set).
#        - Else -> that cached provider, exit 0 (source=cache).
#   2. Else if --url given -> discover installed providers by globbing sibling
#      ../task-manager-*/scripts/tm.py (relative to THIS file), run each
#      `tm.py ref parse <url>`; the first that exits 0 wins -> PERSIST the marker into
#      the cache (merge with any existing cache) -> exit 0 (source=detected).
#   3. Else -> exit 4 (ask the user; no cache, no url).
#
# --set <provider> mode: write/merge the provider marker into the cache and exit 0.
#   The seam calls this to persist the operator's answer after an ask (exit 4) or a
#   conflict (exit 3) resolution.
#
# Exit codes: 0 resolved / 3 conflict / 4 ask-needed / 1 error.
# Provider name -> stdout; source + notes -> stderr.
#
# The per-repo cache key is cache_util.project_key() (git remote of CWD), so this is
# run from within the repo (cd into it), exactly as the seam invokes it.
#
# Dependencies: Python 3 stdlib + the installed providers' tm.py (invoked, not
# imported) + cache_util (imported as a sibling). No network.

import glob
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import cache_util  # noqa: E402

PROG = "resolve_provider.py"


def err(msg):
    sys.stderr.write(msg + "\n")


def die(code, msg=None):
    if msg is not None:
        err(msg)
    sys.exit(code)


# Discover installed providers: glob sibling ../task-manager-*/scripts/tm.py relative
# to THIS file. Returns a sorted list of (provider_name, tm_py_path).
def installed_providers():
    skills_dir = os.path.dirname(os.path.dirname(_HERE))  # .../skills
    out = []
    pattern = os.path.join(skills_dir, "task-manager-*", "scripts", "tm.py")
    for tm_path in glob.glob(pattern):
        skill_dir = os.path.basename(os.path.dirname(os.path.dirname(tm_path)))
        prefix = "task-manager-"
        if skill_dir.startswith(prefix):
            name = skill_dir[len(prefix):]
            if name:
                out.append((name, tm_path))
    out.sort(key=lambda x: x[0])
    return out


# Run `<tm.py> ref parse <url>` for a provider. Returns True iff it exits 0 (the
# provider recognizes the input as its own task reference).
def provider_recognizes(tm_path, url):
    try:
        proc = subprocess.run(
            [sys.executable, tm_path, "ref", "parse", url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except Exception:
        return False
    return proc.returncode == 0


# First installed provider whose `ref parse` recognizes the url, or None.
def detect_from_url(url):
    for name, tm_path in installed_providers():
        if provider_recognizes(tm_path, url):
            return name
    return None


# Write/merge the provider marker into the per-repo cache: read the existing cache (or
# {}), set provider, write back via cache_util.
def persist_provider(provider):
    key = cache_util.project_key()
    cache = cache_util.read_cache(key)
    if not isinstance(cache, dict):
        cache = {}
    cache["provider"] = provider
    cache_util.write_cache(key, cache)


def parse_args(argv):
    url = None
    set_provider = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--url":
            if i + 1 >= len(argv):
                die(1, "%s: --url requires a value" % PROG)
            url = argv[i + 1]
            i += 2
        elif a == "--set":
            if i + 1 >= len(argv):
                die(1, "%s: --set requires a value" % PROG)
            set_provider = argv[i + 1]
            i += 2
        else:
            die(1, "%s: unknown argument '%s'" % (PROG, a))
    return url, set_provider


def main(argv):
    url, set_provider = parse_args(argv)

    # --set mode: persist the marker and exit.
    if set_provider is not None:
        if not set_provider:
            die(1, "%s: --set requires a non-empty provider name" % PROG)
        persist_provider(set_provider)
        err("source=set")
        sys.stdout.write(set_provider + "\n")
        sys.exit(0)

    # 1. Cache provider-marker is authoritative.
    cache = cache_util.read_cache(cache_util.project_key())
    cached = cache_util.cache_provider(cache)
    if cached is not None:
        if url is not None:
            detected = detect_from_url(url)
            if detected is not None and detected != cached:
                err("%s: conflict — cached provider is '%s' but the URL is recognized by '%s'" % (
                    PROG, cached, detected))
                err("source=cache=%s detected(url)=%s" % (cached, detected))
                err("resolve with: %s --set <provider>" % PROG)
                sys.stdout.write(cached + "\n")
                sys.exit(3)
        err("source=cache")
        sys.stdout.write(cached + "\n")
        sys.exit(0)

    # 2. Detect from URL via installed providers' `ref parse`, then persist.
    if url is not None:
        detected = detect_from_url(url)
        if detected is not None:
            persist_provider(detected)
            err("source=detected")
            err("note: persisted provider marker to the per-repo cache")
            sys.stdout.write(detected + "\n")
            sys.exit(0)

    # 3. Nothing to go on — ask the user.
    err("%s: no cached provider marker and no --url — ask the user which task manager this project uses, then persist with --set <provider>" % PROG)
    sys.exit(4)


if __name__ == "__main__":
    main(sys.argv[1:])
