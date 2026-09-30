---
name: agent-loop-readiness
version: 0.1.0
description: Use when a task is about to be executed by an unattended agent run or written for one — auditing a claimed card from the agent board, drafting a card destined for its queue, judging whether an ambiguity is a stop or a safe default, or at the moment an unattended run is about to ask the operator a question.
---

# Agent loop readiness

A task is **ready** when an agent with no human present can carry it to a shipped, verified PR
**without asking a single question**.

Two things make that true. The card states the problem, the goal, what done looks like and how it is
proved. And the run **decides everything else itself**: it reads the card, the repository and its
conventions, takes the call a senior engineer on the team would take, and records it in the PR under
"Decisions taken" for the reviewer to overturn. A question is not the safe option; it is a day of queue
time. The run stops only on a **stop condition** (below).

## The two modes

The checks are identical; only what you do with a failure differs.

| Mode | You are | A failed check means |
|---|---|---|
| **Audit** | an unattended run holding a claimed card | Decide it, record the decision, and pass the check — unless the failure is a **stop condition**, in which case return the questions to the invoking workflow, which moves the card to its blocked column and ends the run. |
| **Author** | writing or fixing a card with the human present | Ask now, patch the card with the answer, **re-run every check from the top**, repeat until READY. The human is there; every open point is cheap to close. |

In author mode the loop matters: an answer routinely creates a new unknown (a named threshold raises
"per what window?"). Re-running only the check that failed ships a card that fails a different check.
Keep looping until a full pass produces no questions.

## Stop conditions (audit mode)

An unattended run routes a card to blocked for exactly two reasons. Anything else is its decision.

| Stop when | Meaning | Not a stop |
|---|---|---|
| **No clear solution** | After reading the card, the repository and its conventions, two or more materially different implementations remain and nothing favours one: not the card's Problem or Goal, not a convention the repo applies anywhere, not the smallest change that satisfies the Definition of done | A missing threshold, name, window or type with any basis to pick from; a choice between two repo conventions where one is nearer the touched code; anything a reviewer overturns with one comment |
| **Contradiction** | The card conflicts with itself or with reality: the Definition of done cannot follow from the Approach; the fix would undo what the Problem says is wrong; a file, field, endpoint or branch the card names does not exist and nothing corresponds to it; a dependency landed a contract the card's Contract disagrees with; the card spans two repositories | Code that differs from the card's `file:line` because it moved; a stale line number; a name that changed but whose thing is still there |

A decision taken under this rule goes in the PR body under "Decisions taken", as the call made, the
alternative rejected and why. That entry is the question the run would have asked, answered where the
reviewer reads it.

## The checks

Run all of them. Record a verdict per check — a check you did not evaluate is a failed check.

| # | Check | Satisfied by | Failed by |
|---|---|---|---|
| 1 | **Repo** | A repository named on the card, resolvable to `<repos root>/<dir>` (the repos root from the agent-loop cache, `agent_loop.py read <provider>` → `repos_root`) or to an `org/repo` whose `origin` remote matches a directory under it | Nothing named; a bare word matching several or no directory; a repo inferable only from the subject matter |
| 2 | **Base branch** | A branch that exists on `origin`, or no branch named at all (→ `main`) | A branch named that `git ls-remote --heads` does not find |
| 3 | **Definition of done** | An outcome you could write a test or a QA step against, today, before reading any code | "Improve", "make better", "clean up", "optimise", "handle properly" |
| 4 | **Single reading** | Two engineers reading it write the same code | Two readings that produce materially different code; the card itself posing an open question |
| 5 | **Contract** | Every name, type, unit, threshold, boundary and error behaviour the change introduces is stated | Any of them left to the implementer, or expressed as a word instead of a number (see the vague-word gate) |
| 6 | **Verification without live services** | At least one non-live rung proves it: a unit, an integration test against a container, an in-process API test, or an element-scoped browser harness | The only proof is a run against staging, prod, or a real third-party account — see "Verification the agent cannot do" |
| 7 | **One repository** | One repository, resolvable to one worktree and one base branch | A card spanning two repositories without the split; two cards in one repository that depend on each other |
| 8 | **Dependencies machine-readable** | Blockers are task-manager dependencies (`get_dependencies(task)` through the task-manager interface) | A blocker stated only in prose ("after the ledger task lands") |
| 9 | **Scope boundary** | The card names the files, module or surface it may touch, or is small enough that "what you touch" has one reading | An open-ended sweep ("and anywhere else this pattern appears") with no enumeration |
| 10 | **Category** | The neutral `Type / Category` field is set to a real value — it routes bug-fix versus feature work | Absent, or left at `To be Specified`, when the card could plausibly be either |

In audit mode, a failed check 3, 4, 5, 6, 8, 9 or 10 is a decision unless it meets a stop condition; a failed check 1, 2 or 7 is always a contradiction. Worked examples: `references/tables.md` → "Decide or stop?".

Check 5's vague words and what each needs: `references/tables.md` → "The vague-word gate". Each hit is a failed check 5 in author mode; in audit mode the run picks the number, states where it came from, and records it.

## Verification the agent cannot do

Check 6 exists because the queue never runs a live service — no staging or production app, no real
third-party account, no packed browser extension in the operator's browser. A card whose only possible proof
is a live run is not unexecutable; it is **incompletely specified**. Ready means it carries both:

- **the non-live proof the agent will produce** — the rung, and the fixture or seed data it needs; and
- **the live check left to the operator** — named as such, with the command or the URL.

A card that says only "verify on staging" fails check 6 in author mode. In audit mode the run picks the
highest non-live rung the change allows, builds its fixture, and names the staging check as the
operator's; that is a decision, not a stop.

## Questions that get answered

A question the human cannot answer in one sentence is not a clarification, it is a delay.

**Every question carries a proposed answer.** "Which window — I propose 30 days, matching
`ShopStats`?" gets a one-word reply. "What window should this use?" gets nothing for a day.

- Numbered, specific, independently answerable.
- One line each, with the default you would take and where it comes from.
- Never "please clarify the requirements", never "let me know how you'd like to proceed".
- Name what is already established, so the reply does not re-litigate it.

## Output

Emit this verdict, whichever mode you are in:

```
READINESS: READY
  checks 1-10 pass
  Repo: <org/repo or path>   Base: <branch>   Category: <value>
  Non-live proof: <rung(s)>
  Left to the operator: <live check, or "none">
```

```
READINESS: NOT READY
  Failed: <check numbers and names>
  1. <question> — proposed: <default>, because <where it comes from>
  2. <question> — proposed: <default>, because <where it comes from>
  Established: <what is already settled, one line>
```

In audit mode that question list is returned verbatim to the invoking workflow, which posts it on the card, and every question names which stop condition it meets.

The arguments for stopping when you should decide, and for deciding when you should stop, each answered: `references/tables.md` → "Rationalizations". Read it when you notice one.

## Red flags

- You are about to stop on a question that has a proposed answer you believe in — that answer is the decision; take it.
- A question you drafted names no stop condition.
- The verification story is "run it on staging and look".
- You re-ran one check after an answer instead of all ten (author mode).
- You are about to build something the card's Problem says is the bug.
- Two engineers would build different things and you cannot say why yours is the one — that is the stop.

Consequences of skipping a check: `references/tables.md` → "Common mistakes".
