#!/usr/bin/env python3
#
# notes.py — what the person tells a goal while it runs. The service adds a note;
# the lead's hook hands it to the lead inside its session, or the runner hands it
# over with the lead's next prompt. One file in the goal's state, under a lock, as
# the service, the hook and the runner each write it.

import contextlib
import fcntl
import json
import os
import time

FILE = "notes.json"
WAITING, DELIVERED, TAKEN = "waiting", "delivered", "taken"

NOTE = """The person sent you a note while the goal runs:

%s

It counts like their answer to a question: it overrules the references. Act on it
now. Write it into the journal's decisions where it changes what is built or how.
If it only steers the work, adjust and carry on. If it adds a small piece of work,
add its acceptance criteria under `### Added: <a name>` and build it with the rest.
If it adds work that needs its own analysis, such as a new screen, path or rule set,
and you are in the build: report `{"status": "replan", "summary": "..."}`. The runner
then sends you back to planning, with a review and the person's approval."""


@contextlib.contextmanager
def _locked(state_dir):
    with open(os.path.join(state_dir, FILE + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(state_dir):
    try:
        with open(os.path.join(state_dir, FILE)) as f:
            return json.load(f).get("notes") or []
    except (IOError, OSError, ValueError, AttributeError):
        return []


def _write(state_dir, notes):
    path = os.path.join(state_dir, FILE)
    with open(path + ".tmp", "w") as f:
        json.dump({"notes": notes}, f, indent=1)
    os.replace(path + ".tmp", path)


def add(state_dir, text, stop=False, now=None):
    """Add a note. Returns it."""
    with _locked(state_dir):
        notes = read(state_dir)
        note = {"n": len(notes) + 1, "text": text.strip(), "stop": bool(stop),
                "at": now or time.time(), "state": WAITING}
        _write(state_dir, notes + [note])
    return note


def waiting(state_dir):
    return [n for n in read(state_dir) if n.get("state") == WAITING]


def take(state_dir, state=TAKEN):
    """The notes not handed over yet, marked handed over. Returns the text for the
    lead, or "" when there are none."""
    with _locked(state_dir):
        notes = read(state_dir)
        new = [n for n in notes if n.get("state") == WAITING]
        if not new:
            return ""
        for n in new:
            n.update(state=state, handed=time.time())
        _write(state_dir, notes)
    return NOTE % "\n\n".join("> " + n["text"].replace("\n", "\n> ") for n in new)


def stop_asked(state_dir):
    """Whether a waiting note asks to stop the tasks that run now. The ask is kept
    once read: the note says so when it is handed over."""
    with _locked(state_dir):
        notes = read(state_dir)
        asked = [n for n in notes if n.get("state") == WAITING and n.get("stop") and not n.get("stopped")]
        for n in asked:
            n["stopped"] = time.time()
        if asked:
            _write(state_dir, notes)
    return bool(asked)
