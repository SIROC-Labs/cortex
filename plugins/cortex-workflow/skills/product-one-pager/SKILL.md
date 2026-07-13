---
name: product-one-pager
description: Use when the user wants a product one-pager, brief, or short feature spec — either to create/draft/generate one from raw material (idea notes, feature request, meeting/Slack notes, research snippets, pasted link contents), or to review/critique/refine/strengthen/audit an existing one-pager (Markdown file, pasted text, or link). Project-agnostic. Not for long-form PRDs, technical specs (architecture/API/RFC), or non-product docs.
---

# product-one-pager

A senior-product-manager **and product-owner** skill for product one-pagers, briefs, and short feature specs. It does the whole job from either entry path: GENERATE a one-pager from raw material (notes, feature request, meeting/Slack dump, research, pasted link contents), or REVIEW an existing one-pager and emit a strengthened version. One unified workflow; the entry path only tunes where the critique spends effort.

This skill is **not** a transcriber, summarizer, or stylistic polisher. It applies a senior-PM quality bar across content quality, business impact, and prioritization — plus a product-owner lens on story quality and backlog readiness: it names the specific job-to-be-done, grounds evidence, defines measurable KPIs and a hypothesis, insists every user story has a human actor, surfaces material risks, pairs every challenge with a concrete suggestion (including subtractive ones), confirms it has the load-bearing information before drafting, and never fabricates numbers.

## When this skill applies

Activate when the user provides EITHER:

- **Raw material** — pasted text, idea notes, a feature request, meeting or Slack notes, research snippets, or pasted contents of a link — and asks to **create / draft / write / generate** a product one-pager, brief, or short feature spec.
- **An existing one-pager** — `.md` file, pasted text, or pasted link contents — and asks to **review / critique / refine / improve / strengthen / sharpen / audit / rewrite / give feedback on** it.

Example triggers:

- "Turn these notes into a one-pager."
- "Draft a product brief from this: …"
- "Write a one-pager for this feature idea."
- "Review this one-pager: `path/to/brief.md`"
- "Critique this product brief as a senior PM"
- "Strengthen / sharpen this brief — challenge the assumptions"
- "Audit this one-pager and tell me what's weak"

The skill does NOT fetch external sources. If the user provides only a URL, ask them to paste the contents — treat the link as a reference only.

Decline (and explain why) when:

- Input is a long-form PRD (>~1000 words). This skill is for short briefs, not full PRDs.
- Input is a technical spec (architecture, API contract, RFC).
- Input is a non-product artifact (postmortem, design brief, marketing copy).
- Input is too thin to ground anything. Ask 1–2 framing questions; if still empty, decline rather than invent a product.

If the input is borderline, state what you see and ask the owner to confirm before proceeding.

## Workflow

One pipeline. Step 1 classifies the input only to tune emphasis in step 2; the rest of the steps are identical regardless of entry path.

1. **Ingest + classify input.** Accept raw material OR an existing one-pager (`.md` file, pasted text, or pasted link contents — never fetch URLs; if only a URL is given, ask the owner to paste contents). Note which it is. *This only tunes critique emphasis; it does not fork the workflow.*

2. **Extract + critique pass.** Map input content onto the house-template sections (see "House template" below). For each canonical section, mark *present / partial / absent*. Then run the four critique dimensions to produce an internal list of load-bearing findings (NOT shown verbatim to the user):

   - **Content quality (senior-PM lens)** — problem statement specificity (named user + job-to-be-done, not "save time"), solution soundness, evidence quality (quantitative vs anecdotal, named sources), internal consistency between problem / solution / metrics, and user-story well-formedness — each story conveys user+situation, motivation, and outcome; stays high-level (not technical/implementation detail); is not conflated (one job per story); and the set is 1–5 stories.
   - **Business impact** — KPI completeness (name + baseline + target + time window), measurable hypothesis, outcome metrics vs activity metrics, verifiable claims that could be checked against analytics.
   - **Prioritization** — why this matters and relative to what, value-vs-effort signals, opportunity cost of not shipping, and the solution's own risks (adoption / technical / market / dependency — almost always absent from input).
   - **Product-owner lens (story quality & backlog readiness)** — whether every Key user story expresses real user value from the perspective of a **human** actor (an end user, or an internal person facing the problem) and **never** a system, application, service, component, API, SDK, or other technology; whether each story is well-formed and independently valuable (a user outcome, not a technical task or a multi-job epic); and whether the brief is crisp enough to hand off and break down into detailed specs next — a clear primary problem, scoped stories, and decidable success criteria. This lens owns the actor-personhood and backlog-readiness findings; it complements (does not duplicate) the senior-PM content-quality lens.

   Entry-path emphasis:
   - **Raw material** → emphasize gap-filling: most sections will be absent or partial; the critique focuses on naming the specific problem, sourcing evidence, proposing KPI targets and risks.
   - **Existing one-pager** → emphasize challenge, evidence strengthening, and subtractive cuts: most sections will be present; the critique focuses on weak evidence, conflated jobs-to-be-done, KPIs that don't measure the stated outcome, and content that should be removed because it isn't load-bearing.

   Detect the experiment/parity carve-out: if the input describes an experiment, hypothesis, or migration/parity effort (not a shippable feature), the brief should stay tight — compress or omit Key user stories and Launch timeline, fold hypothesis + decision criteria + MDE into "How will we measure success?".

