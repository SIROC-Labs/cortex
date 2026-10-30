# Validation Checklist

Run validation after generating files in Phase 5 (`breakdown.md`) and Phase 6 (each `E{N}-milestone-spec.md`), and again before invoking `submit-breakdown` (Phase 8). Each rule below is a hard check — failures surface to the user inline, list each rule that failed with the offending line/section, and block Phase 5/6 file writes or Phase 8 submit until all failures are resolved. No silent skips.

## On breakdown.md

- Each `## E{N} ::` block has `**Goal:**`, `**Description:**` and `**Definition of done:**` (required).
- `**Definition of done:**` has ≥1 bullet, each an outcome also listed in the milestone's `## Acceptance Criteria`.
- `**Description:**` is product-language (no class names, endpoint paths, or framework patterns anywhere in the prose).
- `**References:**` (if present) contains only codebase paths, public URLs, Figma URLs — no input-doc paths.
- `**Attachments:**` lists existing files in the same folder (re-checked at bundle level — see below).
- `**Depends on:**` E-labels all resolve to other `## E{N} ::` blocks in this file (no dangling refs, no cycles).
- E-labels are sequential from E1, no gaps.

## On each E{N}-milestone-spec.md

- Has `## Product Requirements` with ≥1 bullet.
- Has `## Acceptance Criteria` with ≥1 bullet.
- **At least one acceptance criterion is stakeholder-demonstrable** — observable by a non-technical reader (something they can see, use, or be shown). Criteria that are purely technical ("API client initialised", "typecheck passes", "schema migrated") do not satisfy this rule on their own. If no criterion passes this check, the milestone is infrastructure-only and must be absorbed or justified before submission (see `decomposition-principles.md` → "Infrastructure Milestones").
- Has `## Technical Spec` with at least `### Summary`, `### Technical Context`, `### Architecture Notes`, `### Testing Strategy`, `### References & Links`.
- No reference to the input PRD path / input spec path / any uncommitted file.
- No `TBD` / `TODO` / `???` placeholders — explicit `### Open Questions` only.
- File is self-sufficient: a reader without the original PRD can understand what to build.

## On the bundle as a whole

- Every `**Attachments:**` entry in `breakdown.md` points to an existing file in the folder.
- Every `E{N}-milestone-spec.md` in the folder is referenced by exactly one milestone block.

## On failure

Surface failures to the user inline, listing each rule that failed with the offending line/section. Block writing the file (Phase 5/6) or invoking `submit-breakdown` (Phase 8) until all failures are resolved. No silent skips. Format suggestion:

```
Validation failed (3 issues):
- breakdown.md / E2 :: Billing — missing **Goal:** field (line 27)
- breakdown.md / E3 :: Reporting — **Description:** uses framework language ("React component"); rewrite in product language (line 39)
- E2-milestone-spec.md — no `## Acceptance Criteria` section
```
