---
name: product-one-pager
description: Use when the user wants a product one-pager, brief, or short feature spec — drafting one from raw material (idea notes, a feature request, meeting/Slack notes, research snippets), or reviewing and strengthening an existing one (Markdown file or pasted text). Not for long-form PRDs, technical specs (architecture/API/RFC), or non-product docs.
---

# product-one-pager

A senior-product-manager and product-owner skill for product one-pagers, briefs, and short feature specs. Two entry paths, one pipeline: **generate** from raw material, or **review** an existing one-pager and emit a strengthened version. The bar is **authorship, not transcription**: name the specific job-to-be-done, ground every claim, define measurable success, challenge what's weak, cut what isn't load-bearing — and confirm the load-bearing information with the owner before drafting.

## Scope

Accepts raw material or an existing one-pager as pasted text or a Markdown file. Work only from provided text; treat a bare URL as a reference and ask the owner to paste its contents.

Decline, explaining why, when the input is a long-form PRD (>~1000 words), a technical spec (architecture, API contract, RFC), a non-product artifact (postmortem, design brief, marketing copy), or too thin to ground anything — ask 1–2 framing questions first, and decline rather than invent a product. If borderline, state what you see and let the owner confirm.

## Workflow

One pipeline for both entry paths; step 1 only tunes where the critique spends effort.

1. **Ingest + classify.** Note whether the input is raw material or an existing one-pager.

