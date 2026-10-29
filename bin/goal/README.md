# goal

An Asana ticket, implemented by itself, on one branch, into one PR.

```bash
cortex goal new https://app.asana.com/0/0/1218985136116349 --base feature/m6 --start
cortex goal new 1218985136116349               # build on the default branch; start it later
cortex goal run goal-hrt1-519-recruiter-s-queue  # run or resume one in the foreground
```

The usual way in is the TUI: on a board, select a task or a milestone and pick *Run … as
a goal* in the palette (`:`). The goal then shows on the Runs tab, where you answer it,
stop it and carry it on.

## How it works

The ask is the ticket: its description, its open subtasks, its comments and its
attachments, read once when the goal starts (an HTML attachment as its text, with the file
kept for its prototype). A milestone works well: its subtasks become
parts of one piece of work. Nothing is written back to Asana.

A **lead agent** gets the ask and nothing more. It plans the work, keeps a journal, and
starts its own sub-agents, reviewers and checkers as it sees fit. It commits on the goal's
branch as it goes. Nobody breaks the work down for it.

**Which source wins.** The ask points to references: a prototype, one-pagers, design
records, attachments. The prototype always wins: it decides what is built and how each
screen looks and behaves. Where it does not answer a question, the one-pager does. Where
neither does, you decide. The lead, the reviewer and the checker all work to this rule.

This program is the harness around the lead:

- **Analysis first.** The first round changes no code. The lead reads every reference the
  ask names, checks what the ask takes for granted against the code (a branch it builds on,
  earlier work it needs), and writes into its journal: `## References`, fine-grained
  `## Acceptance criteria` (one line for each screen part, state, rule or field, each with
  its source), and a `## Plan`. Its questions come to you together. The runner sends the
  lead back until the journal has all three.
- **Criteria review.** The checker's model then compares the criteria with the references,
  before anything is built: criteria that are missing, wrong, or too broad, and questions
  only you can answer. The lead corrects the criteria, then builds.
- **Parts, for large work.** When the work spans several areas, or more than about 25
  criteria, the lead splits it instead of building it alone. It writes `parts.json` in the
  goal's state: up to 8 parts, each with a brief (what it builds and must not touch, the
  references that cover it, and the contracts other parts depend on), its criteria copied
  from the lead's list, and the parts it comes `after`. The runner checks the split (every
  criterion from the list, none in two parts, no circle), and the review checks its
  boundaries too. Each part then runs as a goal of its own, with its own lead, analysis,
  journal, sub-agents and checker, on a branch off the goal's (`<branch>--<part>`).
  Shared layers come first; parts with nothing between them run two at a time. A part's
  questions go to the goal's lead first, and only what it cannot settle comes to you. A
  part is never pushed: when its check passes, it merges the goal's branch in and is
  merged into it, one part at a time, and a conflict goes back to that part's lead. When
  every part is in, the goal's lead integrates: it checks that the parts fit together,
  builds what no part covers, and ticks the criteria. Then the goal goes on as below,
  with one push and one CI run for all of it. A part does not split again.
- **Rounds.** The lead is called on one session, in rounds of up to 200 turns; the next
  round continues the same conversation. If the session is lost, a new one starts from the
  journal and the branch. The lead ticks each criterion with the file that meets it, and a
  "done" with a criterion not ticked goes back to it. Only you can drop one.
- **Questions.** The lead asks what the prototype and the one-pager do not settle, and what
  only you have. The question waits on the TUI's Runs tab; your answer goes back to the
  lead, and it continues.
- **One push, at the end.** Every push runs CI, and CI costs money. So nothing is pushed
  while the lead works: the runner pushes once the lead reports done. Through a Claude Code
  hook, every agent's `git push`, `gh pr ready|merge|create`, `gh workflow run` and
  `gh run rerun` is refused.
