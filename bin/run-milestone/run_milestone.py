#!/usr/bin/env python3
#
# run-milestone — works a board's milestones through start-task, in parallel, to merge.
#
# A deterministic loop over plain code — no model is called here. It finds the
# ready tasks in the milestones it was given (not done, every dependency done),
# puts each in the sprint it was given, assigns it, and runs `start-task` on it. A
# shipped PR is watched until it merges: review feedback in the meantime is handed
# back to the task's session through `start-task --phase revise`, and a merge
# completes the task in Asana, which is what readies its dependents. A PR that
# conflicts with its base parks its task until someone asks for a resolve; a PR
# closed without merging stops it.
#
# Every run that is going, waiting on a human, or watching a PR is recorded under
# `<repo>/.cortex/milestones/<board>/`, and a restart reconciles that record
# against Asana, GitHub and start-task's own state rather than trusting it.
#
#   cortex run-milestone <board-url> "M1" --sprint <sprint-url>   # until M1 is done
#   cortex run-milestone <board-url> M1 M2 --sprint <sprint-url>  # several at once
#   cortex run-milestone <board-url> --status                     # where every task stands
#   cortex run-milestone <board-url> M1 --sprint <url> --backend echo  # rest → start-task
#
# Dependencies: Python 3 stdlib, git, gh, and start-task (sibling directory).

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import TICK, Engine, Stop, log, parse_project_ref, st  # noqa: E402

MILESTONES_DIRNAME = "milestones"


def match_milestones(wanted, listing):
    """The milestones named in `wanted`, out of a board's `milestone list`.

    Each entry may be the milestone's full name, the short name before ` :: `
    ("M1"), or its task's gid or URL. Returns [{name, ref}] in the order asked;
    raises ValueError naming anything that matched nothing, or more than one.
    """
    out = []
    for item in wanted:
        gid = task_ref(item)
        key = item.strip().lower()
        hits = [m for m in listing
                if m.get("ref") == gid
                or (m.get("name") or "").strip().lower() == key
                or (m.get("name") or "").split(" :: ")[0].strip().lower() == key]
        if len(hits) != 1:
            names = ", ".join(m.get("name") or "?" for m in listing) or "none"
            raise ValueError("%r matches %s milestone(s) on this board (it has: %s)"
                             % (item, len(hits) or "no", names))
        if hits[0] not in out:
            out.append(hits[0])
    return out


def task_ref(item):
    """A task gid from a URL or a bare gid, by the provider's own rules."""
    from asana import asana_extract_ref
    return asana_extract_ref(item)


class BoardRun(Engine):
    """The engine over one board's named milestones, into a named sprint."""

    def __init__(self, board, milestones, sprint, repo, forward):
        self.project = parse_project_ref(board)
        if not self.project:
            raise Stop("not an Asana board URL or gid: %s" % board)
        self.wanted = milestones
        self.sprint_ref = sprint
        Engine.__init__(self, lambda root: os.path.join(
            root, st.CORTEX_DIRNAME, MILESTONES_DIRNAME, self.project), repo, forward)

    def resolve(self):
        """Who the tasks are assigned to, which sprint they go into and which
        milestones are in scope — all from what was given, nothing guessed."""
        me = self.resolve_me()
        _, board = self.asana(["project", "get", self.project])
        self.data["board"] = board.get("name")
        sprint = self.resolve_sprint(self.sprint_ref)
        _, listing = self.asana(["milestone", "list", self.project])
        try:
            self.data["milestones"] = match_milestones(self.wanted, listing or [])
        except ValueError as e:
            raise Stop(str(e))
        log("board %s · %s · sprint %s · assigning to %s"
            % (board.get("name"), ", ".join(m["name"] for m in self.data["milestones"]),
               sprint.get("name"), me.get("name")))

    def scope(self):
        members = []
        for milestone in self.data["milestones"]:
            _, rows = self.asana(["milestone", "tasks", self.project, milestone["ref"]])
            for row in rows or []:
                if all(m["gid"] != row["gid"] for m in members):
                    members.append({"gid": row["gid"], "board": self.project})
        return members

    def run_loop(self):
        self.resolve()
        self.refresh()
        self.reconcile_all()
        self.save()
        try:
            while True:
                self.tick()
                if self.done():
                    break
                time.sleep(TICK)
        finally:
            self.save()
        self.report(self.data.get("board") or self.project)
        return 0 if all(t["completed"] for t in self.tasks.values()) else 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cortex run-milestone",
        description="Work every task in the given milestones of an Asana board through "
                    "start-task, in parallel, until each is merged. Arguments not "
                    "listed here are passed to every start-task run (e.g. --backend "
                    "echo).")
    parser.add_argument("board", help="URL (or gid) of the board the milestones are on")
    parser.add_argument("milestones", nargs="*",
                        help="milestones to work: full name, the short name before "
                             "' :: ' (e.g. M1), or the milestone task's URL or gid")
    parser.add_argument("--sprint", default=None,
                        help="URL (or gid) of the sprint board tasks are added to")
    parser.add_argument("--repo", default=os.getcwd(),
                        help="target repository (default: cwd)")
    parser.add_argument("--status", action="store_true",
                        help="report where every task stands, from the last run's "
                             "record; no network, no work")
    return parser


def main(argv):
    parser = build_parser()
    args, forward = parser.parse_known_args(argv)
    if "--no-wait" in forward:
        sys.stderr.write("run-milestone: --no-wait does not apply — every run waits on "
                         "its own questions\n")
        return 2
    if not args.status and (not args.milestones or not args.sprint):
        parser.error("name at least one milestone, and the sprint with --sprint")
    try:
        board = BoardRun(args.board, args.milestones, args.sprint, args.repo, forward)
        if args.status:
            if not board.tasks:
                raise Stop("no record of this board in %s — run it first" % board.dir)
            board.report(board.data.get("board") or board.project)
            return 0
        return board.run_loop()
    except Stop as e:
        sys.stderr.write("\nrun-milestone: %s\n" % e)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.stderr.write("\n\nrun-milestone: interrupted — progress is recorded; run the "
                         "same command to carry on.\n")
        sys.exit(130)
