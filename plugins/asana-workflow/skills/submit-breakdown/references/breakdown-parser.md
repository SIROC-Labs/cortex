# Breakdown Parser Reference

Defines the parsing contract for the input shapes submit-breakdown accepts. The parser is **polymorphic** — it walks `breakdown.md` and processes whatever blocks it finds:

1. **Single markdown file** (legacy, from older `task-breakdown` runs) — a `.md` file with milestone blocks + implementation task entries inline.
2. **Folder bundle** — a directory containing `breakdown.md` plus attachment files. Two bundle shapes are supported and may be mixed:
   - **Milestone bundle** (from `milestone-breakdown`) — M-blocks only, with `M{N}-milestone-spec.md` attachments.
   - **Task bundle** (from `task-breakdown`) — T-blocks only, with `T{N}-<slug>-implementation-plan.md` attachments, and an optional top-level `**Target milestone:**` line.

The set of block types found in `breakdown.md` decides which Phase 3 steps run (see SKILL.md "Block-presence routing"). M-only, T-only, and mixed inputs are all valid.

## Input shape detection

| Input path resolves to | Action |
|---|---|
| A file | Parse as single-file (legacy). |
| A directory containing `breakdown.md` | Parse as folder bundle. Each file referenced by a block's `**Attachments:**` field is a candidate attachment. |
| A directory without `breakdown.md` | Error: "No `breakdown.md` found in `<path>`. Expected a folder bundle." |

## File-level metadata: `**Target milestone:**`

A folder bundle's `breakdown.md` MAY begin with a single top-level metadata line:

```
**Target milestone:** https://app.asana.com/0/<project>/<task>
```

Routing rule:
- **Parsed** at Phase 1b — resolves the URL to a milestone-subtype task GID; submit-breakdown surfaces the resolved name + section and asks the user to confirm before any write (see SKILL.md Phase 1b).
- **Never pushed** to any Asana description. It is file-level routing metadata only.
- Optional. When absent and the bundle's T-blocks have no wrapping M-block, submit-breakdown prompts the user interactively at upload time (SKILL.md Phase 3 Step 3).

## Folder bundle: M-block parsing

Each `## M{N} :: <Name>` header in `breakdown.md` starts a milestone block. Within a block:

| Field | Role | Pushed to Asana description? |
|---|---|---|
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Out of scope:**` (optional) | Body | Yes |
| `**References:**` (optional) | Body | Yes |
| `**Depends on:**` | Dependency metadata | No — parsed for M-labels, used to wire native Asana task dependencies |
| `**Source:**` (optional) | Refine-path metadata | No — parsed to detect "update existing milestone task" instead of "create new" |
| `**Attachments:**` | Attachment metadata | No — file list uploaded as Asana attachments (renamed to `milestone-spec.md`) |

**Body** = the four body fields above, rendered in canonical order (Purpose → Description → Out of scope → References) as the Asana task `html_notes`.

**Free-text paragraphs** immediately after the `## M{N} ::` header are rationale (md-only) and are ignored.

**Content under top-level headers `## References` and `## Originating Task`** is handled separately (file-level refs / originating-task cleanup) and not associated with any milestone block.

## Folder bundle: T-block parsing

Each `## T{N} :: <Name>` header in `breakdown.md` starts an implementation-task block. Within a block:

| Field | Role | Pushed to Asana description? |
|---|---|---|
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Out of scope:**` (optional) | Body | Yes |
| `**Acceptance criteria:**` | Body | Yes |
| `**References:**` (optional) | Body | Yes |
| `**Depends on:**` | Dependency metadata | No — parsed for T-labels, used to wire native Asana task dependencies |
| `**Attachments:**` | Attachment metadata | No — file list uploaded as Asana attachments (renamed to `implementation-plan.md` — see below) |

T-blocks support the same `**Attachments:**` mechanism as M-blocks. The routing rules are identical (parsed for file list, not pushed to the description); the only differences are the rename target and the downstream Product Status effect (see SKILL.md Phase 3 Step 3).

## Folder bundle: attachment resolution

`**Attachments:**` is a markdown bullet list. Each bullet's text is a file path relative to `breakdown.md`'s folder.

Upload rule (M-blocks):
- Verify the file exists at the resolved path.
- Rename to `milestone-spec.md` on upload (strip any `M{N}-` prefix).
- On re-runs: if an attachment named `milestone-spec.md` already exists on the milestone task, delete it first, then upload the new one (replace, not duplicate).

Upload rule (T-blocks):
- Verify the file exists at the resolved path.
- **Rename to `implementation-plan.md`** on upload (strip the `T{N}-<slug>-` prefix — local-only ordering).
- On re-runs: if an attachment named `implementation-plan.md` already exists on the task, delete it first, then upload the new one (replace, not duplicate).
- The presence of an `implementation-plan.md` attachment is what flips a non-Design T-task's Product Status from `Refinement` to `Unassigned` — see SKILL.md Phase 3 Step 3.

## Folder bundle: dependency wiring

`**Depends on:**` contains a comma-separated list of markdown labels (or "None"):
- M-block `**Depends on:**` lists M-labels (wired via Phase 3 Step 4).
- T-block `**Depends on:**` lists T-labels (wired via Phase 3 Step 5).

Build the `markdown_label → task_gid` map after all tasks are created/reused (combining new and existing tasks in the project). Wire dependencies via `asana_set_task_dependencies` using the resolved GIDs.

The M-label dependency map is for in-session wiring only — it is independent of the `markdown_label → asana_label` map used to name new milestones (Phase 3 Step 0).

## Folder bundle: Source refine path (M-blocks only)

When a milestone block has `**Source:** <url>`:
- Resolve the URL to an Asana task GID.
- Verify the task's `resource_subtype == "milestone"`. If not, error.
- Verify the task's section contains zero `default_task` children. If any exist, refuse (the milestone is expanded; bundle is not allowed to touch it).
- Update the task's `html_notes` with the new body (verbatim push).
- Replace the milestone-spec.md attachment (delete old by name match, upload new).
- Do not create a new task. Do not re-name. Do not re-section.

T-blocks do not support a `**Source:**` field — T-task idempotency is by `(section, name, resource_subtype == "default_task")` (see SKILL.md "Idempotency match keys").

## Single-file (legacy): unchanged

The legacy task-breakdown single-file input continues to be parsed by the existing rules in `description-template.md` (rich vs thin milestone blocks, implementation task entries). This reference does not redefine that path.
