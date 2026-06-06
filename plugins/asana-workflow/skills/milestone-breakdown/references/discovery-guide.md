# Discovery Guide

Before proposing any milestone structure, build a complete picture of what exists, what needs to be built, and across which platforms. This guide covers the input sources, the repo walk, the existing-landscape inspection for Asana project URLs, the hard protectionism rule, the questioning strategy, and the scope read that always produces milestones (no sub-modes).

## Source Detection

Inspect each argument (or the current working directory if no argument was given) and ingest accordingly:

| Source type | How to detect | How to ingest |
|---|---|---|
| Asana task or project | `app.asana.com` in URL | Use the `asana-api` skill to fetch the task / project, all subtasks, comments, and attachments |
| Jira issue | `atlassian.net/browse/` or `atlassian.net/jira/` in URL | Use Atlassian MCP to fetch the issue and linked items |
| Linear issue | `linear.app/` in URL | Use Linear MCP to fetch the issue |
| GitHub issue or PR | `github.com/.../issues/` or `/pull/` in URL | Use `gh issue view` / `gh pr view` |
| Notion page | `notion.so` or `notion.site` in URL | Use Notion MCP |
| Confluence page | `atlassian.net/wiki/` in URL | Use Atlassian MCP |
| Google Drive doc | `drive.google.com` or `docs.google.com` in URL | Use Google Drive MCP |
| Figma file or frame | `figma.com` in URL | Use Figma MCP (`get_design_context`, `get_metadata`, `get_screenshot`) |
| Loom video | `loom.com` in URL | WebFetch the page and extract transcript / summary. If nothing usable, ask the user to paste the transcript |
| Other URL | `http://` or `https://` | WebFetch |
| Local file path | path resolves to a regular file | Read directly (PDF, Markdown, HTML, code) |
| Local folder path | path resolves to a directory | Walk the directory and read all relevant files |
| Free-text seed | non-empty text not matching any rule above | Treat as a problem-statement seed. Ask the user whether to also inspect the current working directory |
| No argument given | — | Inspect the current working directory and read what looks relevant |

When multiple inputs are given (e.g., PRD path + Figma URL + Asana project URL), ingest all of them before continuing. An Asana project URL triggers the Existing-Landscape Inspection step below.

## Repository Walk

Read `CLAUDE.md` / `AGENTS.md` at repo root and in all affected directories. Read source for plausibly-touched modules to understand the current architecture in the areas the work will change. Start at repo root, then check each directory the work is likely to touch. Architecture decision records (ADRs) or similar dated, current-state decision logs are reliable to read if the repo has them.

Do not read prior specs, prior PRDs, prior task breakdowns, or other planning documents found anywhere under `docs/*/specs/`, `docs/*/product-requirements/`, `docs/*/task-breakdowns/`, `docs/*/milestone-breakdown/`, `specs/`, `prds/`, or sibling planning directories. Prior planning documents are frequently stale, superseded, or aspirational. Reading them risks importing outdated assumptions or dropped scope into the new breakdown without you being able to tell which is which. Source code reflects current reality; old planning docs do not.

## Existing-Landscape Inspection

When an Asana project URL is among the inputs, inspect the existing milestone landscape before proposing anything new.

1. Fetch the project's sections via `asana-api`.
2. For each section, find the task where `resource_subtype == "milestone"`.
3. Classify each milestone:
   - **expanded** = section contains ≥1 task with `resource_subtype == "default_task"`
   - **unexpanded** = only the milestone-subtype task is present in the section
4. Surface the landscape to the user as a table. Example:

   ```
   M1: Auth System        — expanded   (read-only, 6 tasks)
   M2: User Management    — expanded   (read-only, 4 tasks)
   M3: Billing            — unexpanded (touchable)
   ```

5. Ask the user (verbatim): *"I'll add new milestones and may refine M3. Expanded milestones are read-only context. OK?"*
6. Wait for explicit confirmation before continuing.

New milestones append to the existing project sequence. Markdown M-labels stay sequential from M1 (they are local-only); `submit-breakdown` assigns the actual Asana M-labels at push time.

## Protectionism Rule

An expanded milestone is read-only. The skill refuses unconditionally to modify, rename, delete, or replace any milestone whose section already contains implementation tasks. There is no override.

> "An expanded milestone has implementation tasks under it. Modifying its description, deleting/renaming it, or replacing its attachment risks orphaning those tasks or breaking the link between them and their parent. The skill refuses unconditionally. The user must rename the new milestone, redesign it not to overlap, or operate via a different workflow."

If the user explicitly asks to touch an expanded milestone, instruct them to use a different workflow. There is no "but you said so" escape hatch.

## Questioning Strategy

Don't interrogate the user with a rigid question sequence. Instead:

- **Batch related questions** — when you already know enough to ask them together, ask about all related aspects in one message.
- **Skip the obvious** — if the spec is clearly a CLI tool, don't ask about Figma or mobile.
- **Infer from context** — if the user dropped a repo URL, explore it (`CLAUDE.md`, file structure, git log) before asking what's already built.
- **One round of questions at a time** — ask what you need, wait for the answer, then ask follow-ups based on what you learned.

Never propose a milestone breakdown until you have enough context to make informed decomposition decisions. What "enough" looks like varies by project.

## Effort & Scope Read

The skill always produces milestones. There are no sub-modes. The interview confirms how many milestones are appropriate and where the boundaries between them lie.

For very small work that fits in a single milestone, still produce a single milestone block — do not short-circuit out of the workflow. The structured output is always required, regardless of scale.
