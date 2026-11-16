# goal

A prompt, implemented by itself, on one branch, into one PR.

```bash
cond goal new "Fix the inbox badge: it counts read items" --start
cond goal new https://app.asana.com/0/0/1218985136116349 -f mock.png --base feature/m6
echo "Long prompt..." | cond goal new          # the prompt from stdin; start it later
cond goal run goal-fix-the-inbox-badge        # run or resume one in the foreground
cond goal undo goal-fix-the-inbox-badge       # take all of it back out
```

The usual way in is `cond queue add`, or the TUI. The goal then shows on the TUI's Runs
tab, where you answer it, approve its plan, stop it and carry it on.

## How it works

The ask is the prompt: what you wrote, and the files you gave with it (`-f`, an image
too), copied into the goal. Each Asana ticket the prompt links to is read once, when the
goal starts: its description, its open subtasks, its comments and its attachments (an
HTML attachment as its text, with the file kept for its prototype). A milestone works
well: its subtasks become parts of one piece of work. Nothing is ever written to Asana:
questions, the plan and its approval are in conductor.

The goal's name is the prompt's first line, or the ticket's name when the prompt is only
a link; a linked ticket's key goes into its id and branch. Without `--base`, the PR goes
into `main`.

A **lead agent** gets the ask and nothing more. It plans the work, keeps a journal, and
starts its own sub-agents, reviewers and checkers as it sees fit. It commits on the goal's
branch as it goes. Nobody breaks the work down for it.

**Which source wins.** The prototype is the source of truth: it decides what is built and
how each screen looks and behaves. Only your answers to questions overrule it, and the
ask where it says explicitly that it replaces the prototype ("X instead of the
prototype"). An ask that only describes something differently does not. One-pagers,
PRDs and the product repository are never used; an attached one-pager is left out of the
ask. What the prototype does not show or answer, you decide. The rule is one text,
`SOURCES` in `goal.py`, given to the lead, the reviewer, the checker and a part's consult.

This program is the harness around the lead:

- **Analysis first.** The first round changes no code. The lead reads every reference the
  ask names, checks what the ask takes for granted against the code (a branch it builds on,
  earlier work it needs), and writes into its journal: `## References`, fine-grained
  `## Acceptance criteria` (one line for each screen part, state, rule or field, each with
  its source), and a `## Plan`. It also writes `technical-plan.md` in the goal's state: how
  the work will be built, in Simplified Technical English, with tables and mermaid
  diagrams (overview, where the code goes, data model, flows, API, frontend, tests, risks).
  When it splits the work, that is only an overview of the parts and where they meet; each
  part's lead writes its own. Its questions come to you together. The runner sends the
  lead back until it has all four.
- **Testing guide.** When the repository has `TESTING.md` files, the lead is told to read
  them in the analysis, plan and write its tests by them, and give them to every sub-agent
  that writes tests; the checker judges the tests against them.
- **Criteria review.** The checker's model then compares the criteria with the references,
  before anything is built: criteria that are missing, wrong, or too broad, and questions
  only you can answer. The lead corrects the criteria and the plan.
- **Your approval.** Then nothing is built until you approve the plan. It waits on you
  with its steps or parts listed, and its technical plan in the goal's state: review the
  criteria alone to move fast, and the technical plan when the design needs care. To
  approve, press `c` on the goal's row on the TUI, or answer it with an approval (`ok`,
  `continue`, `lgtm`). Anything else you answer is changes: the lead revises the plan and
  it waits for you again, with what changed at the top. *Plan
  approval* on the Setup tab (or `--gate`) sets who approves: you, for the goal and each
  part (`wait`, the default); you for the goal and the reviewer for its parts (`top`); or
  the reviewer only (`auto`). A goal keeps the setting it started with.
- **Tiny work.** When the lead finds the work tiny and clear, such as a quick bug fix or
  one button on a screen, it says so with the plan. Then there is no review, no approval
  and no technical plan, whatever *Plan approval* says: after its questions, if any, it
  builds and opens the PR. A goal that splits, and a part, is always reviewed.
- **Parts, for very large work.** One lead builds most goals: its tasks already run at the
  same time. Only work of more than about 60 criteria, in areas that can be built at the
  same time, is split, never into a chain of parts that wait for each other. It writes `parts.json` in the
  goal's state: up to 8 parts, each with a summary for you, a short brief for the part's
  lead (what it builds, the references that cover it, what it must not touch, and where it
  meets other parts; the design inside the part is left to its lead), its criteria copied
  from the lead's list, and the parts it comes `after`. The runner checks the split (every
  criterion from the list, none in two parts, no circle), and the review checks its
  boundaries too. Each part then runs as a goal of its own, with its own lead, analysis,
  journal, sub-agents and checker, on a branch off the goal's (`<branch>--<part>`).
  Every part plans as soon as you approve the split; `after` holds back only its build,
  until those parts are merged, and two parts build at a time. A part that cannot sensibly
  be planned before another is built names it in `plan_after`, and starts once that one
  is merged. A part's
  questions go to the goal's lead first, and only what it cannot settle comes to you. A
  part is never pushed: when its check passes, it merges the goal's branch in and is
  merged into it, one part at a time, and a conflict goes back to that part's lead. When
  every part is in, the goal's lead integrates, in a new session: the planning's context is
  stale by then, so it starts from its journal and the parts' journals. It checks that the
  parts fit together, builds what no part covers, and ticks the criteria. Then the goal goes on as below,
  with one push and one CI run for all of it. A part does not split again.
