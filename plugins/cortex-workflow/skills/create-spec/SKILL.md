---
name: create-spec
version: 0.1.0
description: Produces a technical specification as a markdown document — the layer above feature implementation that captures architecture, data, contracts, behaviors, and testing strategy at the right abstraction level for a later planner to act on. Inputs can be passed as arguments — a PRD path, a task URL, a Notion / Confluence / Drive / Loom / web URL, a Figma URL or local design artifact, a folder path, a plain-text problem statement, or nothing at all (the skill inspects the current working directory). Use this skill whenever the user wants to draft, write, or generate a technical spec — "/create-spec", "/spec-it", "/technical-spec", "/tech-spec", "write a tech spec for this", "draft a tech spec", "we need a spec before we plan this out", "spec this out", or pastes a PRD / ticket / design link and asks for a spec. Also triggers when the user describes a problem in free text and asks for a technical spec. Do NOT trigger on requests to implement a feature, review code, debug, or create tasks — those go to other skills.
---

# Create Spec

Produces a self-contained technical specification as a single markdown file. Follow the seven phases below **in order** — they encode the only way the skill can do its job well.

A technical spec is **not an implementation plan**. It sits one layer above feature implementation: it captures the technical *shape* of the work — architecture, data, contracts, behaviors, testing — at a level of abstraction that lets a separate, later step turn it into a concrete plan with additional decisions of its own.

The goal is **enough information at the right level of abstraction** for that later step to act, not to enumerate every fact and decision. Over-specification is a failure mode: it wastes time, locks in details prematurely, and crowds out the judgment a planning step should bring.

---

## Absolute Rules

