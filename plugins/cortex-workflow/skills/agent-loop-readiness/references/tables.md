# Readiness tables — referenced from ../SKILL.md

## Decide or stop?

The unattended run is the engineer on the card. It decides the way a senior engineer decides when the
author is offline: from the problem, the goal, the code and the conventions around it, and it writes the
decision down. The two stop conditions are in `../SKILL.md`; these are the same line drawn through
concrete cases.

| Decide, and record it | Stop |
|---|---|
| A threshold, window or unit the card leaves out: take the one a sibling feature uses, else the smallest that satisfies the Definition of done | The card's Definition of done names a number that the Problem section shows is the wrong quantity |
| A wire name, enum value or payload key: follow the repo's naming in the nearest existing contract, add it additively, name the consumers you checked | Two consuming repositories already disagree on the name and the card names neither |
| Two conventions in the repo: the one nearer the touched code, or the newer one when they are equidistant | The card's Contract mandates the convention the touched module was migrated away from |
| Which non-live rung proves the change: the highest one the change allows, with the fixture built from the card's evidence | The Definition of done can only be observed against a live third-party account and the card names no recorded payload |
| A migration or backfill script the card asks for: write it, test it against the container, never run it against a live store | The card's fix would delete or overwrite data the Problem section says must be kept |
| A `file:line` that moved: find the code by name, note the new location | A file, field or endpoint the card names does not exist and nothing in the repo corresponds |
| A dependency written in prose: check whether the blocker landed; landed → build on it, not → stop as a contradiction with the ordering | A dependency's merged contract differs from what the card's Contract expects |
| Category absent: `Bug` when the Problem quotes an error or a wrong value, else feature | The card asks for two repositories' work at once |

Several small decisions in one card are fine; each is recorded. A decision is not a stop because it is
the third one.

## The vague-word gate

Scan the card for these. Each one is a failed check 5.

| Word | What it needs |
|---|---|
| stable, flat, steady | A tolerance (±5%, ±1pp) |
| substantial, significant, strong | A threshold, or the clause deleted |
| contextual, it depends | A number; the nuance goes in the user-facing copy, not the spec |
| recent, historically | A window in days |
| fast, slow, heavy | A measured budget (ms, rows, MB) |
| "and the rest", "etc.", "similar" | The full enumeration |
| "map X to Y" | The actual mapping table |
| "properly", "correctly", "as expected" | The expected value, stated |

An unattended agent needs a number even where the source said "contextual". In author mode, pick one,
state it, and say where the nuance lives instead.

## Rationalizations

Both directions get argued, in the words they get argued in. Each is answered.

**For stopping when you should decide:**

| Excuse | Reality |
|---|---|
| "It sets a wire contract, so it's the operator's call." | Every PR goes through the review run and a human before it reaches `main`. A name is one comment to change; a day in Blocked is not. Follow the nearest contract, add it additively, record it. |
| "Two places in the repo do it differently, so the convention is in question." | Pick the one nearer the code you touch and say so. The reviewer who disagrees names the other one. |
| "I'd rather ask than guess." | Deciding from the problem, the goal and the code is not guessing. Asking with a proposed answer you believe in is asking permission to do what you were going to do. |
| "The card doesn't say which rung proves it." | The change says. Pick the highest non-live rung it allows and build the fixture. |
| "There are three open points, that's too many to decide." | Count is not a stop condition. Record three decisions. |

**For deciding when you should stop:**

| Excuse | Reality |
|---|---|
| "The Definition of done is impossible as written but I know what they meant." | You know one reading of what they meant. A DoD that cannot follow from the card is a contradiction; stop and say which line. |
| "The file it names isn't there, but something similar is." | Similar is a decision only when it is the same thing moved or renamed. A different thing is a contradiction with the card's evidence. |
| "I'll build the half that fits in this repo." | A card spanning two repositories is authored wrong; half of it ships a broken contract. Stop. |
| "The dependency's contract changed, I'll adapt to it silently." | The card's Contract and the landed contract disagree; the author has to pick. Stop, quoting both. |
| "Two readings, I'll flip a coin and note it." | If nothing on the card, in the code or in the conventions favours one, that is the definition of no clear solution. Stop. |

## Common mistakes

| Mistake | Consequence |
|---|---|
| Stopping on a point that had a defensible answer | A day of queue time to be told what you already proposed |
| Deciding past a contradiction | A PR that builds the wrong thing well, and a reviewer who has to find that out |
| Asking questions with no proposed answers or no stop condition named | Cards sit in `Blocked` for days |
| A decision taken and not recorded | The reviewer cannot tell a choice from an oversight |
| Accepting a prose dependency | The run starts before its blocker exists and builds on nothing |
| One card for two repositories | Hidden deploy ordering, surfaced as a broken release; the run cannot ship both halves from one worktree |
| "Verify on staging" as the whole verification plan | The agent has no way to prove the change and stops at QA |