- **Rounds.** The lead is called on one session, in rounds of up to 200 turns; the next
  round continues the same conversation. If the session is lost, a new one starts from the
  journal and the branch.
- **The build is delegated, in a new session.** Every step of a session sends the whole
  conversation again, so a build carried on from the planning costs far more than the work.
  The build starts in a new session, from the journal, the technical plan and the branch,
  and so does a build carried on after a usage pause or a restart. In the build the lead
  does not start agents: it ends each session with a `dispatch` block, a list of tasks.
  A coding task makes one change; a question asks an explorer one thing about the code.
  The runner runs the whole list at once (six at a time), each coding task as its own
  `claude -p` call on the sub-agent model, in its own worktree off the goal's branch. A
  task's worktree links the goal worktree's `node_modules` and `.venv`, so it can run the
  tests of what it changed without an install; it runs nothing else, since the runner,
  the checker and CI test after it. When the tasks end, the runner commits what each
  left, merges each finished task's branch into the goal's branch, removes the
  worktrees, and calls the lead again, in a new session, with only their reports. A task
  that failed, or conflicts with one merged before it, keeps its branch, and its report
  says so. Whatever the runner hands back (failing tests, a conflict, CI, the checker's
  gaps, criteria not ticked) starts a new session too. Only an answer to the lead's own
  question goes back into its session. In the build the lead
  coordinates, coding tasks write the code, and explorers read it: a hook
  refuses the lead, and only the lead, an edit to the worktree, a shell command that
  writes a file there, and a read of its code (Read, Grep, Glob, or `cat`, `grep`, `sed`
  and the like), Markdown aside. Every file the lead reads stays in its context and is
  paid for on every later turn; an explorer answers one narrow question for a few cents.
  The lead can still run git, commit, and edit its journal and technical plan. In the
  analysis it is told to learn the codebase through explorers too. The lead ticks each criterion with the file that meets it, and a
  "done" with a criterion not ticked goes back to it. Only you can drop one.
- **Questions.** The lead asks what the prototype and your answers do not settle, and what
  only you have, all at once in the analysis where it can. They wait on the TUI's Runs
  tab, and the goal goes on once you answer them. The plan is approved only after its
  questions are answered.
- **One push, at the end.** Every push runs CI, and CI costs money. So nothing is pushed
  while the lead works: the runner pushes once the lead reports done. Through a Claude Code
  hook, every agent's `git push`, `gh pr ready|merge|create`, `gh workflow run` and
  `gh run rerun` is refused.
- **Check, then sync and CI, by the runner.** When the lead says it is done, the runner
  merges the base into the branch and has the checker check it, without pushing. Only a
  clean check is pushed: a gap found after CI would cost a second CI run. The runner then
  marks the PR ready for review and waits for its CI. The runner waits for the whole CI run, even after a check
  fails, so a fix never starts CI over while a run still bills. Every failing check, with
  the telling lines of its log, then goes at once to a fresh call on the lead's model
  (Opus) to fix, with two tries before the lead takes it on. The fixer opens only the files
  and lines the failures name, decides each fix, and has sub-agents on the sub-agent model
  (Sonnet) make the changes: a hook refuses its own edits and gives every sub-agent that
  model. A fixer that commits
  nothing hands over without another CI run. When GitHub did not run the jobs at all (a
  spending limit or a failed payment), the runner asks you, and re-runs them once you
  answer: no fixer is called. A conflict goes to the lead. The full suites run only on CI, never on this
  machine. The checker runs no tests or CI at all: it judges only the code against the ask.
  A CI fix by the fixer is pushed without another check; one by the lead is
  checked again first. The PR comment lists what CI passed under **Checks**.
- **What it cost.** After each call, the goal notes the time, tokens and cost of the lead or
  the checker and of every sub-agent it started, from Claude Code's transcripts. `u` on the
  goal's row on the TUI shows it; it is `usage.txt` in the goal's state. Costs are at API
  prices: what the work would cost, not a bill. Each agent is priced from its own tokens at
  the rate its model's result reported, since a resumed session reports its running total.
