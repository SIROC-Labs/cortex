#!/usr/bin/env python3
#
# migrate.py — move the state cortex left behind to where conductor looks for it.
#
#   cond migrate                       # what would move, changes nothing
#   cond migrate --apply               # move it
#   cond migrate --repo PATH --apply   # a repo the old daemons never registered
#
# What moves:
#   ~/.cortex/cli/          → ~/.conductor/          (daemons, Asana cache, model rates)
#   ~/.cache/cortex/        → ~/.cache/conductor/    (the TUI's board cache)
#   <repo>/.cortex/         → <repo>/.conductor/     (queue, state, worktrees, milestones)
#
# In each repo, the absolute paths written into state and queue files are rewritten,
# git is told where its worktrees went, and the Claude Code session folders of those
# worktrees are renamed, so a run in flight resumes its sessions. The skills' own
# ~/.cortex/cortex-workflow/ is left alone.
#
# Stop every cortex daemon and run first: a run that still writes into .cortex/
# while it moves loses that work. The migration refuses while one is alive.

import argparse
import json
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
OLD_HOME = os.path.join(HOME, ".cortex", "cli")
NEW_HOME = os.path.join(HOME, ".conductor")
OLD_DIRNAME, NEW_DIRNAME = ".cortex", ".conductor"


# --- pure helpers (unit-tested) ----------------------------------------------

def claude_folder(path):
    """The name Claude Code gives the project folder of a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def rewrite(text, root):
    """`text` with every path under `<root>/.cortex` pointing under `<root>/.conductor`,
    in plain and in Claude-folder form."""
    pairs = [(os.path.join(root, OLD_DIRNAME), os.path.join(root, NEW_DIRNAME), r"(?![\w.-])"),
             (claude_folder(os.path.join(root, OLD_DIRNAME)),
              claude_folder(os.path.join(root, NEW_DIRNAME)), r"(?![A-Za-z0-9])")]
    for old, new, end in pairs:
        text = re.sub(re.escape(old) + end, new.replace("\\", "\\\\"), text)
    return text


def renamed_folder(name, root):
    """The new name of a Claude project folder under `<root>/.cortex`, or None."""
    old = claude_folder(os.path.join(root, OLD_DIRNAME))
    if name == old or name.startswith(old + "-"):
        return claude_folder(os.path.join(root, NEW_DIRNAME)) + name[len(old):]
    return None


def live_pids(records, is_alive):
    """The pids among daemon registry records whose process is still running."""
    out = []
    for record in records:
        pid = record.get("pid") if isinstance(record, dict) else None
        if isinstance(pid, int) and not isinstance(pid, bool) and is_alive(pid):
            out.append(pid)
    return out


def processes_in(ps_lines, roots):
    """The `ps` lines whose command names a path under one of the old state folders."""
    marks = [os.path.join(r, OLD_DIRNAME) + os.sep for r in roots]
    return [line for line in ps_lines if any(m in line for m in marks)]


# --- effects -----------------------------------------------------------------

def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def registry_records():
    folder = os.path.join(OLD_HOME, "daemons")
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        try:
            with open(os.path.join(folder, name)) as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            pass
    return out


def main_root(path):
    """The main worktree of the git repo at `path`."""
    try:
        common = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return os.path.dirname(common.stdout.strip().rstrip(os.sep))


def text_files(folder, skip):
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if os.path.join(dirpath, d) != skip]
        for name in filenames:
            yield os.path.join(dirpath, name)


def plan_repo(root, claude_projects):
    """What moving one repo's state takes: [(description, action)]."""
    old, new = os.path.join(root, OLD_DIRNAME), os.path.join(root, NEW_DIRNAME)
    if not os.path.isdir(old):
        return []
    if os.path.exists(new):
        return [("skip %s: %s already exists" % (root, new), None)]
    steps = []
    worktrees = os.path.join(old, "worktrees")
    for path in text_files(old, worktrees):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        changed = rewrite(text, root)
        if changed != text:
            def write(path=path, changed=changed):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(changed)
            steps.append(("rewrite paths in %s" % os.path.relpath(path, root), write))
    steps.append(("move %s → %s" % (old, new), lambda: os.rename(old, new)))
    names = sorted(os.listdir(worktrees)) if os.path.isdir(worktrees) else []
    moved = [os.path.join(new, "worktrees", n) for n in names
             if os.path.exists(os.path.join(worktrees, n, ".git"))]
    if moved:
        steps.append(("git worktree repair (%d worktrees)" % len(moved), lambda: subprocess.run(
            ["git", "-C", root, "worktree", "repair"] + moved, check=True)))
    try:
        folders = sorted(os.listdir(claude_projects))
    except OSError:
        folders = []
    for name in folders:
        target = renamed_folder(name, root)
        if not target:
            continue
        src, dst = os.path.join(claude_projects, name), os.path.join(claude_projects, target)
        if os.path.exists(dst):
            steps.append(("skip Claude folder %s: %s exists" % (name, target), None))
        else:
            steps.append(("rename Claude folder %s → %s" % (name, target),
                          lambda src=src, dst=dst: os.rename(src, dst)))
    return steps


def plan_move(src, dst):
    if not os.path.isdir(src):
        return []
    if os.path.exists(dst):
        return [("skip %s: %s already exists" % (src, dst), None)]
    def move():
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
    return [("move %s → %s" % (src, dst), move)]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cond migrate", description=(
        "Move cortex's state to conductor's folders. Without --apply, only prints the plan."))
    parser.add_argument("--apply", action="store_true", help="make the changes")
    parser.add_argument("--repo", action="append", default=[],
                        help="a repo to migrate besides those the old daemons registered")
    args = parser.parse_args(argv)

    records = registry_records()
    alive = live_pids(records, pid_alive)
    roots = []
    for path in [r.get("main_root") for r in records if isinstance(r, dict)] + args.repo + [os.getcwd()]:
        root = main_root(path) if path and os.path.isdir(path) else None
        if root and root not in roots:
            roots.append(root)

    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    busy = processes_in(ps.splitlines(), roots)
    if alive or busy:
        print("Stop these first — they still use the old state:")
        for pid in alive:
            print("  daemon pid %d" % pid)
        for line in busy:
            print("  " + line.strip()[:160])
        if args.apply:
            return 1

    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
    claude_projects = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude"),
                                   "projects")
    steps = plan_move(OLD_HOME, NEW_HOME) + plan_move(os.path.join(cache, "cortex"),
                                                      os.path.join(cache, "conductor"))
    for root in roots:
        steps += plan_repo(root, claude_projects)

    if not steps:
        print("Nothing to migrate.")
        return 0
    for description, action in steps:
        if not args.apply or action is None:
            print(("  " if action else "  ! ") + description)
            continue
        action()
        print("  ✔ " + description)
    if not args.apply:
        print("\nRun `cond migrate --apply` to make these changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