- **Sync and CI, by the runner.** When the lead says it is done, the runner merges the base
  into the branch, pushes, marks the PR ready for review, and waits for its CI, as the merge
  step does for task runs. The runner waits for the whole CI run, even after a check
  fails, so a fix never starts CI over while a run still bills. Every failing check, with
  the telling lines of its log, then goes at once to a fresh call on the sub-agent model
  (Sonnet) to fix, with two tries before the lead takes it on. A fixer that commits
  nothing hands over without another CI run. When GitHub did not run the jobs at all (a
  spending limit or a failed payment), the runner asks you, and re-runs them once you
  answer: no fixer is called. A conflict goes to the lead. The full suites run only on CI, never on this
  machine. The checker runs no tests or CI at all: it is told what CI passed and judges only
  the code against the ticket. The PR comment lists what CI passed under **Checks**.
- **What it cost.** After each call, the goal notes the time, tokens and cost of the lead or
  the checker and of every sub-agent it started, from Claude Code's transcripts. `u` on the
  goal's row on the TUI shows it; it is `usage.txt` in the goal's state. Costs are at API
  prices: what the work would cost, not a bill. Each agent is priced from its own tokens at
  the rate its model's result reported, since a resumed session reports its running total.
- **Done means checked.** When the lead says it is done, a separate checker agent compares
  the branch with the references and the lead's acceptance criteria, which it does not
  trust to be complete. Each gap names its source. Gaps go back to the lead, which checks
  each against the references and pushes back on one the prototype contradicts. A
  conflict the references do not settle is a question to you. A check that is cut off by
  the usage limit, or fails, runs again: only a real verdict counts. Only a clean check
  finishes the goal: the PR gets the ticket link and the lead's summary, a comment with its
  walkthrough, and is marked ready for review.
- **Models.** The lead runs on Opus. Its sub-agents run on Sonnet by default
  (`CLAUDE_CODE_SUBAGENT_MODEL`, and a hook gives it to each one started without a model,
  since built-in types such as Explore otherwise take the lead's model), as most of them do narrow, well-briefed work;
  the lead can ask for Opus for one that needs deep reasoning. The checker runs on Fable at `xhigh`
  effort. It only verifies and reports: it plans no fix and changes nothing, and leaves
  the legwork on a large diff to Sonnet sub-agents. So the
  strongest model costs little there. All four are on the TUI's Setup tab, and on
  `cortex goal new` as `--model`, `--subagent-model`, `--check-model` and `--check-effort`.
  A goal keeps the models it started with.
- **Usage.** Your Claude subscription's limits (`/usage`) are read before each call and
  every 5 minutes during one. At 75% of any limit (`--threshold`) the call winds down
  rather than stopping: through Claude Code hooks, new sub-agents are refused and every
  tool call tells the agents to finish the step they are on, commit, note in the journal
  where they stopped, and end. Usage is read every minute while it winds down. Only at 2%
  past the limit is the call cut off, and then the lead is told on resuming which
  sub-agents were stopped and which files were left uncommitted. Either way the goal
  pauses until the limit resets, then carries on.
- **Stops.** Three rounds in a row that change nothing, four checks in a row that find
  gaps, a refused push, or an agent call that keeps failing: each is a question to you,
  not an end.

The goal never merges, rebases or force-pushes, and never touches another branch.

## Files

A goal keeps its state in `.cortex/state/<id>/`:

| File | What |
|---|---|
| `goal.json` | the ticket, the ask, the branch, the PR, the status, the round, the last usage read |
| `attachments/` | the ticket's attachments |
| `journal.md` | the lead's references, acceptance criteria, plan, progress and decisions |
| `parts.json` | the parts, when the lead split the work; each part's own state is `<id>--<part>/` |
| `goal.log` | everything the harness did |
| `awaiting.json` | the question waiting on you, while there is one |
| `usage.json` | the tokens of every call |
| `calls.json`, `usage.txt` | each call's time, tokens and cost, by agent, and the report `u` shows |

Its worktree is `.cortex/worktrees/<id>`, on the branch `<ticket key>/goal-<slug>`.

## Tests

```bash
python3 -m unittest discover -s tests
```