- **Done means checked.** Tests guide the coding tasks while they code: each runs the tests
  of its own change, and they are not a gate. When the lead says it is done, the runner
  first runs the repo's own CI static checks here (a `ci-verify` make target at the root,
  and a `ci-verify` script in each package): they show in seconds whether the merged
  pieces fit, before a push pays for CI. Each step runs on its own, past a failure too:
  every prerequisite of the make target, and each `&&` step of the script (an `npm run x`
  in it is x's own steps). So every failure shows at once, not one per round. The
  failures go to the fixer (Opus judges, Sonnet sub-agents change), twice, then to the
  lead; the fixer runs only the failing steps again. Coding tasks format and lint the files they change.
  A fix about other failures than the last one starts the tries again, since the last
  fix made progress; after ten fixes in a row the runner asks you anyway. Then a separate checker agent compares the branch with the references and the lead's acceptance criteria, which
  it does not trust to be complete. Each gap names its source. Gaps go back to the lead, which checks
  each against the references and pushes back on one the prototype contradicts. A
  conflict the references do not settle is a question to you. A check that is cut off by
  the usage limit, or fails, runs again: only a real verdict counts. Only a clean check
  finishes the goal: the PR gets the ask and the lead's summary, a comment with its
  walkthrough, and is marked ready for review.
- **Re-checks are scoped.** The first check reads the whole branch. After it, a check
  covers only the last check's gaps, the review comments of a PR revision, and the
  branch's own commits since the last check. A split goal's first check skips the parts'
  criteria, which their own checkers checked: it covers the goal's own criteria, how the
  parts meet, and the integration since the parts were merged. A branch rewritten since
  the last check is checked whole.
- **After the finish.** The runner stays, and watches the PR every minute until it
  is merged or closed: "ready to merge" on the TUI. Each new review comment on it (a
  review, an inline comment, or a top-level comment, but not the runner's own) starts a
  revision: the lead, in a new session, has sub-agents address it, then the runner checks
  it, pushes, waits for CI, and replies on the PR with the lead's summary. Only the merge
  makes the goal done; a goal whose PR was closed says so. A goal that finished before
  goals watched their PR says "r watches it": r starts the watch. Comments left before
  the finish are not taken as review comments. `d` on the TUI marks a goal done by hand, at any
  time: the runner stops and nothing it writes as it ends undoes the mark.
- **Models.** The lead runs on Opus. Its sub-agents run on Sonnet by default
  (`CLAUDE_CODE_SUBAGENT_MODEL`, and a hook gives it to each one started without a model,
  since built-in types such as Explore otherwise take the lead's model), as most of them do narrow, well-briefed work;
  the reasoning is the lead's, so no task or sub-agent runs on Opus. The checker runs on Opus at `high`
  effort, and so does the review of the plan. It only verifies and reports: it plans no fix
  and changes nothing, and leaves the legwork on a large diff to Sonnet sub-agents. All four are on the TUI's Setup tab, and on
  `cond goal new` as `--model`, `--subagent-model` and `--check-model`, all but the effort.
  A goal keeps the lead's and the sub-agents' models it started with. The checker's model and
  effort are what the Setup tab shows, read at each check and review, so they hold for every
  goal, running ones too.
- **Permissions.** No run uses bypass mode, which a repo may turn off (Humanus does). Each
  call runs in auto mode: reading, edits in the goal's worktree and state, sub-agents and
  the web are allowed outright, and a classifier judges every other action, such as a
  shell command. A model with no auto mode (Haiku 4.5) runs in dontAsk instead, with the
  shell allowed too. Task runs work the same way.
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

**Undo** takes all of a goal back out: it stops the goal and its parts, closes its PR and
deletes its branches, here and on GitHub, and removes its worktrees and its saved state.
It is *Undo the goal* in the TUI's palette on the goal's row, `cond queue undo <id>`, or
`cond goal undo <id>`.

**Discuss** opens a Claude session to talk a goal through, in the goal's worktree. Its
journal, its open questions and the end of its log are in the session's prompt. Of its
parts, only their state and the paths of their files are: the session reads a part's files
when the talk needs them, so a split goal's discussion stays small on every turn. It opens
by saying in a few lines what it has loaded, then waits for you. It runs in plan
mode, without the tools that edit files or write to Asana, and it is told to change
nothing: answers and approvals still go through the TUI or `cond`. It is *Discuss the
goal* in the TUI's palette, or `cond goal discuss [<id>]`: without an id, it lists the
repo's goals that are not done, to pick from by number or key.

## Files

A goal keeps its state in `.cortex/state/<id>/`:

| File | What |
|---|---|
| `goal.json` | the prompt, the ask, the branch, the PR, the status, the round, the last usage read |
| `inputs/` | the files given with the prompt |
| `attachments/` | the linked tickets' attachments |
| `journal.md` | the lead's references, acceptance criteria, plan, progress and decisions |
| `parts.json` | the parts, when the lead split the work; each part's own state is `<id>--<part>/` |
| `goal.log` | everything the harness did |
| `awaiting.json` | the question, or the plan, waiting on you, while there is one |
| `usage.json` | the tokens of every call |
| `calls.json`, `usage.txt` | each call's time, tokens and cost, by agent, and the report `u` shows |

Its worktree is `.cortex/worktrees/<id>`, on the branch `goal/<slug>`, or
`<ticket key>/goal-<slug>` when it links to a ticket.

## Tests

```bash
python3 -m unittest discover -s tests
```
