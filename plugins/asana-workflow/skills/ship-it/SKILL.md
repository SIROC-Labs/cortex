---
name: ship-it
version: 0.1.0
description: >
  This skill should be used when development is complete and the work needs to be shipped:
  the user says "ship it", "we're done", "ready to ship", "done with this feature", "let's wrap up",
  "mark as in review", "create the PR", "link this to Asana", "create a PR and update Asana",
  or "push this and close the ticket". Also triggered automatically by `start-task` once the
  downstream development workflow (feature-dev, fix-bug, brainstorm) signals completion — in that
  case all session context (task GID, branch, draft PR URL) is already available and must not be
  re-requested.
---

# Ship It

Thin orchestrator that calls sub-skills in sequence to ship completed work. This skill contains NO domain logic — it coordinates, threads context, and handles skip conditions. Each sub-skill is independently invocable and self-contained.

## Prerequisites

### Sub-skills (must be installed)

- `pre-ship-check` — readiness gate (clean tree, commits, branch state)
- `work-summary` — session recap (git history, conversation context)
- `create-pr` — PR lifecycle (create, push, format)
- `asana-api` — Asana API operations (fetch, comment, move sections)

### External tools

- `gh` CLI authenticated for GitHub
- `asana-api` skill for Asana API operations — handles token resolution and setup guidance.

## Context Threading

The orchestrator threads context from earlier in the session — it does NOT re-ask for information that is already available.

### From start-task (if used)

When the session began with `start-task`, the following context is already in the conversation:
- **Task GID** — extracted from the Asana URL
- **Task URL** — the original Asana task URL
- **Task ID** — the project ID (e.g., MT251-168) from the custom field
- **Sprint project GID** — from the task's memberships
- **Section mappings** — already discovered when moving to "In Progress"
- **Branch name** — created by start-task (e.g., `MT251-168/add-export`)
- **Draft PR URL** — created by start-task, to be promoted to ready by create-pr

Reuse all of this. Do not ask the user for the Asana task URL again.

### From log-task (if used)

When the session began — or continued — with `log-task` (Fix Done variant), the handoff payload from log-task Step 7b-6 is already in the conversation:
- **Task GID**, **Task URL**, **Task ID** (e.g., `MT251-182`), **Task title**, **Sprint project GID**, **Branch name**

Reuse all of this when invoking `create-pr`. In particular, pass the **Task ID** and **Task title** through explicitly so the PR title is formatted as `<TASK-ID> :: <description>` without re-fetching from Asana. If log-task signalled that the Task ID could not be resolved, honour its fallback instruction — do not substitute a guess.

### From conversation history

If neither `start-task` nor `log-task` was used but an Asana URL appeared earlier in the conversation, extract the task GID from it. Only prompt for the URL if there is genuinely no Asana context available.

## The Flow

Follow these 5 steps in order.

### Step 1: Pre-ship Check

Invoke `pre-ship-check`. This sub-skill owns the QA verification gate — it prompts and invokes the QA skill directly if QA is missing for a non-bug task, blocks on missing QA for a bug task, and runs git/lint/build/test checks.

- If it returns **blocking** issues — stop and resolve them before continuing.
- If it returns **advisory** warnings — present them to the user and ask whether to proceed or fix first.

ship-it no longer has a separate QA step — all QA handling lives in pre-ship-check.

### Step 2: Work Summary

Invoke `work-summary` to generate a session recap.

Use the returned **body** for the PR description and the **Asana summary** for the Asana comment — they are different outputs with different audiences. Do not prompt the user to tweak or validate them.

### Step 3: Create PR

Invoke `create-pr`, passing:
- The work summary from Step 2
- The Asana task URL (from context threading above, if available)
- `orchestrator: true` — signals create-pr to skip its own git-check (already done in Step 1)

If a draft PR exists from `start-task`, create-pr will promote it to ready, update its description with the work summary, and assign reviewers — no new PR needed.

### Step 4: Asana Update

Handle via the `asana-api` skill. All Asana operations use the task GID from context threading.

1. **Move to "In Review":** Find the Sprint project from the task's memberships, find the "In Review" section, and move the task there. If the section mappings are already in conversation context from start-task, reuse them — do not re-fetch.

2. **Post ship comment:** Post a comment on the task using the **Asana summary** from work-summary (the high-level, non-technical 1-3 sentence version — NOT the full technical body). The comment MUST include the stats line from work-summary (`~Xm | Files changed: N | Commits: N`):

   ```
   <asana summary — high-level, non-technical>

   ~Xm | Files changed: N | Commits: N

   PR: <pr-url>

   🤖 Done
   ```

   The stats line is mandatory. The `🤖 Done` footer is mandatory — it signals AI-assisted work is complete and ready for review.

   **Posting:** use `asana-post-comment.sh <task-gid> --text "..."` (the wrapper bundled with `asana-api`). This comment is **plain text** — do not add HTML tags (`<strong>`, `<em>`, `<br>`, etc.). Asana auto-links the PR URL, and plain text with `\n` line breaks renders correctly. If an earlier comment in this session used `--html-text` (e.g., a QA verification comment), do not carry that style over — this comment is plain text and uses `--text`. The wrapper will refuse the POST if HTML slips into the body.

**Skip condition:** If no Asana task context is available, skip this step entirely.

### Step 5: Recap

Print a single recap:

> Shipped! Here's what happened:
> - Pre-ship check: passed (or "blocked — resolved X")
> - Work summary: generated
> - PR created: <pr-url> (or "already existed" / "skipped")
> - Asana task moved to "In Review": <task-url> (or "skipped")
> - Asana comment posted (or "skipped")

## Skippable Steps Summary

| Condition | Steps skipped |
|---|---|
| No Asana task context | 4 |
| Draft PR from start-task | 3 promotes draft to ready (no skip) |

## Deliberate Removals

- **No estimated cost** in session stats — removed from work-summary output.

## Error Handling

Never silently skip a step. If a sub-skill or command fails:
1. Report exactly what failed and why.
2. Ask the user how to proceed (retry, skip, or abort).