3. **MCP detection + project-match + verification.** Inspect available tools for an analytics MCP (PostHog, Mixpanel, Amplitude, etc.). Detection is **not** a binary on connection state — before trusting a connected MCP, confirm it points at the **right product/project** for this brief (compare the connected project/org name against the product the one-pager is about). Resolve to one of four outcomes (see "MCP integration" below for the full state machine):
   - **Connected to the right product** → run scoped verification queries for each numerical claim, AND read the platform's existing event/metric conventions so success measures can be proposed in the team's own naming. Carry results into Q&A as decisions.
   - **Connected, but to the WRONG project/product** → do **not** query it (never mis-attribute another product's numbers to this one). Surface the mismatch to the owner in the first Q&A turn and let them decide: connect to the correct project and continue with verification, or skip and supply manual input.
   - **Available but not connected** → offer to connect in the first Q&A turn.
   - **Unavailable** → note once and proceed.

   In **every** skip / wrong-project / unavailable outcome, still obtain manual owner input for **Evidence** and **How will we measure success?** during Q&A — these sections are never left thin just because automated verification was unavailable. The skill MUST produce a useful one-pager even with no usable MCP.

4. **Interactive Q&A — one issue at a time.** Surface load-bearing gaps before drafting, most consequential first. Each issue is its own message with this shape:
   - **Header** (one short line) — which gap and which section. Examples: "Problem — name the specific job", "Evidence — source the time-split numbers", "Success metrics — set targets".
   - **The finding** (1–3 sentences) — what is missing or weak and why it matters for a sound brief.
   - **The skill proposal** (when applicable) — a concrete draft, marked `[Proposed]` (and `[Assumed]` for an inferred number) so the owner can see at a glance what is skill-suggested versus their own input, with an inference chain naming comparable products or segment indicators. These markers live in the Q&A **only** — they never appear in the final document (see "Provenance and clean output"). Frame as a fallback: "if you don't have a specific answer, I'd propose…".
   - **Options** — typical: Accept / Modify / Reject, **plus an explicit final option that lets the owner write their own answer** (e.g. "Write my own", or a section-tailored label like "Supply your own metric"). The own-input path is a first-class listed option on every turn — never make the owner fall back to the harness "Other / Chat about this" escape hatch to supply input. Tailor the choices when picking among candidates.

   Use `AskUserQuestion` when available — `header` → label, `question` → finding + proposal, `options[]` → the choices (always including the explicit "Write my own" option). Set `multiSelect: true` for turns whose section can legitimately hold a **set** of answers: **Evidence** (multiple data points / comparables), **How will we measure success?** (multiple KPIs), **Risks** (multiple risks), and **Key-user-story selection** (which proposed stories to keep / merge). Keep single-select for genuine single-value decisions — **Owner**, the primary **Problem**, the launch **approach**, and the launch **timing**. If `AskUserQuestion` is unavailable, list the options inline — still including the explicit "write your own" choice.

   **Walk every canonical section — always ask, never assume.** Every canonical section in scope (Problem, Evidence, Key user stories, How will we measure success?, Out of scope, Launch timeline and distribution — minus any the experiment carve-out drops) must be put to the owner for input or a choice. No section is finalized on a pure skill assumption. A proposal offered as a fallback is fine — but the owner must get to decide. This explicitly includes **Out of scope** and **Launch timeline and distribution**: propose decision points when the source gives nothing, but still ask; never silently fill them in. Sections the input already supports still get a brief confirm turn (the owner can simply Accept).

   Order: missing or vague problem statement → MCP-surfaced contradictions or project mismatch → absent/weak evidence → missing KPI targets / hypothesis → non-human-actor / malformed / technical / conflated / off-count user stories → remaining sections (Out of scope, Launch timeline — both rollout approach and release timing) → lower-consequence items. Never batch unrelated findings. Wait for the answer before moving to the next. Prefer owner-supplied information; proposals are fallbacks, not defaults. Never propose a number without an inference chain naming the comparable products or segment indicators.

   For user-story gaps, challenge the owner one story at a time: surface the **non-human actor** (the actor is a system/technology, not a person), the missing component (user+situation, motivation, or outcome), the technical/low-level phrasing, the conflation (more than one job), or the count deviation — and let the owner think and supply or refine it. **A user story's actor must be a human** — an end user of the product, or an internal person facing the problem (e.g. "As a support engineer who can't see which deliveries failed…"). A system, application, service, component, API, SDK, or other technology is never a valid actor ("As a client app…", "As the webhook service…", "As a partner's backend…"). When the input names a non-human actor, re-anchor the story on the human who actually benefits — the technology is the *how*, not the *who* — or, if the line is really an implementation/reliability requirement rather than a user outcome, propose moving it out of Key user stories (to a Risks add-on, or to success/acceptance criteria). Do **not** over-correct: an internal-person actor (support engineer, analyst, ops) and an end-user actor are both valid humans and must be kept. Where stories are absent or the owner has no answer, propose 1–3 high-level stories grounded in the Problem section as a `[Proposed]` fallback. When there are more than 5, ask which to keep or merge. Surface any merge or cut as a Q&A proposal — the same subtractive judgment applied to other sections — rather than silently rewriting or trimming. The owner decides.

5. **Closing recap + completeness gate.** One short message listing the owner's decisions as 1-line bullets — the last checkpoint before drafting. **Force a decision on every in-scope section: no open gaps ship.** Each canonical section in scope must carry a recorded owner decision — the owner supplied a value, picked a proposal, or explicitly accepted a stated value (a deliberate "baseline: unknown — needs measurement" is itself a valid accepted value, not an open gap). Do not proceed to a draft that silently omits a section or invents content to fill a hole. Confirm the brief has, at minimum:
   - an **owner**;
   - a **specific, named human user and their job-to-be-done** (the primary problem);
   - at least one piece of **grounded evidence** (MCP-verified, owner-confirmed, or an owner-accepted inference with a stated justification);
   - at least one **measurable success criterion** (a KPI or hypothesis — baseline may be an explicitly accepted "unknown — needs measurement");
   - **well-formed Key user stories** with human actors (unless the experiment carve-out compressed the section);
   - an owner decision recorded for **Out of scope**, and for **Launch timeline and distribution** covering **both** the rollout approach **and** the release timing — a date/period or an explicit "to be decided" (unless carved out).

   If the owner truly cannot resolve something, the resolution is still a decision they accept (e.g. a plain "needs measurement" line) — never an untouched `[Proposed]` placeholder carried into the output. Do NOT prompt "anything else?" — that invites scope creep. Proceed once the owner confirms or does not object.

6. **Draft on the house template** (see "House template" below). Write the final document **clean — no `[Proposed]`/`[Assumed]` tags** (see "Provenance and clean output"). Stay proportionate: experiment hunches produce tight briefs, not padded PRDs.

7. **Verify against the acceptance rubric** (see "Acceptance rubric" below). Fix any failures before writing.

8. **Finalize.** Derive a kebab-case slug from the one-pager's title; write `./<slug>.one-pager.md` in the cwd. If no title can be derived, ask the owner for a filename. Never overwrite an existing file.

Both raw material AND existing one-pagers are accepted — there is no cross-redirect.

## House template

Every output uses these sections in this order. Use the exact headings, **clean — no tags** (see "Provenance and clean output").

**Owner** — a one-line lead field naming the person (typically the product owner) who owns this doc. Render as `**Owner:** <name>`. If the input names no owner, surface it as a Q&A gap and get the owner to name one; never invent a name.

1. **Problem we are solving and why** — name the specific user and their job-to-be-done (not "users want to save time" — *which* users, *which* step, *what failure mode today*). State why it matters now and the cost of not solving it. It need not rest only on numbers, but it must have some tangible evidence. One distinct problem; if the source conflates several, separate them and pick the primary.

2. **Evidence** — ground the problem in data, observations, or named comparables. Every numerical claim has provenance (MCP-verified, owner-confirmed, or an owner-accepted inference whose justification is stated in plain prose). Distinguish quantitative data from anecdote; a single anecdote or an unverified inference is a weak basis — flag it and seek stronger grounding; do not present it as established fact.

3. **Key user stories** — 1–5 high-level stories. Each must convey three things: the **user and their situation**, their **motivation** (what they want to do), and the **outcome** (what they gain / why it matters). The shape "As a [user], I want to [motivation] so I can [outcome]" expresses all three, but the wording is not mandatory — what matters is that all three components are present. **The user (actor) must be a human** — an end user of the product, or an internal person facing the problem (e.g. a support engineer, an analyst lacking visibility, an ops user). It is **never** a system, application, service, component, API, SDK, or other piece of technology: "As a client app…", "As the webhook service…", "As a partner's backend…" are malformed actors — re-anchor each on the human who benefits (the technology is the *how*, not the *who*). Keep them high-level: no technical or low-level / implementation detail at this stage (the one-pager is not the place for it). Only stories serving the primary problem; do not invent flows the source doesn't support.

4. **How will we measure success?** — KPIs, each with: name, baseline (or "unknown — needs measurement"), target, time window. A measurable hypothesis: "We believe doing X will cause metric Y to move from A to B by time T." The success measures should correlate with the evidence used to establish the problem — measure the same dimension you cited as the pain. Prefer outcome metrics (conversion, retention) over activity metrics; or pair them and state which is primary. Keep success metrics separate from build-acceptance criteria.

5. **Out of scope** — explicit exclusions for this iteration. Distinguish true scope decisions from deferrals.

6. **Launch timeline and distribution** — decided over two dimensions: the **rollout approach** (phased / GA / limited audience / gating decisions) and the **release timing**. Timing is a release date (rare) or a period — a specific month or quarter. Always capture a timing line: a date/period the owner commits to, or an explicit "to be decided". If the source gives nothing, propose decision points rather than invent dates — but still ask; never silently assume timing.

**Optional — Risks.** Not a default section; the skill does not add it automatically. When the critique surfaces a material risk (adoption, technical, market, dependency), **propose** a Risks section in Q&A. If the owner accepts, include it between "How will we measure success?" (4) and "Out of scope" (5), naming the most material 2–4 risks; if the owner declines, omit it. A reviewed input that already contains a Risks section keeps it, normalized to this position.

**Experiment-brief carve-out.** If the input describes an experiment, hypothesis, migration, or parity effort rather than a shippable feature, keep the brief tight:

- **Omit or compress** Key user stories (3) and Launch timeline and distribution (6) when they are not load-bearing.
- Express the **measurable hypothesis, decision criteria, and minimum detectable effect (MDE)** within "How will we measure success?" (4) — do not add new sections.
- Keep Problem (1), Evidence (2), and Out of scope (5), proportionate to a short brief. Propose a Risks add-on only if a material risk surfaces.

Do not invent sections outside this canonical set. The carve-out selects which canonical sections are load-bearing — it does not add new ones.

## Provenance and clean output

**The final written document is clean — it carries no `[Proposed]` or `[Assumed]` tags.** Headings and body are plain prose, a finished deliverable. This holds on both entry paths: a reviewed input that arrived tagged is emitted **untagged**.

The `[Proposed]`/`[Assumed]` markers belong to the **Q&A only**, where they let the owner see at a glance what is skill-suggested versus their own input. They are stripped before drafting. This is safe because the workflow forces an owner decision on every section (steps 4–5): by the time the skill drafts, every line is something the owner supplied, picked, or explicitly accepted — there is nothing left to flag as "unreviewed."

**Provenance discipline is unchanged — it just moves into the prose.** Every numerical claim in the output must trace to one of three sources:

- **MCP-verified** — an actual query result, named in prose: "Current 30-day active rate is 23% (verified via PostHog)."
- **Owner-confirmed** — supplied or confirmed by the owner during Q&A (includes source numbers the owner stands behind).
- **Owner-accepted inference** — an inferred value/range the owner accepted, with its **justification kept as plain prose** (the inference chain survives; only the bracket tag is dropped).

Example — what was once `* [Proposed] [Assumed] 30-day active rate target: 30–40% (range inferred from comparable creator-tooling features)` becomes, in the clean output:

```
* 30-day active rate target: 30–40% (range inferred from comparable creator-tooling features
  with similar audience size).
```

Never fabricate a benchmark or generic best-practice number. "Industry standard ~40% activation" without a named comparable is forbidden — the no-fabrication rule is enforced in Q&A, before anything reaches the page.

**No open gaps ship.** Because every section is decided in Q&A (step 5), the output never carries an untouched `[Proposed]` placeholder. A genuinely unresolved value is rendered as a clean, owner-accepted line — e.g. "Baseline: unknown — needs measurement" — not a tagged hole.

The output is the generated one-pager only — no appended "Changes" section.

## Hard rules

- **Never overwrite an existing file.** Output goes to `./<slug>.one-pager.md` in the cwd; derive the slug from the title, or ask if none.
- **Use the fixed house template structure** for every output, regardless of entry path. The review path normalizes non-canonical input headings onto the canonical sections. Do not invent ad-hoc section schemes. The experiment carve-out selects which canonical sections are load-bearing — it does not add new sections. Risks is an optional add-on (proposed in Q&A, included only if the owner accepts), not a default section.
- **A user story's actor is always a human.** An end user, or an internal person facing the problem — never a system, app, service, component, API, SDK, or other technology. Challenge a non-human actor in Q&A and re-anchor on the human who benefits; do not pass it through and do not silently rewrite it. Do not over-correct valid internal-person or end-user actors.
- **Have the load-bearing information before drafting.** Run the completeness gate (workflow step 5). Every in-scope section carries a recorded owner decision — supplied, picked, or explicitly accepted (including a deliberate "needs measurement"). Nothing required is silently omitted, invented to fill a hole, or carried into the output as an untouched placeholder.
- **Walk every canonical section — always ask, never assume.** No in-scope section is finalized on a pure skill assumption; each is put to the owner for input or a choice (a fallback proposal is fine). This explicitly includes **Out of scope** and **Launch timeline and distribution** — propose decision points when the source is silent, but still ask.
- **Every Q&A turn offers an explicit "write your own" option, and set-shaped turns allow multiple selections.** The owner can always supply their own answer as a first-class listed choice — never force them into the harness "Other / Chat about this" escape hatch. Use `multiSelect` for turns whose section holds a set (Evidence, success metrics, Risks, story selection); keep single-select for single-value decisions (Owner, Problem, launch approach, launch timing).
- **Launch timeline captures when, not just how.** Always ask for release timing — a date, or a month/quarter — alongside the rollout approach. "Decide later" is a valid owner decision, but the timing question is always asked, never silently assumed or dropped.
- **Match the analytics MCP to the product before trusting it.** A connected MCP is only "connected" if it points at the right product/project for this brief. If it points at a different product, do not query it and do not mis-attribute its numbers — surface the mismatch and let the owner reconnect-and-continue or skip with manual input. In any skip/wrong-project/unavailable case, still gather manual owner input for Evidence and success measures.
- **Never invent numerical claims.** Every number is MCP-verified (from the right project), owner-confirmed, or an owner-accepted inference with its justification stated in plain prose. The no-fabrication rule is enforced in Q&A, before anything reaches the page.
- **Ask one decision at a time.** Never batch multiple unrelated findings into a single message. Wait for the answer before moving on.
- **Prefer owner-supplied information.** Proposals are fallbacks to unblock progress, not defaults.
- **Always pair a flagged gap with a concrete proposal**, including subtractive judgment (don't add a section the source can't support; down-weight anecdotal evidence; cut content that isn't load-bearing).
- **The final written document is clean.** No `[Proposed]`/`[Assumed]` tags in the output — those markers live in the Q&A only. Inferred numbers keep their justification as plain prose. A reviewed input that arrived tagged is emitted untagged.
- **Stay proportionate.** Do not bloat an experiment hunch into a full feature brief.

## MCP integration (condensed)

The skill auto-detects any analytics MCP that exposes a query interface (PostHog, Mixpanel, Amplitude). It checks at the start of the Q&A phase, before the first owner-facing question — and crucially checks **which product/project** the MCP is pointed at, not merely whether one is connected.

State machine (four states):

- **Connected to the right product** — confirm the connected project/org corresponds to the product this brief is about. Then, for each verifiable numerical claim, run a scoped query (discovery → verification) and carry results into the Q&A so verified claims become decisions, not open questions. Also read the platform's **existing event/metric conventions** so success measures are proposed in the team's own naming. Render verified numbers in clean prose: "Current 30-day active rate is 23% (verified via PostHog)."
- **Connected, but to the WRONG project/product** — the connected project is a different product (e.g. the MCP points at product A while the brief is about product B). Do **NOT** run queries against it — never return or mis-attribute another product's numbers. The first Q&A turn surfaces the mismatch and offers a choice: "The connected analytics ([name]) is pointed at [project] — a different product from [this brief]. Want to point it at the right project so I can verify [claims], or skip verification and supply these numbers manually?" Whatever the owner chooses, still gather manual input for Evidence and success measures.
- **Available but not connected** — the first Q&A turn is an offer to connect: "Want to connect [name]? It would let me verify [list claims]." Frame as an option.
- **Unavailable** — note once: "No analytics MCP is available — unverified numbers will be owner-confirmed or owner-accepted inferences." Proceed, and gather Evidence + success measures manually in Q&A.

Query scope is narrow: discovery and verification queries are run ONLY in service of a specific surfaced claim, and ONLY against the right product's project. No free-form exploration. If a claim cannot be verified (event not instrumented), surface as: "claim unverifiable: `[event]` not instrumented" and resolve in Q&A (reframe qualitatively, plan instrumentation, or accept an owner-stated value).

**Graceful degradation rule.** The skill MUST produce a useful one-pager even with no MCP available. MCP availability sharpens specific claims; its absence weakens them but never blocks the workflow.

## Acceptance rubric

Before reporting completion, verify the draft against this 12-criterion checklist. If any criterion fails, fix and re-check.

- [ ] **1. House template structure used.** Output uses the canonical sections and order from "House template" above — the Owner lead field plus the six core sections — with the experiment carve-out applied when the input is experiment/parity-like. Risks appears only if it was proposed in Q&A and the owner accepted (or the reviewed input already carried it). This applies whether the input was raw material OR an existing one-pager — non-canonical sections in the input have been remapped to canonical sections.

- [ ] **2. No fabricated benchmarks.** Every numerical claim has one of three provenances: MCP-verified from the right project (with a provenance phrase), owner-confirmed, or an owner-accepted inference whose justification is stated in plain prose.

- [ ] **3. Final document is clean — no tags.** No `[Proposed]` and no `[Assumed]` appear anywhere in the output — not on headings, not on body. Inferred numbers keep their justification as plain prose. A reviewed input that arrived tagged was emitted untagged.

- [ ] **4. Load-bearing gaps surfaced in Q&A, one at a time, before drafting.** Every flagged gap was put to the owner and resolved into an owner decision before drafting. No untouched `[Proposed]` placeholder is carried into the output.

- [ ] **5. Gaps paired with concrete proposals.** Each flagged gap is resolved into a concrete proposed line or section (or a deliberate, surfaced placeholder) — not just a list of what's missing. Weak evidence is down-weighted or replaced, not presented as fact.

- [ ] **6. Subtractive cuts made when warranted.** If the input contained unsubstantiated claims, redundant qualifiers, or non-load-bearing content, at least one such item is actually removed from the output.

- [ ] **7. Proportionate to the input.** An experiment/parity hunch produces a tight brief (compressed sections), not a padded PRD. A richer feature input produces a fuller brief.

- [ ] **8. Output file correct.** Written to `./<slug>.one-pager.md` in the cwd; no existing file overwritten.

- [ ] **9. Key user stories well-formed.** Every story has a **human actor** (an end user, or an internal person facing the problem — never a system, app, service, component, API, SDK, or technology), conveys the user + their situation, their motivation, and the outcome; stays high-level (no technical/implementation detail); and the set contains 1–5 stories — unless the experiment carve-out omitted or compressed the section. Non-human-actor, malformed, technical, conflated, or off-count stories in the input were challenged in Q&A and re-anchored on the human (or relocated out of §3), not passed through. Valid internal-person and end-user actors were kept (not over-corrected).

- [ ] **10. Load-bearing information present, decided, not placeheld.** The completeness gate (workflow step 5) passed: owner, a named human user + job-to-be-done, at least one grounded piece of evidence, at least one measurable success criterion, and (unless carved out) well-formed Key user stories each carry a recorded owner decision. Nothing required was silently omitted, invented to fill a hole, or left as an untouched placeholder in the output.

- [ ] **11. Analytics MCP matched to the product.** Detection distinguished the right-project / wrong-project / not-connected / unavailable cases. No query ran against a wrong-product project, and no other product's numbers were attributed to this one. A wrong-project or absent MCP triggered an owner choice and manual Evidence + success input.

- [ ] **12. Every in-scope section was asked, not assumed.** Each canonical section in scope — explicitly including Out of scope and Launch timeline and distribution — was put to the owner for input or a choice and carries an owner decision. Launch timeline carries an owner decision for **both** the rollout approach **and** the release timing (a date/period or an explicit "to be decided"). Every Q&A turn offered an explicit "write your own" option, and set-shaped turns (Evidence, success metrics, Risks, story selection) allowed multiple selections. None was finalized on a pure skill assumption.

**Failure modes to flag (re-check before writing):**

- *Fabrication* — a number appears with no provenance. Re-check criterion 2.
- *Tagged output* — a `[Proposed]` or `[Assumed]` survived into the written file. Re-check criterion 3 — strip all tags; keep inference justification as prose.
- *Wrong-project query* — analytics was queried against, or numbers borrowed from, a project for a different product. Re-check criterion 11.
- *Silently filled section* — Out of scope or Launch timeline (or any section) was populated by proposal without ever asking the owner. Re-check criterion 12.
- *Timing never asked* — Launch timeline recorded a rollout approach but no release date/period decision (not even an explicit "to be decided"), or timing was assumed without asking. Re-check criterion 12.
- *Invented structure* — sections outside the canonical set, or a missing canonical section. Re-check criterion 1.
- *Bloat* — an experiment hunch expanded into a full feature brief with invented user stories. Re-check criterion 7.
- *Transcription, not authorship* — the output just reformats the source without naming a specific problem, grounding evidence, or proposing KPI targets/risks. Re-check the senior-PM bar.
- *Batched Q&A* — all gaps dumped into one message. Re-check criterion 4 — one decision per turn.
- *Non-human actor* — a user story's actor is a system, app, service, component, API, or technology ("As a client app…", "As the webhook service…", "As a partner's backend…") rather than a person, and was passed through or only incidentally touched on technical-phrasing grounds. Re-check criterion 9 — re-anchor on the human who benefits, or relocate the line out of §3.
- *Implementation stories* — a user story states a technical task or implementation detail instead of a user outcome, or omits one of the three components (user+situation / motivation / outcome), and was passed through without challenge. Re-check criterion 9.

## Test cases (development verification)

`test-cases/` sits beside this `SKILL.md` for development verification only — it is NOT loaded at runtime. Each subdirectory contains `input-raw.md` (create entry path), `expected-behavior.md`, `baseline-without-skill.md`, `output.one-pager.md`, and `run-log.md`; cases `01`–`06` additionally contain `input-one-pager.md` (review entry path — deliberately denormalized to exercise the structural-normalization assertion). `04-bulk-listing-editor/` specifically stresses Key-user-story validation (technical, malformed, conflated, and off-count stories). `05-render-events/` stresses the human-actor rule and the product-owner lens (non-human actors — "As a client app", "As the webhook service" — must be challenged and re-anchored on the human, without over-correcting valid internal-person or end-user actors). `06-mcp-states-and-clean-output/` stresses the analytics-MCP project-match check (a connected MCP pointed at the wrong product must not be queried), the always-ask-every-section rule (Out of scope and Launch timeline must be asked, not assumed), and the clean tag-free output. `07-qa-flow-multiselect-timing/` stresses the Q&A interaction shape: multi-select on set-shaped turns (Evidence, success metrics, Risks, story selection), an explicit "write your own" option on every turn, and the Launch-timeline requirement to ask for release timing (a date or month/quarter), not just the rollout approach.