1. **Read everything before asking anything — except prior planning docs.** Context discovery is the first job of every run. Exhaust the user-provided inputs and the repo's *current-state* references (source code, `CLAUDE.md` / `AGENTS.md`, ADRs). Do NOT read prior specs, PRDs, or other planning documents in the repo — they may be stale and contaminate the new spec. The user's Phase 1 inputs are authoritative for anything that would otherwise come from a prior plan. See Phase 1 for details.
2. **Treat the interviewee as a technical expert.** They know the stack. Questions are technical — frame choices in terms of trade-offs, not tutorial.
3. **Scale the interview to scope.** A small change gets a small interview and a short spec. A large initiative gets a longer one. Never impose a heavy spec on a light change.
4. **Stay at the spec layer, not the implementation layer.** Every interview question must be one a planner or implementer cannot resolve later from code, framework defaults, or routine engineering judgment. If a question can be answered by the implementer at code-writing time, do not ask it now. The spec captures the *shape* of the work, not the details that follow from the shape.
5. **Discover the undiscovered.** The interview is not a transcription of what the user already knows. Actively probe for edge cases, failure modes, hidden assumptions, rollout considerations, and cross-cutting concerns the user did not raise. The spec must surface what the user did not think to mention — otherwise it inherits the blind spots of the input.
6. **Synthesize and get approval before writing.** After the interview, present a structured synthesis of the strategy (decisions, trade-offs, items surfaced beyond the user's framing, open questions) and wait for explicit user approval. The spec is only written once the user greenlights the synthesis. See Phase 4.
7. **Markdown output only.** The deliverable is the spec file. Never edit application source files, run dev servers, or run build / test commands against the project.
8. **The spec is self-contained.** Never reference the PRD by file path. Where a product rule motivates a technical choice, restate the rule inline.
9. **Stop at the spec hand-off.** Planning the work and building the work are separate, later concerns. Do not propose tickets, build orders, or task assignments.
10. **No placeholders in the final spec.** If something is unknown, ask. Only leave it as an explicit Open Question if the user confirms "not yet decided" after being asked.

---

## Phase 1: Context Discovery

Before anything else, resolve every input and read everything reachable. This is the foundation — every later phase depends on it.

### Source detection

Inspect each argument (or the current working directory if no argument was given) and ingest accordingly:

| Source type | How to detect | How to ingest |
|---|---|---|
| Task in the task manager | URL/id that resolves to a task | Fetch it through the **task manager**: `get_task(task)`, plus `get_subtasks`, `get_comments`, and `get_attachments` as needed |
| Notion page | `notion.so` or `notion.site` in URL | Use Notion MCP |
| Confluence page | `atlassian.net/wiki/` in URL | Use Confluence MCP |
| Google Drive doc | `drive.google.com` or `docs.google.com` in URL | Use Google Drive MCP |
| Figma file or frame | `figma.com` in URL | Use Figma MCP (`get_design_context`, `get_metadata`, `get_screenshot`) |
| Loom video | `loom.com` in URL | WebFetch the page and extract transcript / summary. If nothing usable, ask the user to paste the transcript |
| GitHub issue or PR | `github.com/.../issues/` or `/pull/` in URL | Use `gh issue view` / `gh pr view` |
| Other URL | `http://` or `https://` | WebFetch |
| Local file path | path resolves to a regular file | Read directly (PDF, Markdown, HTML, code) |
| Local folder path | path resolves to a directory | Walk the directory and read all relevant files |
| Free-text seed | non-empty text not matching any rule above | Treat as a problem-statement seed. Ask the user whether to also inspect the current working directory |
| No argument given | — | Inspect the current working directory and read what looks relevant |

To fetch a task, go through the **task manager** interface — resolve the input with `find_task(ref)`, then read it with the neutral operations (`get_task`, `get_subtasks`, `get_comments`, `get_attachments`). Never call a task-tracking provider or its API directly, and never name one in the spec.

If multiple sources are given (e.g. a PRD path + a Figma URL + a task URL), ingest all of them before continuing.

### Then walk the repository

Once the explicit inputs are read, walk the repository for the affected areas. This is where the technical shape lives.

- Read every `CLAUDE.md`, `AGENTS.md`, or equivalent convention file in scope. Start at repo root, then check the directories touched by the work. These are explicitly maintained — safe to read.
- Identify the affected modules / services / components. Read enough source to understand the current architecture in the areas the work will change. Do not read the whole codebase — read what is plausibly touched.
- Architecture decision records (ADRs) or similar dated, current-state decision logs, if the repo has them, are reliable to read. If the repo has no such convention, skip.

### What NOT to read

Do **not** read prior specs, prior PRDs, or other planning documents found in the repo — anywhere under `docs/*/specs/`, `docs/*/product-requirements/`, `specs/`, or sibling planning directories. The user has provided the inputs for this spec explicitly in Phase 1; that set is authoritative.

**Why:** prior planning documents are frequently stale, superseded, or aspirational. They describe what someone *intended* at a moment in time, not what currently holds. Reading them risks importing outdated assumptions or dropped scope into the new spec without you being able to tell which is which. Source code reflects current reality; old planning docs do not.

If something would normally come from a prior spec — an inherited assumption, a stylistic convention, a referenced decision — ask the user for it rather than reading the prior document. The user knows what is still load-bearing.

The output-format reference (`references/output-format.md`) is the canonical convention for this skill's output. Do not look elsewhere for it.

### Follow references

Inputs link to other things. Follow those too:

- A ticket linking to a Figma → fetch the Figma context.
- A PRD linking to a Drive doc or external spec → fetch it.
- A task linking to a Loom → try to extract the transcript.

If important context is **unreachable** (e.g., a private link with no auth, a referenced doc that no longer exists), surface that to the user and ask where to find it. Do not proceed pretending it was read.

---

## Phase 2: Scope Assessment

Once context is loaded, decide the rough scope of the work. Scope drives both the depth of the interview and the length of the resulting spec.

Classify the work as **small**, **medium**, or **large** using these signals — not a checklist, a judgment call:

| Signal | Small | Medium | Large |
|---|---|---|---|
| Surface area | one file or one module | a handful of related modules | multiple subsystems, a new module, or a new service |
| Architecture change | none | local refactor or new pattern in one place | new component, new service boundary, new data flow |
| Data model | unchanged | small schema change | new schema, new entities, or non-trivial migration |
| Contracts | unchanged | one contract changes | new contract or several contracts change |
| Risk | low — easy to revert | moderate — affects a feature | high — affects a product area, or hard to revert |

### Tiny-scope short-circuit

If the work is genuinely sub-spec-sized — a one-line fix, a copy change, a single-property tweak — surface that to the user before starting the interview:

> "Looking at the input, this looks like a [<one-sentence description>] change. A full technical spec might be overkill — I can either skip the spec entirely, or write a short note instead. What do you want?"

Respect the user's answer. If they want no spec, stop and say so. If they want a short note, write a one-paragraph note in the spec output location and stop. Otherwise proceed with the interview at the small-scope depth.

### Tell the user the scope

State the scope read briefly:

> "This looks like a **medium-scope** change — it touches the X module and the Y contract, but doesn't introduce a new service. I'll keep the interview tight and the spec proportional."

This sets expectations and gives the user a chance to push back if your read is off.

---

## Phase 3: Interview (via `superpowers:brainstorming`)

Drive the interview by invoking the `superpowers:brainstorming` skill. It already provides the right mechanic — one question at a time, multiple-choice with a recommended option — and there is no reason to reinvent it.

When invoking brainstorming, frame it as a **technical interview with a technical expert**, and pass through the context already discovered. The interview has two jobs:

1. **Resolve what the user already knows.** Pull out their constraints, preferences, and decisions on the topics this work touches.
2. **Surface what the user has not raised.** The user gives you their framing; the spec needs more. Actively probe for edge cases, failure modes, cross-cutting concerns, rollout considerations, and hidden assumptions that the inputs did not name. A passive transcription of the user's framing produces a spec that misses what the spec is for.

### Keep questions at the spec layer

Every question should pass this test: **would a planner or implementer have to ask this themselves, later, if you didn't ask now?**

- If the answer can be picked at implementation time — from reading existing code, choosing a framework default, following an in-repo convention, or making a routine engineering call — **do not ask now.** The planner is allowed to decide. Over-specification crowds out their judgment.
- If the answer changes the *shape* of the work — what gets built, what contracts emerge, what fails how, where data lives, what is in or out of scope — **ask now.** That shape is what the spec exists to capture.

If a question feels too detailed to be at the spec layer, lift it up: ask the higher-level decision the detail would follow from, and let the implementer pick the detail later.

### What to cover

Use this as the topic universe. Skip topics the work doesn't touch. For each topic, after resolving what the user already knows, ask yourself what they might *not* have mentioned — and probe for that.

- **Problem framing.** The technical problem; the constraint or product rule driving it. (Restate inline — do not reference the PRD by path.)
- **Architecture.** Where the new behavior lives. Whether you're extending an existing pattern or introducing a new one — and why.
- **Data.** What changes in the data model. Ownership and lifecycle.
- **Contracts.** Which API / message / event contracts change. Wire shape, versioning, backwards compatibility.
- **Behavior.** Meaningful states, transitions, and edge cases. The error model.
- **Cross-cutting concerns.** Auth, permissions, observability, performance, accessibility — only the ones this work actually touches. Often the user will not raise these; the interview must.
- **Rollout & migration.** How the change reaches production and how existing state is handled. Often unsaid by the user.
- **Testing strategy.** What kinds of tests, at what boundaries. What fixtures or infrastructure.
- **Risks and non-goals.** What is explicitly out of scope. The biggest risk and its mitigation.
- **Open questions.** What genuinely cannot be answered yet, and who decides.

### When to stop interviewing

Stop when every remaining question is one a planner or implementer could resolve at implementation time. If you find yourself drafting a question about a function signature, a variable name, a library choice with an obvious default, or a routine engineering pattern — that is the line. Skip it.

Also stop when a question would force the user to *invent* an answer rather than recall or judge one. Mark it as an Open Question and move on.

The interview does not produce drafted spec sections — it produces *answers*. Section content is consolidated and reviewed in Phase 4, then written in Phase 5.

---

## Phase 4: Synthesis & Approval

The interview is over. Before writing anything to disk, present a **synthesis of the strategy** to the user and get explicit approval to proceed.

The synthesis is not the spec. It is a structured summary of what the interview produced — the decisions taken, the trade-offs resolved, the items intentionally left open, and the things the skill surfaced that the user did not initially raise. Its job is to let the user see the shape of the proposed spec at a glance and either approve, fine-tune, or challenge it before any prose is written.

### What the synthesis covers

Present this as a single message to the user, with these subsections in order. Skip a subsection when the work does not touch its topic.

- **Scope read.** Small / medium / large, one sentence on the surface area.
- **Architecture direction.** Where the new behavior lives, what pattern it follows, what changes.
- **Data direction.** What the data model gains, loses, or migrates.
- **Contract direction.** Which contracts change, and the versioning approach.
- **Behavior & edge cases.** The error model and the most consequential edge cases the interview resolved.
- **Cross-cutting concerns.** What this work touches in auth, observability, rollout, performance, accessibility.
- **Testing approach.** The kinds of tests, at what boundaries.
- **Risks and non-goals.** The biggest risk + mitigation; what is explicitly out of scope.
- **Items I surfaced that you did not initially raise.** Make this section explicit and call attention to it. List the gaps the interview filled — concerns, edge cases, or constraints that were not in the user's original input. The user should be able to confirm, override, or reject each one. This is where "discover the undiscovered" becomes visible to the user.
- **Open questions.** Items the user explicitly chose not to resolve now.

Keep each subsection tight — bullet points or one or two sentences. The synthesis is for *review*, not for re-running the interview or pre-drafting the spec.

### Approval gate

End the synthesis with an explicit ask:

> "Does this match what you want? Anything to add, change, or push back on before I write the spec?"

Then **wait** for the user's response. Do not write the spec until the user gives an explicit green light.

If the user pushes back, asks for additions, or fine-tunes anything:

- Process the feedback. This may mean revisiting topics in the interview, removing a direction, swapping a choice, or moving an item from "resolved" to "open" (or vice versa).
- Update the synthesis with the changes — show the updated version, not just a diff.
- Ask for approval again.

Iterate this loop until the user explicitly says "go" (or equivalent). Only then proceed to Phase 5.

If the user wants to abandon the spec entirely, stop here.

---

## Phase 5: Write the Spec

Only start writing once the user has explicitly approved the synthesis in Phase 4.

### Output location

Resolve the repo root from `git rev-parse --show-toplevel`. Then:

1. If `<repo-root>/docs/cortex/specs/` exists, write there.
2. Else, if another obvious specs directory exists (look for `docs/specs/`, `specs/`, `docs/<area>/specs/` other than `docs/superpowers/specs/` — that one is reserved for skill-development specs), use the most appropriate match.
3. Else, create `<repo-root>/docs/cortex/specs/` and write there.

### Filename

`YYYY-MM-DD-<title>.md` — all lowercase, hyphen-separated, dated first so listings sort chronologically.

If a file with the same name already exists, append `-v2`, `-v3`, etc. until the name is free.

### Structure

Every spec contains at least the seven sections below. They are the **minimum** — add further sections only when the work genuinely needs them (e.g., contract notes, behavioral state machines, lifecycle rules, error model, fixture conventions, non-goals, open questions). Do not invent new top-level sections without flagging it to the user. Do not pre-populate sections "for completeness" when they have nothing to say — empty ceremony hurts the spec.

```
1. Title & metadata          (author, date, status, version)
2. Summary
3. Technical Context
4. Architecture Notes
5. Data Model Notes          (when the work touches data)
6. Testing Strategy
7. References & Links
```

For a small change the spec may be little more than these sections, each kept short. For a larger initiative the spec may add sections that serve the specific work. The judgment about what to add belongs to the skill at runtime, informed by the interview.

For the detailed formatting conventions (heading levels, link style, table layouts, status values, where each section's content comes from), see `references/output-format.md`.

### Writing rules

- The spec is self-contained. Restate the relevant product rule inline where a technical choice depends on it. Never write "see the PRD" or link to it as the source of truth.
- Describe the technical shape, not a step-by-step plan. Say what the architecture is, not in what order to build it.
- Prefer prose for shape; reach for tables, lists, or diagrams when they are clearly the better representation (contracts, state transitions, data fields).
- Link references with real URLs. If a reference exists but has no URL yet (e.g., designs not started), list it explicitly as "Not yet available" — never omit it.
- Avoid framing as decisions the team has made unless the user confirmed it in the interview. If a question is genuinely open, it goes in Open Questions, not in the architecture section as a fait accompli.

---

## Phase 6: Self-Review Pass

After writing the file, re-read it once with a fresh-eyes checklist and edit inline. This catches the things that are easy to miss on the way in.

Check for:

- **Placeholders.** `TBD`, `TODO`, `XXX`, `???`, `<fill in>`. Each one is either a confirmed Open Question (move it to that section) or a real omission (write the missing content, or ask the user).
- **Internal contradictions.** Two sections say different things about the same fact. Pick the right one and fix the other.
- **Ambiguity.** Sentences a planner would read and ask "what does this actually mean?" Tighten them.
- **Scope creep.** Sections that drifted into implementation detail (e.g., enumerated build steps, ticket-level breakdowns). Lift them back to the abstraction the spec lives at, or remove.
- **PRD path references.** Search the file for the PRD's file path. If it appears anywhere, replace with inline restatement of the rule that motivated the reference.
- **Empty ceremony.** Sections present but saying nothing. Either fill them with substance or remove.
- **Output-format conformance.** Compare against `references/output-format.md`. If a section drifts from the canonical structure (heading levels, required content, optional-section criteria), align.

Fix what you find. If a problem cannot be fixed silently (e.g., a true contradiction that needs user input), surface it before the user review gate.

---

## Phase 7: User Review Gate

Hand off to the user with a single short message:

> "Spec written to `<path>`. Please review and let me know if you want changes."

Wait for explicit feedback.

- If the user requests changes, make them and re-run Phase 6 (self-review) over the edited sections.
- If the user approves, stop. The skill ends here. Planning the work and building it are separate, later concerns.

---

## What This Skill Is NOT

- Not an implementation plan. No step-by-step build order, no ticket-level breakdown, no task assignments. That is a separate, later step.
- Not a PRD restatement. Restate product rules inline only where they directly motivate a technical choice.
- Not exhaustive. Capture the technical shape at a level of abstraction that gives a later planner enough to act — and leaves room for that planner's judgment.
- Not a code change. Never edit application source. Never run dev servers, build, or tests.

---

## Common Mistakes to Avoid

| Mistake | Prevention |
|---|---|
| Interrogating before reading | Phase 1 is non-optional. Read every reachable resource and walk the repo before asking anything. |
| Reading prior specs / PRDs in the repo for "context" | Off-limits. They're stale, superseded, or aspirational. User-provided inputs in Phase 1 are authoritative. Convention files (`CLAUDE.md`, `AGENTS.md`) and source code are safe. |
| Imposing a heavy spec on a light change | Phase 2 — scope-classify before interviewing. Offer to skip on tiny scopes. |
| Treating the interview as a transcription of the user's framing | The interview has two jobs — resolve what the user knows AND surface what they didn't raise. Probe for edge cases, failure modes, rollout, and cross-cutting concerns the input didn't name. |
| Asking implementation-level questions | "Would the implementer have to ask this anyway, later?" If the answer is yes (framework default, in-repo convention, routine engineering choice), skip it. The spec captures shape, not detail. |
| Writing the spec straight after the interview, without synthesis | Phase 4 is non-optional. Present the strategy as a structured synthesis, surface the items you added beyond the user's framing, wait for explicit approval, then write. |
| Reinventing the interview mechanic | Use `superpowers:brainstorming`. It already does one-question-at-a-time with recommended options. |
| Treating the interviewee like a beginner | Frame technically. They know the stack. |
| Linking the PRD as the source of truth | Restate the rule inline. The spec is self-contained. |
| Drifting into implementation steps | The spec describes shape, not build order. Lift back to abstraction. |
| Writing TBD without asking | Ask. Only leave a confirmed Open Question. |
| Pre-populating sections for "completeness" | Empty ceremony hurts the spec. Add sections only when they have content. |
| Skipping self-review | Phase 6 catches the things the writer's eye misses. |
| Continuing past the hand-off | Stop at the user-review gate. Do not start planning or implementing. |