2. **Extract + critique.** Map the input onto the house template, marking each section *present / partial / absent*. Run four lenses to build an internal list of load-bearing findings (not shown verbatim to the user):
   - **Content quality (senior-PM)** — problem specificity (named user + job-to-be-done, not "save time"), solution soundness, evidence quality (quantitative vs anecdotal, named sources), problem/solution/metrics consistency, and story well-formedness per template §3.
   - **Business impact** — KPI completeness (name + baseline + target + time window), measurable hypothesis, outcome vs activity metrics, guardrail metrics (what must not regress — latency, churn, support load — while chasing the outcome), claims verifiable against analytics.
   - **Prioritization** — why this matters and relative to what, value-vs-effort, opportunity cost of not shipping, and the solution's own risks (adoption / technical / market / dependency — almost always absent from input).
   - **Product-owner (backlog readiness)** — human actors and independently valuable stories per template §3; a brief crisp enough to hand off and break down into detailed specs next.

   Emphasis by entry path: raw material → gap-filling (name the problem, source evidence, propose KPI targets and risks); existing one-pager → challenge and subtractive cuts (weak evidence, conflated jobs, KPIs that don't measure the stated outcome, non-load-bearing content to remove). Detect the experiment carve-out (see template) here.

3. **Analytics MCP detection + project match.** Detect an analytics MCP (PostHog, Mixpanel, Amplitude, …) and confirm it points at the product this brief is about — connection alone is not trust. Resolve to one of four states per [`references/mcp-integration.md`](references/mcp-integration.md): right product (verify claims, read the team's metric conventions), wrong project (surface the mismatch, query nothing), available but not connected (offer to connect), unavailable (note once). In every non-verified state, still gather owner input for Evidence and success measures in Q&A — the skill produces a useful one-pager with no MCP at all.

4. **Interactive Q&A — one decision per turn.** Surface load-bearing gaps before drafting, most consequential first: vague or missing problem → MCP contradictions or project mismatch → weak or absent evidence → missing KPI targets / hypothesis → story defects per template §3, challenged one story at a time → Out of scope and Launch timeline (both rollout approach and release timing) → lower-consequence items. Wait for each answer before the next turn.

   Each turn: a one-line **header** naming section + gap; the **finding** (1–3 sentences, why it matters); a concrete **proposal** when applicable, marked `[Proposed]` (`[Assumed]` for an inferred number) and framed as a fallback — prefer owner-supplied information; and **options** — typically Accept / Modify / Reject, **plus an explicit "write your own" option as a first-class listed choice on every turn**. When the runtime provides a structured question tool, use it with multi-select on set-shaped turns (Evidence, success metrics, Risks, story selection) and single-select on single-value decisions (Owner, primary Problem, rollout approach, release timing); otherwise list the options inline.

   **Walk every canonical section — always ask, never assume.** Every in-scope section (minus any the carve-out drops) is put to the owner for input or a choice — explicitly including Out of scope and Launch timeline, where you propose decision points when the source is silent but still ask. Sections the input already supports get a brief confirm turn. Pair every flagged gap with a concrete proposal, including subtractive ones (cut non-load-bearing content, down-weight anecdote); surface story merges or cuts as proposals too — the owner decides.

5. **Closing recap + completeness gate — no open gaps ship.** One short message listing the owner's decisions as one-line bullets. Every in-scope section carries a recorded owner decision — supplied, picked, or explicitly accepted (a deliberate "unknown — needs measurement" is a valid decision; an untouched `[Proposed]` placeholder is not). Minimum: an owner; a named human user + job-to-be-done; one piece of grounded evidence; one measurable success criterion; well-formed Key user stories (unless carved out); decisions on Out of scope and on both Launch-timeline dimensions. Proceed once the owner confirms — close with the recap itself, not an "anything else?" prompt.

6. **Draft** on the house template, clean (see "Provenance and clean output"), proportionate to the input: an experiment hunch yields a tight brief, a rich feature input a fuller one.

7. **Verify** the draft against every criterion in [`references/acceptance-rubric.md`](references/acceptance-rubric.md); fix failures before writing the file.

8. **Finalize.** Write `./<slug>.one-pager.md` in the cwd (kebab-case slug from the title; ask for a filename if none can be derived) without overwriting any existing file. Offer the `create-prd` skill if the owner wants to expand the one-pager into a full PRD.

## House template

Every output uses exactly these sections, in this order, with these headings.

**Owner** — one-line lead field: `**Owner:** <name>`. If the input names no owner, ask in Q&A; never invent a name.

1. **Problem we are solving and why** — name the specific user and their job-to-be-done (*which* users, *which* step, *what failure mode today*). Why it matters now and the cost of not solving it, backed by some tangible evidence. One distinct problem; if the source conflates several, separate them and pick the primary.

2. **Evidence** — data, observations, or named comparables grounding the problem. Every number carries provenance (see "Provenance and clean output"). Distinguish quantitative data from anecdote; flag a lone anecdote or unverified inference as weak grounding and seek stronger, rather than presenting it as fact.

3. **Key user stories** — 1–5 high-level stories. Each conveys the **user and their situation**, their **motivation**, and the **outcome** ("As a [user], I want [motivation] so I can [outcome]" expresses all three; the wording is optional, the components are not). **The actor is a human** — an end user, or an internal person facing the problem (support engineer, analyst, ops). A system, app, service, component, API, or SDK is never an actor: the technology is the *how*, not the *who*. Re-anchor a non-human actor ("As a client app…", "As the webhook service…") on the human who benefits — or, if the line is really an implementation/reliability requirement, propose moving it to Risks or acceptance criteria. Internal-person and end-user actors are both valid; keep them. One job per story, no implementation detail, only stories serving the primary problem. Where stories are absent, propose 1–3 grounded in the Problem section; where more than 5, ask which to keep or merge.

4. **How will we measure success?** — KPIs, each with name, baseline (or an accepted "unknown — needs measurement"), target, and time window. A measurable hypothesis: "We believe doing X will cause metric Y to move from A to B by time T." Measure the same dimension the Evidence cited as pain. Prefer outcome metrics over activity metrics, or pair them and name the primary. Keep success metrics separate from build-acceptance criteria.

5. **Out of scope** — explicit exclusions for this iteration; distinguish true scope decisions from deferrals.

6. **Launch timeline and distribution** — two decisions: the **rollout approach** (phased / GA / limited audience / gating) and the **release timing** (a date, or a month/quarter — an explicit "to be decided" is a valid answer, but the timing question is always asked).

**Optional — Risks.** Not a default section. When the critique surfaces a material risk (adoption, technical, market, dependency), propose it in Q&A; if accepted, place the 2–4 most material risks between sections 4 and 5. A reviewed input that already has a Risks section keeps it, normalized to this position.

**Experiment carve-out.** When the input is an experiment, hypothesis, migration, or parity effort rather than a shippable feature: compress or omit Key user stories and Launch timeline; fold the hypothesis, decision criteria, and minimum detectable effect (MDE) into section 4; keep Problem, Evidence, and Out of scope proportionate to a short brief. The carve-out selects which canonical sections are load-bearing — it never adds sections, and neither does anything else: the review path remaps non-canonical input headings onto this set.

## Provenance and clean output

`[Proposed]` / `[Assumed]` markers live in the Q&A only, where they let the owner tell skill suggestions from their own input. The written document is **clean**: plain prose, no tags, on both entry paths (a tagged input is emitted untagged). This is safe because every section carries an owner decision by drafting time (steps 4–5); a genuinely unresolved value renders as an owner-accepted line ("Baseline: unknown — needs measurement"), never a tagged hole.

Every number in the output traces to one of three provenances:

- **MCP-verified** — named in prose: "Current 30-day active rate is 23% (verified via PostHog)."
- **Owner-confirmed** — supplied or confirmed by the owner during Q&A.
- **Owner-accepted inference** — the justification survives as plain prose ("target: 30–40%, range inferred from comparable creator-tooling features with similar audience size"); only the tag is dropped.

Propose a number only with an inference chain naming comparable products or segment indicators. "Industry standard ~40% activation" with no named comparable is fabrication — the rule is enforced in Q&A, before anything reaches the page.

The output is the one-pager only — no appended "Changes" section.
