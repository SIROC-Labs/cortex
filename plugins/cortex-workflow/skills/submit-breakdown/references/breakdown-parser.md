# Breakdown Parser Reference

Defines the parsing contract for the input shapes submit-breakdown accepts. The parser is **polymorphic** — it walks `breakdown.md` and processes whatever blocks it finds:

1. **Single markdown file** (legacy, from older `task-breakdown` runs) — milestone blocks + implementation-task entries inline.
2. **Folder bundle** — a directory containing `breakdown.md` plus attachment files. Two bundle shapes are supported and may be mixed:
   - **Milestone bundle** (from `milestone-breakdown`) — M-blocks only, with per-milestone spec attachments.
   - **Task bundle** (from `task-breakdown`) — T-blocks only, with per-task implementation-plan attachments, and an optional top-level `**Target milestone:**` line.

The set of block types found in `breakdown.md` decides which Phase 3 steps run (see SKILL.md "Block-presence routing"). M-only, T-only, and mixed inputs are all valid.

This reference describes *what the markdown carries and how it maps to the neutral task operations*. It never names a provider or a provider identifier — the seam resolves those.

## Input shape detection

| Input path resolves to | Action |
|---|---|
| A file | Parse as single-file (legacy). |
| A directory containing `breakdown.md` | Parse as folder bundle. Each file referenced by a block's `**Attachments:**` field is a candidate attachment. |
| A directory without `breakdown.md` | Error: "No `breakdown.md` found in `<path>`. Expected a folder bundle." |

## File-level metadata: `**Target milestone:**`

A folder bundle's `breakdown.md` MAY begin with a single top-level metadata line:

```
**Target milestone:** <task-url>
```

Routing rule:
- **Parsed** at Phase 1b — resolved via `find_task` to a milestone (`kind == milestone`); submit-breakdown surfaces the resolved name and asks the user to confirm before any write (see SKILL.md Phase 1b).
- **Never pushed** to any task description. It is file-level routing metadata only.
- Optional. When absent and the bundle's T-blocks have no wrapping M-block, submit-breakdown prompts the user interactively at upload time (SKILL.md Phase 3 Step 3).

## Folder bundle: M-block parsing

Each `## M{N} :: <Name>` header in `breakdown.md` starts a milestone block. Within a block:

| Field | Role | Pushed to description? |
|---|---|---|
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Out of scope:**` (optional) | Body | Yes |
| `**References:**` (optional) | Body | Yes |
| `**Depends on:**` | Dependency metadata | No — parsed for M-labels, used to wire native dependencies via `add_dependency` |
| `**Source:**` (optional) | Refine-path metadata | No — parsed to reuse an existing milestone instead of creating one; refreshes its description when unexpanded, refuses when expanded (see idempotency below) |
| `**Attachments:**` | Attachment metadata | No — file list uploaded via `upload_attachment` (renamed to `milestone-spec.md`) |

**Body** = the four body fields above, rendered in canonical order (Purpose → Description → Out of scope → References) as the milestone's description via `set_description` (new milestones only — see idempotency below).

**Free-text paragraphs** immediately after the `## M{N} ::` header are rationale (md-only) and are ignored.

**Content under top-level headers `## References` and `## Originating Task`** is handled separately (file-level refs / originating-task cleanup) and not associated with any milestone block.

## Folder bundle: T-block parsing

Each `## T{N} :: <Name>` header in `breakdown.md` starts an implementation-task block. Within a block:

