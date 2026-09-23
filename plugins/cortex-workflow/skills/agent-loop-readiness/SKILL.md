---
name: agent-loop-readiness
version: 0.1.0
description: Use when a task is about to be executed by an unattended agent run or written for one — auditing a claimed card from the agent board, drafting a card destined for its queue, judging whether an ambiguity is a stop or a safe default, or at the moment an unattended run is about to ask the operator a question.
---

# Agent loop readiness

A task is **ready** when an agent with no human present can carry it to a shipped, verified PR
**without asking a single question**.

That is the whole bar. Not "a competent engineer could figure it out" — a competent engineer asks.
Readiness means every question that *would* be asked is already answered on the card.

## The two modes

The checks are identical; only what you do with a failure differs.

| Mode | You are | A failed check means |
|---|---|---|
| **Audit** | an unattended run holding a claimed card | Return the questions to the invoking workflow, which moves the card to its blocked column and ends the run. Never guess to keep going. |
| **Author** | writing or fixing a card with the human present | Ask now, patch the card with the answer, **re-run every check from the top**, repeat until READY. |

In author mode the loop matters: an answer routinely creates a new unknown (a named threshold raises
"per what window?"). Re-running only the check that failed ships a card that fails a different check.
Keep looping until a full pass produces no questions.

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
| 7 | **One deployable unit** | One repo, one deploy unit | A card spanning backend and frontend, or two repos, without the split |
| 8 | **Dependencies machine-readable** | Blockers are task-manager dependencies (`get_dependencies(task)` through the task-manager interface) | A blocker stated only in prose ("after the ledger task lands") |
| 9 | **Scope boundary** | The card names the files, module or surface it may touch, or is small enough that "what you touch" has one reading | An open-ended sweep ("and anywhere else this pattern appears") with no enumeration |
| 10 | **Category** | The neutral `Type / Category` field is set to a real value — it routes bug-fix versus feature work | Absent, or left at `To be Specified`, when the card could plausibly be either |

Check 4's default-or-stop line: `references/tables.md` → "Default or stop?". The line is cost of being wrong, not confidence; two stacked defaults are a stop.

Check 5's vague words and what each needs: `references/tables.md` → "The vague-word gate". Each hit is a failed check 5.

## Verification the agent cannot do

Check 6 exists because the queue never runs a live service — no staging or production app, no real
third-party account, no packed browser extension in the operator's browser. A card whose only possible proof
is a live run is not unexecutable; it is **incompletely specified**. Ready means it carries both:

- **the non-live proof the agent will produce** — the rung, and the fixture or seed data it needs; and
- **the live check left to the operator** — named as such, with the command or the URL.

A card that says only "verify on staging" fails check 6. A card that says "unit-test the mapper
against the recorded payload in the description; operator confirms on staging with
`<the repo's staging command>`" passes.

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

In audit mode that question list is returned verbatim to the invoking workflow, which posts it on the card.

The arguments for shipping anyway, each answered: `references/tables.md` → "Rationalizations". Read it when you notice one.

## Red flags

- You are about to write "I'll assume…" in a plan for an unattended run.
- A check is marked pass because you could work it out, not because the card says it.
- The verification story is "run it on staging and look".
- A question you drafted has no proposed answer attached.
- You re-ran one check after an answer instead of all ten.
- Check 4 passed on the strength of a default whose cost of being wrong is a rewrite.

Consequences of skipping a check: `references/tables.md` → "Common mistakes".
