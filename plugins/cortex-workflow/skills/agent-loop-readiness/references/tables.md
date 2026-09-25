# Readiness tables — referenced from ../SKILL.md

## Default or stop?

Check 4 is where readiness is most often faked. Every ambiguity feels resolvable with a sensible
default, and "sensible default" is the rationalisation that ships the wrong change.

The line is **cost of being wrong**, not confidence:

| Take the default | Stop and ask |
|---|---|
| A reviewer disagreeing costs one comment and a one-line edit | Being wrong means rewriting the change |
| Naming a private helper, ordering independent statements, picking a test's fixture values | Setting a wire contract: an event name, an enum value, a payload key, a URL param |
| Following a convention the repo already applies in three places | Choosing between two conventions the repo uses in different places |
| An internal constant no user sees | Any number a user sees, any threshold that classifies data |
| Anything a `git revert` undoes cleanly | Anything that writes, migrates or backfills stored data |

Two defaults stacked are not a default. If resolving one ambiguity requires resolving another,
that is a stop.

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

## Rationalizations for shipping anyway

These are the arguments that actually get made, in the words they get made in. Each is answered.

| Excuse | Reality |
|---|---|
| "A PR is a better question than a card comment — it shows them the rendered number and costs seconds to redirect." | It also merges. A question costs a reply; a wrong user-visible number costs a rewrite and, if it ships, a wrong figure in front of users. The card is the cheap channel precisely because nothing is built yet. |
| "The repo's conventions already answer it." | They answer it where they are unambiguous. If two places in the repo do it differently, the convention is the thing in question — that is check 4 failing, not passing. |
| "It's the cost asymmetry: a stop burns 24 hours, a wrong decimal gets fixed at review." | Correct for a decimal, which is why the default column exists. Run the actual ambiguity through the default-or-stop table instead of applying a decimal's economics to a contract. |
| "The operator said they find trivial questions annoying." | They do. The answer is a question that is one word to answer, not fewer questions. A blocked card is not more annoying than a wrong metric. |
| "I'll list the assumptions prominently in the PR description for them to overturn." | Nobody is there to overturn them before the code is written. An assumption listed in a PR is a decision taken, dressed as a question. |
| "I'll build the unambiguous part and leave the rest." | The mapper has to name a source, so it bakes in the contested decision while shipping nothing visible. Same delay, plus dead code and an extra review. |
| "The two numbers disagreeing is a reconciliation for later, not a blocker on rendering." | Rendering is what makes the disagreement visible to a user. |

## Common mistakes

| Mistake | Consequence |
|---|---|
| Treating "an engineer could figure it out" as ready | The unattended run stops, or guesses |
| Resolving an ambiguity with a default that sets a wire contract | A dashboard or a consuming repo breaks on rename |
| Asking questions with no proposed answers | Cards sit in `Blocked` for days |
| Accepting a prose dependency | The run starts before its blocker exists and builds on nothing |
| One card for backend + frontend | Hidden deploy ordering, surfaced as a broken release |
| "Verify on staging" as the whole verification plan | The agent has no way to prove the change and stops at QA |
