---
name: milestone-breakdown
description: >
  Produces a milestone-based roadmap of work as a folder of artifacts — a top-level breakdown.md
  (one rich block per milestone, ready to push as Asana milestone task descriptions) plus one
  M{N}-milestone-spec.md per milestone (a self-contained technical spec scoped to that milestone,
  designed to be uploaded as an Asana attachment so future task expansion never needs the original
  PRD or input spec). Use this skill whenever the user wants to plan, structure, or roadmap work
  at the milestone level — "break this into milestones", "milestone breakdown for this PRD",
  "plan the milestones", "/milestone-breakdown", or provides a spec / PRD / Asana task or project
  URL / Figma link and wants a milestone roadmap. Always operates in milestone-first mode; never
  authors implementation tasks (that is task-breakdown EXPAND mode in a later session). When given
  an existing Asana project URL, surfaces the existing milestone landscape and refuses to touch
  any milestone that already has implementation tasks (expanded milestones are read-only context).
---

# Milestone Breakdown

Produce a milestone-based roadmap as a folder of artifacts under
`docs/cortex/milestone-breakdown/<YYYY-MM-DD>-<slug>/`:

- **`breakdown.md`** — one rich block per milestone, structured for `submit-breakdown` to push verbatim as Asana milestone task descriptions.
- **`M{N}-milestone-spec.md`** — per-milestone technical spec (Product Requirements + Acceptance Criteria + Technical Spec). Uploaded as an Asana attachment by `submit-breakdown` so future task expansion is self-sufficient.

Each milestone in Asana is atomic: the task description + the attached `milestone-spec.md` together carry everything a future `task-breakdown` EXPAND session needs. No dependency on the original PRD, input spec, or any uncommitted file.

## Mode

Always milestone-first. No sub-modes. The "slot tasks into existing milestones" path lives in `task-breakdown` (not this skill).

## Phases

### Phase 1 — Context Discovery

Ingest all input sources (PRD path, Asana task/project URL, Figma URL, Notion, Loom, free text, folder path, current working directory). Walk the repo for `CLAUDE.md` / `AGENTS.md` and current-state code in affected areas. Never read prior planning docs.

See `references/discovery-guide.md` for the source-detection table and questioning strategy.

### Phase 2 — Existing-Landscape Surfacing

If an Asana project URL is among inputs, fetch its sections + milestone tasks, classify each milestone as **expanded** (has `default_task` children) or **unexpanded**, and surface the landscape to the user. Confirm with the user that operations will target only unexpanded + new milestones, then enforce the protectionism rule: never modify an expanded milestone.

See `references/discovery-guide.md` → "Existing-Landscape Inspection".

### Phase 3 — Decomposition Interview

Drive via `superpowers:brainstorming`. Topic universe scoped to milestone-level decisions:

- Boundaries — how many milestones, what each delivers, where the seams are
- Ordering — which milestone unblocks the most downstream work
- Scope per milestone — what's in, what's out
- Cross-milestone dependencies — including the ones the user did not name
- Platform coverage per milestone (Backend, Frontend, iOS, Android, Design)
- Design-dependency strategy — designs ready / parallel tracks / design-as-you-go
- For existing projects: which unexpanded milestones to refine, which to leave alone, which new ones to add

One question at a time. Treat the user as a technical expert. Probe for what the user did not raise.

See `references/decomposition-principles.md` for milestone-design rules.

### Phase 4 — Synthesis & Approval

Present a single structured message: proposed milestone list (M-labels, names, one-line purpose, DAG, items surfaced beyond the user's framing, open questions). Wait for explicit "go". Iterate on push-back.

### Phase 5 — Author breakdown.md

Write `breakdown.md` with one `## M{N} :: <Name>` block per milestone. Body fields: Purpose, Description, Out of scope (optional), References (optional). Metadata fields: Depends on, Source (optional), Attachments. Md-only rationale paragraphs (free-text prose immediately after a header) capture planning context and are ignored by `submit-breakdown`.

See `references/output-format.md` → "breakdown.md template".

### Phase 6 — Extract per-milestone specs

For each milestone, automatically generate `M{N}-milestone-spec.md` from the ingested material plus interview answers. Template: Product Requirements + Acceptance Criteria + Technical Spec (nested create-spec 7-section structure). Copy-paste verbatim subsections from inputs where appropriate. Inline product rules where they motivate technical choices. References allowed: codebase paths, public URLs, Figma URLs only. If material is genuinely missing for a milestone, add an explicit `### Open Questions` section to the spec — do not loop back into another interview round.

See `references/output-format.md` → "M{N}-milestone-spec.md template".

### Phase 7 — Self-Review Pass

For each generated file, scan for placeholders, contradictions, off-limits references (input doc paths), product-language violations in `**Description:**`, dangling M-label deps. Fix inline.

See `references/validation.md` for the full checklist.

### Phase 8 — Handoff

Offer `submit-breakdown`:

> "Breakdown saved to `<folder>`. Submit to Asana now? [Y/n]"

If yes, invoke `asana-workflow:submit-breakdown` via the Skill tool with the folder path.

## What This Skill Does NOT Do

- Author tasks under milestones (that is `task-breakdown` EXPAND mode in a later session).
- Touch expanded milestones in an existing Asana project.
- Reference input docs (PRD, source spec, originating ticket, any uncommitted file) in the artifacts that reach Asana.
- Run code, scaffold projects, or modify application sources.
- Create or modify Asana resources directly — that's `submit-breakdown`.

## Reference Files

- `references/discovery-guide.md` — input sources, existing-landscape inspection, protectionism rule, questioning strategy
- `references/decomposition-principles.md` — milestone design, ordering, deps DAG, design-driven decomposition
- `references/output-format.md` — `breakdown.md` template + parsing contract, `M{N}-milestone-spec.md` template, allowed references
- `references/validation.md` — validation checklist (per file + bundle-wide)
