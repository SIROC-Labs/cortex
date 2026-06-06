# Breakdown Parser Reference

Defines the parsing contract for the two input shapes submit-breakdown accepts:

1. **Single markdown file** (legacy, from `task-breakdown`) — a `.md` file with milestone blocks + implementation task entries.
2. **Folder bundle** (new, from `milestone-breakdown`) — a directory containing `breakdown.md` + one or more `M{N}-milestone-spec.md` files.

## Input shape detection

| Input path resolves to | Action |
|---|---|
| A file | Parse as single-file (legacy). |
| A directory containing `breakdown.md` | Parse as folder bundle. Each `M{N}-milestone-spec.md` in the folder is a candidate attachment. |
| A directory without `breakdown.md` | Error: "No `breakdown.md` found in `<path>`. Expected a folder bundle." |

## Folder bundle: milestone block parsing

Each `## M{N} :: <Name>` header in `breakdown.md` starts a milestone block. Within a block:

| Field | Role | Pushed to Asana description? |
|---|---|---|
| `**Purpose:**` | Body | Yes |
| `**Description:**` | Body | Yes |
| `**Out of scope:**` (optional) | Body | Yes |
| `**References:**` (optional) | Body | Yes |
| `**Depends on:**` | Dependency metadata | No — parsed for M-labels, used to wire native Asana task dependencies |
| `**Source:**` (optional) | Refine-path metadata | No — parsed to detect "update existing milestone task" instead of "create new" |
| `**Attachments:**` | Attachment metadata | No — file list uploaded as Asana attachments |

**Body** = the four body fields above, rendered in canonical order (Purpose → Description → Out of scope → References) as the Asana task `html_notes`.

**Free-text paragraphs** immediately after the `## M{N} ::` header are rationale (md-only) and are ignored.

**Content under top-level headers `## References` and `## Originating Task`** is handled separately (file-level refs / originating-task cleanup) and not associated with any milestone block.

## Folder bundle: attachment resolution

`**Attachments:**` is a markdown bullet list. Each bullet's text is a file path relative to `breakdown.md`'s folder.

Upload rule:
- Verify the file exists at the resolved path.
- Rename to `milestone-spec.md` on upload (strip any `M{N}-` prefix).
- On re-runs: if an attachment named `milestone-spec.md` already exists on the milestone task, delete it first, then upload the new one (replace, not duplicate).

## Folder bundle: dependency wiring

`**Depends on:**` contains a comma-separated list of markdown M-labels (or "None"). Build a `markdown_label → milestone_task_gid` map after all milestone tasks are created/reused (combining new and existing milestones in the project). Wire dependencies via `asana_set_task_dependencies` using the resolved GIDs.

The map is for in-session wiring only — it is independent of the `markdown_label → asana_label` map used to name new milestones (Phase 3 Step 0).

## Folder bundle: Source refine path

When a milestone block has `**Source:** <url>`:
- Resolve the URL to an Asana task GID.
- Verify the task's `resource_subtype == "milestone"`. If not, error.
- Verify the task's section contains zero `default_task` children. If any exist, refuse (the milestone is expanded; bundle is not allowed to touch it).
- Update the task's `html_notes` with the new body (verbatim push).
- Replace the milestone-spec.md attachment (delete old by name match, upload new).
- Do not create a new task. Do not re-name. Do not re-section.

## Single-file (legacy): unchanged

The legacy task-breakdown single-file input continues to be parsed by the existing rules in `description-template.md` (rich vs thin milestone blocks, implementation task entries). This reference does not redefine that path.
