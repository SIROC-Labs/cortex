---
name: agent-loop-author
version: 0.1.0
description: Use when anything has to become work on the agent board — product or stakeholder feedback, review notes, a benchmark table, a UX critique, customer complaints, a bug report, a chat thread, a screenshot, a spec, or a one-line idea — including requests to analyse input, find improvements, plan tasks from it, break it into tickets, or report back on what will be built. Produces cards an unattended run can execute one-shot.
---

# Authoring agent loop cards

## Overview

One job: **turn any input into one or more cards that an unattended agent can execute one-shot.**

Input describes a desired **output**. A card describes a buildable **change**, specified tightly enough
that nobody has to be present while it is built. The gap between the two is where all the work is.

**Core principle: verify, then scope, then gate.** Every claim the input makes is checked against code
before it reaches a card, and every card is checked against `agent-loop-readiness` before it reaches
the board.

## Any input

See `references/authoring.md` → "Any input".

## Read the source, not your summary

Enumerate asks from the source itself. A long document read in chunks loses items between chunks. When
verifying coverage later, map **source → cards**, never cards → source — the second direction can only
confirm what you already wrote.

## Before planning anything: four verifications

See `references/authoring.md` → "Before planning anything: four verifications".

## Split by deployable unit

One card per repo or platform. A card spanning two deploy units hides an ordering constraint that
surfaces as a broken release — and an unattended run works in one worktree, so it cannot ship both
halves anyway.

Make cross-unit contract changes **additive**: add the new field or value, keep the old one serving,
remove it in a follow-up. Then either side can ship first. State in the card which side degrades and how
— "an unaware client renders it as plain text" is a shipping decision, not a footnote.

## Dependencies and branches

Do not assume the base is `main`. Check whether the branch this work extends is itself merged — an
unmerged parent makes it the base for everything downstream.

Record each card's base branch, and set its blockers as **task-manager dependencies** (`add_dependency`), not prose. The run's gate reads dependencies and lets a blocker through once it is completed or sits in the board's in-review, ready or done column; "after the ledger task lands" in a description is invisible to it and the run will start anyway.

Chains form for two reasons and both belong in the card: **logical** (needs the other's contract) and
**file overlap** (edits the same files). File-overlap chains are often the ones that actually constrain
order.

## Card shape

Each card carries all of:

| Part | Content |
|---|---|
| Repo | The repo, resolvable — never inferable from the subject matter |
| Base branch | The branch to build on, and why if it is not `main` |
| Problem | The defect with `file:line` evidence, and the quote from the input that motivates it |
| Goal | One sentence of the end state |
| Definition of done | Observable outcomes |
| Spec | The contract: names, types, units, thresholds, boundaries, error behaviour |
| Execution plan | Ordered file-level steps |
| Verification | The non-live proof the agent must produce, its fixtures or seed data — **and** the live check left to the operator, named as theirs |
| Dependencies | Task-manager dependency links, plus their branch names |
| `Priority` | The neutral Priority field, highest option first. This is the queue's running order; unset sorts last |
| **Decisions taken** | 2–3 calls you made that the reader might overturn |
| `Category` | A real value, so the run routes bug-fix versus feature work — `Bug` routes bug-fix, everything else routes feature. Never left at `To be Specified` |

**"Decisions taken" is load-bearing.** It converts a silent assumption into a cheap correction. Expect
several to be overturned — that is the section working, not failing.

**The Verification row is what makes a card executable unattended.** The queue never runs a live
service, so a card whose only stated proof is "check it on staging" leaves the agent with no way to
finish. Name the rung — a unit test on the mapper, an integration test against the container, an
element-scoped harness — and name the operator's live check separately.

## The readiness gate

**Every drafted card goes through `agent-loop-readiness` before it is created.** That skill owns the
bar; do not restate or relax its checks here.

Run it in **author mode**: a failed check is a question you ask the human *now*, patch into the card, and
then re-run all ten checks from the top. Loop until a full pass produces no questions. An answer
routinely creates a new unknown, so a single pass over the failures is not the gate.

Nothing reaches the board carrying a `NOT READY`. A card parked as a draft until an answer arrives is
fine; a card on the queue that the run will stop on is not — it costs an hour of queue time and a
round-trip.

## The completeness sweep

Before declaring the plan done, walk the source top to bottom and map each ask to a card or to a stated
exclusion. Anything unmapped is a gap — expect to find some, and expect at least one to be a general
case you scoped too narrowly.

## Creating the cards

Show the full card list in chat for approval first — titles plus the one-line goal, the repository, and the dependency order. Then state the target board and column before writing anything.

Cards meant for unattended execution go to the agent board's **queue**: `resolve_board("agent-queue")` gives the board and its role → column map (the interface says "run agent-loop-setup" when there is none; stop and say so). For each approved card, in dependency order: `create_task(title, description, board, fields={Priority, Category, …})`, then `move_task(card, board, columns.queue)` — a card created without a column may land outside every role and the run never sees it. Set dependencies with `add_dependency` after all the cards exist, since a link needs both refs.

**There is one queue and it is ordered by priority.** Reworks and first implementations sit in the same column, so `Priority` decides what runs next — set it on every card, and put the card at the top of the column when it should be taken before its equals. Never assume a card will be picked up because it is a fix.

Create cards only at the level asked for. No milestone, section or project unless it was requested.

## Reporting back

Four buckets, in this order:

1. **Doing as asked** — no commentary needed.
2. **Doing, with changes** — each with the reason. Reasons are mechanisms, not preferences.
3. **Not building** — state the missing data source. This is not a judgment about value, and saying so
   plainly is what keeps the relationship.
4. **Deferred** — what would make it schedulable.

Record every exclusion in the code with its reason, or the next reader re-adds it from the same input.

## Common mistakes

See `references/authoring.md` → "Common mistakes".

## Red flags

- You are writing a card for a metric you have not traced to its source.
- A threshold in your spec is a word rather than a number.
- You wrote "not feasible" without opening the file.
- Your coverage check started from the card list.
- Every "decision taken" survived review — you are not surfacing the real calls.
- You are about to create a card you have not run `agent-loop-readiness` over.
