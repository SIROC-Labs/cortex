---
name: agent-loop-author
version: 0.1.0
description: Use when anything has to become work on the agent board — product or stakeholder feedback, review notes, a benchmark table, a UX critique, customer complaints, a bug report, a chat thread, a screenshot, a spec, or a one-line idea — including requests to analyse input, find improvements, plan tasks from it, break it into tickets, or report back on what will be built. Produces one milestone with its feature branch per repository, and cards under it that an unattended run can execute one-shot, one card per parallelizable unit of work in one repository.
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

## One card per parallelizable unit, in one repository

A card is the largest piece of work that one run can build and one review can merge on its own, inside
one repository. Group, then split:

1. Group the asks by repository. A card never spans two: a run works in one worktree, and a review
   merges into one branch.
2. Within a repository, merge into **one card** every ask that is sequentially dependent on another —
   it needs the other's contract (logical) or edits the same files (file overlap). Repeat until no two
   cards in the same repository depend on each other.
3. What is left in a repository is independent; those cards run in parallel. Keep them separate.

Dependencies therefore only ever cross repositories. Make cross-repo contract changes **additive**: add
the new field or value, keep the old one serving, remove it in a follow-up. Then either side can ship
first. State in the card which side degrades and how — "an unaware client renders it as plain text" is a
shipping decision, not a footnote.

A bigger card is still a one-shot card: the problem, the approach, the definition of done and the
verification are exact; how the code gets there is the run's.

## The milestone and its branches

Every run of this skill produces exactly one milestone, even for a single card: it is what the
milestone branch hangs off, and what a later extension adds cards to. See `references/authoring.md` →
"The milestone".

- **Hosting project.** Ask the operator for the URL of the project that hosts milestones; there is no
  default. Resolve it through the task-manager interface and confirm it is a board. Refuse the agent
  board: a milestone there is a section, and the agent board's columns are its six roles.
- **Anchor.** `ensure_milestone(project, <name>)`, the name proposed from the source in one line and
  confirmed.
- **Branches.** Per repository the cards touch, the parent is the branch this work extends: `main`, or
  an unmerged branch the work builds on. Cut `milestone/<slug>` from `origin/<parent>` and push it, so
  the readiness check finds it on `origin`. One `<slug>` across every repository. An existing
  `milestone/<slug>` is reused.
- **Base branch.** Every card's base is `milestone/<slug>` unless the operator asks for the default
  branch. The review run merges each card's PR into a milestone branch; merging the milestone branch
  into its parent stays the operator's, and the anchor's description says so. A PR against the
  default branch is approved by the review run and merged by the operator, so a card based there
  gates its dependents until that merge.

Set blockers as **task-manager dependencies** (`add_dependency`), not prose. The run's gate reads
dependencies and lets a blocker through once it is completed or sits in the board's ready or done column
— that is, merged into its milestone branch; "after the ledger task lands" in a description is invisible
to it and the run will start anyway.

## Card shape

Each card carries all of:

| Part | Content |
|---|---|
| Repo | The repo, resolvable — never inferable from the subject matter |
| Base branch | `milestone/<slug>`, or the default branch when the operator chose it |
| Problem | The defect with `file:line` evidence, and the quote from the input that motivates it |
| Goal | One sentence of the end state |
| Approach | One paragraph: the idea and its direction, the layer it lives in, what it deliberately does not do. No file-level steps, no code |
| Definition of done | Observable outcomes, one per line, each testable |
| Contract | Only what is observable from outside the change: wire names, enum values, types, units, thresholds, user-visible numbers, error behaviour. Internal names and structure are the run's |
| Verification | The non-live proof the agent must produce, its fixtures or seed data — **and** the live check left to the operator, named as theirs |
| Scope boundary | The files, modules or surfaces the card may touch |
| Dependencies | Task-manager dependency links (cross-repo only), plus their branch names |
| `Priority` | The neutral Priority field, highest option first. This is the queue's running order; unset sorts last |
| **Decisions taken** | 2–3 calls you made that the reader might overturn |
| `Category` | A real value, so the run routes bug-fix versus feature work — `Bug` routes bug-fix, everything else routes feature. Never left at `To be Specified` |

**"Decisions taken" is load-bearing.** It converts a silent assumption into a cheap correction. Expect
several to be overturned — that is the section working, not failing.

**The Verification row is what makes a card executable unattended.** The queue never runs a live
service, so a card whose only stated proof is "check it on staging" leaves the agent with no way to
finish. Name the rung — a unit test on the mapper, an integration test against the container, an
element-scoped harness — and name the operator's live check separately.

**Approach and Scope boundary are what keep a bigger card single-reading.** Without an execution plan,
the approach says which way the run goes and the boundary says where it stops; the review run checks
both against the diff.

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

Show the milestone name, the per-repository branch table and the full card list in chat for approval first — titles plus the one-line goal, the repository, and the dependency order. Then state the hosting project, the target board and column before writing anything.

Order of writes: the milestone anchor, the branches, then the cards. Cards meant for unattended execution go to the agent board's **queue**: `resolve_board("agent-queue")` gives the board and its role → column map (the interface says "run agent-loop-setup" when there is none; stop and say so). For each approved card, in dependency order: `create_task(title, description, board, milestone=<anchor ref>, fields={Priority, Category, …})`, then `move_task(card, board, columns.queue)` — a card created without a column may land outside every role and the run never sees it. Membership in the milestone places the card in the hosting project too; the agent board stays the queue. Set dependencies with `add_dependency` after all the cards exist, since a link needs both refs. Last, `set_description(anchor, …)` with the card list filled in.

**There is one queue and it is ordered by priority.** Reworks and first implementations sit in the same column, so `Priority` decides what runs next — set it on every card, and put the card at the top of the column when it should be taken before its equals. Never assume a card will be picked up because it is a fix.

Create nothing beyond the milestone and its cards: no section, no project, no second milestone.

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
- A card's base branch is `main` without the operator asking for it, or two cards in one repository depend on each other.
- Your card carries file-level steps — that is the run's plan, not the card's.