| Field | Role | Pushed to description? |
|---|---|---|
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Out of scope:**` (optional) | Body | Yes |
| `**Acceptance criteria:**` | Body | Yes |
| `**References:**` (optional) | Body | Yes |
| `**Platform:**` / `**Category:**` | Field metadata | No — passed as `create_task(..., fields={Platform, Category, …})` |
| `**Depends on:**` | Dependency metadata | No — parsed for T-labels, wired via `add_dependency` |
| `**Attachments:**` | Attachment metadata | No — file list uploaded via `upload_attachment` (renamed to `implementation-plan.md`) |

T-blocks support the same `**Attachments:**` mechanism as M-blocks. The routing rules are identical (parsed for file list, not pushed to the description); the only differences are the rename target and the downstream Product Status effect (see SKILL.md Phase 3 Step 3).

## Folder bundle: attachment resolution

`**Attachments:**` is a markdown bullet list. Each bullet's text is a file path relative to `breakdown.md`'s folder.

Upload rule (M-blocks):
- Verify the file exists at the resolved path.
- Rename to `milestone-spec.md` on upload (strip any `M{N}-` prefix).
- On re-runs: if an attachment named `milestone-spec.md` already exists on the milestone (`get_attachments`), `remove_attachment` it first, then `upload_attachment` the new one (replace, not duplicate).
- **Skip entirely for expanded/protected milestones** (see idempotency below).

Upload rule (T-blocks):
- Verify the file exists at the resolved path.
- **Rename to `implementation-plan.md`** on upload (strip the `T{N}-<slug>-` prefix — local-only ordering).
- On re-runs: if an attachment named `implementation-plan.md` already exists on the task, `remove_attachment` it first, then `upload_attachment` the new one (replace, not duplicate).
- The presence of an `implementation-plan.md` attachment is what flips a non-Design T-task's Product Status from `Refinement` to `Unassigned` — see SKILL.md Phase 3 Step 3.

## Folder bundle: dependency wiring

`**Depends on:**` contains a comma-separated list of markdown labels (or "None"):
- M-block `**Depends on:**` lists M-labels (wired in SKILL.md Phase 3 Step 4).
- T-block `**Depends on:**` lists T-labels (wired in SKILL.md Phase 3 Step 5).

Build the `markdown_label → task ref` map after all tasks are created/reused (combining new and existing tasks). Wire each dependency via `add_dependency(<dependent>, <depended-on>)` using the resolved refs.

## Milestone matching, ordinal assignment, and label remapping

Milestones on the board carry an **`M{n}:` ordinal prefix** in their name — e.g. `M1: Zeta`, `M2: Onboarding`. The prefix is part of the milestone's neutral name; how a provider realizes a milestone under that name is internal to the seam. Three rules govern how `breakdown.md`'s M-blocks map onto this:

**Matching (idempotency).** A block reuses an existing milestone when their **plain names** match — the milestone name with any leading `M{n}: ` prefix stripped, compared case-insensitively. A block named `Zeta` (from `## M1 :: Zeta`) matches an existing `M1: Zeta` on the board. Matching never depends on the ordinal — only the plain name portion.

**Ordinal assignment (new milestones).** A newly created milestone's board name is `M{n}: <Name>`, where `n` continues the board's existing numbering: `n = max(existing ordinals on the board) + 1`, incrementing once per new milestone in breakdown order. Existing ordinals come from parsing the `M{n}:` prefix of each `list_milestones(board)` entry (unprefixed names count as no ordinal). A board already holding `M1:`–`M3:` names the first new block `M4:`, the next `M5:`, and so on. Reused milestones keep their existing name and ordinal — they are never renumbered.

**Label remapping (dependencies).** The `M{N}` labels in `breakdown.md` are **local** — this file's namespace, sequential from M1, used only to express `**Depends on:**` before the board assigns handles. They are **not** the board ordinals. submit-breakdown builds a `local M-label → milestone ref` map as it ensures each milestone, then wires every `**Depends on:**` dependency through that map. Because the board may renumber (a board holding M1–M3 turns the doc's local `M1` into `M4:`), a local label and its board ordinal routinely differ — always resolve dependencies through the ref map, never by matching label text to a board ordinal.

This is provider-neutral: the `M{n}:` name, the plain-name matching, and the local-label remapping apply whatever provider the seam resolves.

## Folder bundle: milestone idempotency and Source (M-blocks)

Milestone reuse is by **plain name on the board** (leading `M{n}: ` prefix stripped — see "Milestone matching, ordinal assignment, and label remapping" above), discovered via `list_milestones(board)` (each entry is `{ref, name, expanded}`). There is no notion of sections or resource subtypes — those are internal to whichever provider the seam resolves.

- **New milestone** (plain name not in the `list_milestones` landscape) — `ensure_milestone(board, "M{n}: <Name>")` creates it with the next board ordinal; submit-breakdown then sets its body via `set_description` and uploads its spec attachment.
- **Existing, unexpanded milestone** — `ensure_milestone` reuses it. Its description is **frozen** (never overwritten) — except when a `**Source:**` refine targets it (see below). The spec attachment is still replaced on re-run.
- **Existing, expanded milestone** (`expanded == true`, i.e. has member tasks per `list_milestones` / `milestone_tasks`) — **protected**: neither description nor attachments are touched. Log a divergence notice and continue.

When a milestone block carries `**Source:** <url>` (a `milestone-breakdown` refine request):
- Resolve the URL via `find_task`; verify `kind == milestone`. Treat it as the reuse target for that block — do not create a new milestone, and keep its existing board name/ordinal (no renumbering).
- If the milestone is **expanded**, refuse: "Milestone '<name>' at <url> is expanded; bundle input cannot modify an expanded milestone." A milestone with work under it is never overwritten.
- If the milestone is **unexpanded**, refresh its description via `set_description(<milestone>, <rendered body>)`, and replace its spec attachment as usual. This is the one reuse path that overwrites a description: `**Source:**` is a deliberate refine, distinct from an incidental name-match on re-run (which stays frozen).

T-blocks do not support a `**Source:**` field — T-task idempotency is by name within the parent milestone's `milestone_tasks` (see SKILL.md "Idempotency match keys").

## Single-file (legacy): unchanged

The legacy task-breakdown single-file input continues to be parsed by the rules in `description-template.md` (milestone blocks + implementation-task entries). This reference does not redefine that path; it is treated as a mixed bundle at submit time.
