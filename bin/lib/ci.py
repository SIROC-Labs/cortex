#!/usr/bin/env python3
#
# ci.py — reading a PR's checks, CI failures and review feedback.

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASANA = os.path.join(HERE, "asana.py")
sys.path.insert(0, HERE)
import core as st  # noqa: E402


_CHECK_FAILED = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED",
                 "STARTUP_FAILURE"}


class Stop(Exception):
    pass


def _is_bot(user):
    user = user or {}
    return user.get("type") == "Bot" or (user.get("login") or "").endswith("[bot]")


def collect_feedback(reviews, review_comments, issue_comments, handled):
    """New review feedback on a PR, as [(id, heading, body)].


    A submitted review's own text, every inline comment, and every top-level
    comment count — but never one the run posted (it carries the mark), one from
    a bot account, or one already handled.
    """
    handled = set(handled or ())
    out = []
    for r in reviews or []:
        fid = "review:%s" % r.get("id")
        body = (r.get("body") or "").strip()
        if (fid in handled or r.get("state") == "PENDING" or not body
                or st.is_marked(body) or _is_bot(r.get("user"))):
            continue
        out.append((fid, "Review by @%s (%s)" % ((r.get("user") or {}).get("login"),
                                                 r.get("state")), body))
    for c in review_comments or []:
        fid = "inline:%s" % c.get("id")
        body = (c.get("body") or "").strip()
        if fid in handled or not body or st.is_marked(body) or _is_bot(c.get("user")):
            continue
        where = "`%s`" % c.get("path")
        if c.get("line"):
            where += " line %s" % c["line"]
        out.append((fid, "%s — @%s" % (where, (c.get("user") or {}).get("login")), body))
    for c in issue_comments or []:
        fid = "comment:%s" % c.get("id")
        body = (c.get("body") or "").strip()
        if fid in handled or not body or st.is_marked(body) or _is_bot(c.get("user")):
            continue
        out.append((fid, "Comment by @%s" % (c.get("user") or {}).get("login"), body))
    return out


def render_feedback(items):
    lines = []
    for _, heading, body in items:
        lines += ["### %s" % heading, "", body, ""]
    return "\n".join(lines).strip() + "\n"


def latest_checks(rollup):
    """Each check once: its latest run. A re-run CI lists a check once per run —
    a cancelled run superseded by a newer one on the same commit is history,
    not the check's state."""
    latest = {}
    for i, check in enumerate(rollup or []):
        name = check.get("name") or check.get("context") or "?"
        when = (check.get("startedAt") or check.get("createdAt") or "", i)
        if name not in latest or when >= latest[name][0]:
            latest[name] = (when, check)
    return [check for _, check in latest.values()]


CI_NOT_STARTED = "CI to start (every check so far was skipped)"


def check_states(rollup):
    """(pending names, failing [(name, url)]) from a PR's statusCheckRollup, which
    mixes check runs (status + conclusion) and commit statuses (state). Only each
    check's latest run counts."""
    pending, failing = [], []
    for check in latest_checks(rollup):
        name = check.get("name") or check.get("context") or "?"
        url = check.get("detailsUrl") or check.get("targetUrl")
        if check.get("__typename") == "StatusContext" or "state" in check and "status" not in check:
            state = (check.get("state") or "").upper()
            if state in ("PENDING", "EXPECTED"):
                pending.append(name)
            elif state in ("FAILURE", "ERROR"):
                failing.append((name, url))
        elif (check.get("status") or "").upper() != "COMPLETED":
            pending.append(name)
        elif (check.get("conclusion") or "").upper() in _CHECK_FAILED:
            failing.append((name, url))
    if not pending and not failing and rollup and all(
            (c.get("conclusion") or "").upper() == "SKIPPED" for c in latest_checks(rollup)):
        # Every check skipped is a run that did not apply, such as one on a push to a
        # draft: the run that counts has not started yet.
        pending.append(CI_NOT_STARTED)
    return sorted(set(pending)), sorted(set(failing))


_LOG_STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# What a failed job's log says went wrong, strongest signals first: an error
# annotation, a line that starts with ERROR or FAIL, a named exception, a failed
# test mark, a non-zero exit. Weaker words count only when nothing strong does.
_STRONG = re.compile(r"##\[error\]|^\s*(?:ERROR|FAIL(?:ED)?|FAILURE)\b|\b\w*(?:Error|Exception):|"
                     r"^\s*(?:✗|✘|×)|AssertionError|Traceback|exit code [1-9]")


_WEAK = re.compile(r"\berror\b|\bfail(?:ed|ure|s)?\b|expected|received|timed? ?out", re.IGNORECASE)
_NOISE = re.compile(r"^(##\[(?:group|endgroup)\]|Post job cleanup|Cleaning up orphan|\s*[✓√]|"
                    r".*Expected Digest)", re.IGNORECASE)
JOB_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)/job/(\d+)")
_NOT_RUN = re.compile(r"not started because|spending limit|billing", re.I)


def actions_refused(failing, cwd):
    """GitHub's reason for not running the failed jobs at all, such as a spending
    limit or a failed payment; None when they ran. No fix helps then, only the
    person."""
    for _, url in failing[:3]:
        m = JOB_URL.search(url or "")
        if not m:
            continue
        code, out, _ = run(["gh", "api", "repos/%s/%s/check-runs/%s/annotations"
                            % (m.group(1), m.group(2), m.group(4)), "--jq", ".[].message"], cwd=cwd)
        for line in out.splitlines() if code == 0 else []:
            if _NOT_RUN.search(line):
                return line.strip()
    return None


def failed_runs(failing):
    """The ids of the workflow runs the failed checks belong to."""
    return sorted({m.group(3) for m in (JOB_URL.search(url or "") for _, url in failing) if m})


def failure_excerpt(log_text, max_lines=10):
    """The lines of a CI job's log that say what failed: errors, failed tests,
    assertions — the last `max_lines` of them, timestamps off. Falls back on the
    log's last lines when none stand out."""
    lines = []
    for raw in (log_text or "").splitlines():
        line = _ESCAPES.sub("", _LOG_STAMP.sub("", raw)).rstrip()
        if line.strip() and not _NOISE.match(line.strip()):
            lines.append(line.replace("##[error]", "error: "))
    strong = [l for l in lines if _STRONG.search(l)]
    weak = [l for l in lines if _WEAK.search(l)]
    picked = strong or weak or lines
    out = []
    for line in picked[-max_lines * 3:]:
        if line not in out:
            out.append(line[:200])
    return out[-max_lines:]


def task_url(board, gid):
    return "https://app.asana.com/0/%s/%s" % (board or 0, gid)


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (proc.returncode, proc.stdout.decode("utf-8", "replace").strip(),
            proc.stderr.decode("utf-8", "replace").strip())
