# Authoring references — referenced from ../SKILL.md

## Any input

The input shape changes nothing about the process; it only changes how you enumerate the asks.

| Input | Enumerate by |
|---|---|
| Feedback or review document | Every ask, top to bottom, from the document itself |
| Benchmark or metrics table | Every row, and every metric a row implies |
| Bug report or an error-tracker issue | The reported symptom, then the general case behind it |
| A chat thread or meeting notes | Every decision and every complaint, separated |
| A screenshot or a design | Every state the surface can be in, not just the one pictured |
| A spec or a PRD | Every requirement, plus the ones it assumes silently |
| A one-line idea | The states, the edges and the failure modes it does not mention |

For thin inputs — an idea, a one-liner — the enumeration is mostly interrogation. Use
the `CREATE_PLAN` binding (`plugins/cortex-workflow/references/runtime-bindings.md`) to run it, then come back here.

## Before planning anything: four verifications

**1. Data feasibility, per metric.** For every number the input wants shown, find where it comes from. A
field existing is not the same as a field populated and exposed.

> A benchmark table asked for shop conversion rate. The field existed — `views: int | None = 0  # TODO:
> implement time based views`. Nine of nineteen requested metrics turned out to be unbuildable. Planning
> them would have burned a sprint.

**2. Internal contradictions.** Long inputs contradict themselves. Find the conflict and resolve it
explicitly instead of implementing both.

> One row called 3x ROAS "good"; another called a 33% ad-spend share "needs attention". They are the
> same measurement inverted.

**3. Symptom vs. general case.** An item usually reports the one instance the author hit. Ask what the
general form is, and scope both.

> "It couldn't tell me my ad spend" was one guarded code path. The general case — most dashboard metrics
> never reach the model at all — was a second, larger task.

**4. Your own exclusion claims.** Before writing "not feasible" anywhere, check it. Reviewers push back
on exclusions, and being wrong there costs credibility.

> Four metrics were dropped as unmeasurable on first pass. On inspection three were measurable; only the
> reasoning was lazy.

## The milestone

One milestone per run, whatever the card count. It is the unit the operator reviews and releases, and the
branch every card of this run targets.

**Branch recipe**, per repository under `repos_root` that the cards touch:

```bash
git -C <repo> fetch origin --prune
git -C <repo> ls-remote --exit-code --heads origin milestone/<slug> \
  || git -C <repo> push origin origin/<parent>:refs/heads/milestone/<slug>
```

`<slug>` is the milestone name lower-cased, non-alphanumerics collapsed to `-`, trimmed; the same in every
repository. `<parent>` is `main` unless the work extends an unmerged branch, and is recorded per
repository. Nothing is committed to the milestone branch here; the review run's squash merges fill it.

**Anchor description** (`set_description`), in this order:

```markdown
## Source
<one paragraph: what the input asked for, and the exclusions with their reasons>

## Branches
| Repository | Milestone branch | Parent |
|---|---|---|
| <org/repo> | `milestone/<slug>` | `<parent>` |

## Cards
- <ref> — <title> (<repo>)   ← in dependency order

## Closing
When every card is in Ready, open `milestone/<slug> → <parent>` in each repository above and review the
milestone as one change. Extending this milestone means authoring new cards under it with the same base.
```

## Common mistakes

| Mistake | Consequence |
|---|---|
| Planning from the summary you wrote | Items lost between reading chunks |
| Trusting "we can't measure that" without a code check | Wrong exclusions in a stakeholder-facing report |
| Implementing both sides of a contradiction | Two features that disagree on screen |
| One card spanning two repositories | Hidden deploy ordering; the run cannot ship both halves |
| Two cards in one repository that depend on each other | Serialised work that one card would have carried; the second waits a review cycle for nothing |
| A card with file-level steps | The run follows a plan written before the code was read, instead of the approach |
| A card whose base is `main` | The review run refuses it; nothing may merge into `main` unreviewed by a human |
| No milestone because "it is just one card" | Nothing to extend; the next card from the same source gets a second branch |
| Leaving a threshold as a word | The run stops and asks, or invents a number |
| Verifying coverage cards-first | Confirms what you wrote, finds nothing missing |
| Calling a data-absent item "declined" | Reads as a judgment on the author's idea |
| Blockers written in prose | The gate does not see them; the run builds on nothing |
| No Verification row, or "check on staging" as the whole one | The agent reaches QA with nothing it can run |
| Creating the card before the readiness gate passes | An hour of queue time spent producing a question |
