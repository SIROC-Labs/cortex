# Validation Checklist

Run validation after generating files in Phase 5 (`breakdown.md`) and Phase 6 (each `M{N}-milestone-spec.md`), and again before invoking `submit-breakdown` (Phase 8). Each rule below is a hard check — failures surface to the user inline, list each rule that failed with the offending line/section, and block Phase 5/6 file writes or Phase 8 submit until all failures are resolved. No silent skips.

## On breakdown.md

- Each `## M{N} ::` block has `**Purpose:**` and `**Description:**` (required).
- `**Description:**` is product-language (no class names, endpoint paths, or framework patterns anywhere in the prose).
- `**References:**` (if present) contains only codebase paths, public URLs, Figma URLs — no input-doc paths.
- `**Attachments:**` lists existing files in the same folder (re-checked at bundle level — see below).
- `**Depends on:**` M-labels all resolve to other `## M{N} ::` blocks in this file (no dangling refs, no cycles).
- M-labels are sequential from M1, no gaps.

## On each M{N}-milestone-spec.md

- Has `## Product Requirements` with ≥1 bullet.
- Has `## Acceptance Criteria` with ≥1 bullet.
- **At least one acceptance criterion is stakeholder-demonstrable** — observable by a non-technical reader (something they can see, use, or be shown). Criteria that are purely technical ("API client initialised", "typecheck passes", "schema migrated") do not satisfy this rule on their own. If no criterion passes this check, the milestone is infrastructure-only and must be absorbed or justified before submission (see `decomposition-principles.md` → "Infrastructure Milestones").
- Has `## Technical Spec` with at least `### Summary`, `### Technical Context`, `### Architecture Notes`, `### Testing Strategy`, `### References & Links`.
- No reference to the input PRD path / input spec path / any uncommitted file.
- No `TBD` / `TODO` / `???` placeholders — explicit `### Open Questions` only.
- File is self-sufficient: a reader without the original PRD can understand what to build.

## On the bundle as a whole

- Every `**Attachments:**` entry in `breakdown.md` points to an existing file in the folder.
- Every `M{N}-milestone-spec.md` in the folder is referenced by exactly one milestone block.

## On failure

Surface failures to the user inline, listing each rule that failed with the offending line/section. Block writing the file (Phase 5/6) or invoking `submit-breakdown` (Phase 8) until all failures are resolved. No silent skips. Format suggestion:

```
Validation failed (3 issues):
- breakdown.md / M2 :: Billing — missing **Purpose:** field (line 27)
- breakdown.md / M3 :: Reporting — **Description:** uses framework language ("React component"); rewrite in product language (line 39)
- M2-milestone-spec.md — no `## Acceptance Criteria` section
```
