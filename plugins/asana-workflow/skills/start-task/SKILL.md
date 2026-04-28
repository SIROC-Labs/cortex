---
name: start-task
version: 0.1.0
description: >
  This skill should be used when the user provides an Asana task URL and wants to begin working on it —
  "start task", "work on this", "pick up this ticket", "let's start on [task-id]", "jump on this",
  "begin this task", or pastes an Asana URL with intent to start development. Orchestrates the full
  lifecycle: validates sprint-readiness, sets up the branch and draft PR, routes to the right
  development workflow (feature-dev, fix-bug, or brainstorm), and ships via ship-it when done.
  Every run writes a step-by-step checkpoint file so work can be resumed after any interruption
  ("resume task", "pick up where I left off", "continue [task-id]"). For a shortcut that runs the
  full Asana orchestration and ship-it but skips sub-skill routing (feature-dev, brainstorming,
  fix-bug) and implements inline instead, add "fast" to the arguments — "start task fast",
  "fast mode", "just start coding".
argument-hint: <asana-task-url> [brainstorm|feature-dev|fast]
---

# Start Task

Take an Asana task, validate it's ready for development, understand the work, set up the branch, and route to the right skill. This skill is the conductor — it validates, prepares, and hands off.

## Prerequisites

- `asana-api` skill for all Asana API operations — handles token resolution and setup guidance.
- Access to `feature-dev:feature-dev`, `superpowers:systematic-debugging`, and optionally `superpowers:brainstorming` skills (external — see `references/skill-dependencies.md`).

## Argument Parsing

Parse `$ARGUMENTS` once and establish these flags. The rest of the skill refers to them by name instead of re-parsing.

| Flag | Set when `$ARGUMENTS` contains | Effect |
|------|-------------------------------|--------|
| `fast_mode` | `fast` | Step 10 skips sub-skill routing and the Step 11 QA sub-flow; implements inline |
| `workflow_choice` | `brainstorm` or `feature-dev` | Non-bug routing at Step 10; if neither, Step 10 asks the operator |

`fast_mode` is mutually exclusive with `workflow_choice` (fast skips routing entirely).

## Fast Mode

Set when `fast_mode` flag is active (see Argument Parsing above).

Fast mode runs the full lifecycle (Steps 0–9 and Step 12) unchanged but replaces Step 10 skill routing with direct inline implementation, and skips Step 11 (QA sub-flow) entirely. No `feature-dev`, `brainstorming`, `fix-bug`, or QA skill is invoked — implement the solution immediately using built-in tools (Read, Edit, Bash, Grep, etc.) and reason about it directly in this conversation.

**What is skipped:** only the sub-skill routing in Step 10 and the entire Step 11 QA sub-flow. Everything else — dependency checks, sprint validation, branch creation, draft PR, Asana status move/comment, and the ship-it handoff — runs as normal.

## The Flow

**Before Step 0:** Initialize (or resume) the checkpoint by running `${CLAUDE_PLUGIN_ROOT}/skills/start-task/scripts/checkpoint.sh init <task-gid> <asana-url>` (or load the existing file if one exists — see **`references/checkpoints.md`** → "Initialization" and "Resume Flow"). All checkpoint writes throughout the flow go through that helper script — do not Edit/Write the file directly.

### Step 0: Check External Skill Dependencies

Before doing anything else, check whether the external skills required for routing are installed. These are **not bundled** with this plugin.

- **`feature-dev@claude-plugins-official`** — required for non-bug tasks using the `feature-dev` workflow
- **`superpowers@claude-plugins-official`** — required for Bug tasks (`fix-bug` uses `systematic-debugging`) and for non-bug tasks using the `brainstorm` workflow

If either is missing, warn the user and ask whether to install now or continue. This is an **advisory blocking step** — wait for the user's answer before proceeding. See **`references/skill-dependencies.md`** for check instructions, install commands, and warning message templates.

### Step 1: Get the Asana Task URL

The Asana task URL is passed as `$ARGUMENTS`. If empty or invalid, prompt for it. Extract the **task GID** from the URL. See **`references/asana-patterns.md`** for supported URL formats.

### Step 2: Fetch Task Details

Fetch the full task with custom fields, memberships, assignee, and notes via the `asana-api` skill. See **`references/asana-patterns.md`** for required `opt_fields`.

Present a quick summary for confirmation: task name, assignee, category, task ID, sprint, and backlog board memberships. Classify memberships per **`plugins/asana-workflow/references/board-resolution.md`**.

### Step 3: Validate Sprint-Readiness

Run four validation checks: Active sprint membership, Estimated time, Product Status = Assigned, and ID field presence. See **`references/validation-rules.md`** for check details, failure display format, fix-offer logic, and skip rules. The validation-rules reference loads the board registry cache (see **`plugins/asana-workflow/references/board-resolution.md`**) to resolve the active sprint.

Report failures as a checklist. Active sprint membership, Estimated time, and Product Status are all blocking — offer to set the latter two via API, but do not proceed until all three pass. Only the ID field can be skipped after a warning.

### Step 4: Fetch Subtasks

Fetch subtasks via the `asana-api` skill. Group by status (incomplete = remaining work, completed = already done). Include subtasks in downstream context so the receiving skill understands what "done" looks like.

### Step 5: Fetch Comments and Attachments

Fetch task stories and filter for comments. List attachments by name, noting any images (mockups, screenshots). See **`references/asana-patterns.md`** for details.

### Step 6: Check for Existing Work

Before creating a branch, check if work already exists for this task ID. See **`references/git-workflow.md`** for the detection commands.

If a branch or PR exists, offer to resume or start fresh. If resuming, check out the existing branch and skip creation.

### Step 6a: Ask About Worktree (BLOCKING)

Before creating the branch, ask the user whether to use a git worktree. This is a **blocking** question — wait for an explicit answer before proceeding.

Present the choice:

> Would you like to work in a git worktree (isolated copy of the repo) or directly in the current directory?
> - **Worktree** _(recommended for parallel work — keeps main directory clean)_
> - **Current directory**

If the user chooses worktree, use `EnterWorktree` to create an isolated copy. The branch will be created inside the worktree in Step 7.

### Step 6b: Confirm Base Branch (BLOCKING)

Ask the user which branch to base the new branch on. This is a **blocking** question — wait for an explicit answer before proceeding.

Present the choice:

> Which branch should `<task-id>/<slug>` be based on?
> - **main** _(default — latest stable base)_
> - Another branch _(enter branch name)_

Default to `main` only after the user confirms. If the user specifies a different base branch, use that instead. Record the chosen base branch for Step 7.

### Step 7: Create Feature Branch

Create a branch using the task ID and a slug from the task name. Use the **base branch confirmed in Step 6b** (not assumed `main`). Inform (do not ask) when creating. See **`references/git-workflow.md`** for commands and naming convention.

### Step 8: Create Draft PR

Immediately after creating the branch, create an empty commit and a draft PR to establish the GitHub ↔ Asana link from minute one.

1. Create an empty commit so the branch can be pushed:
   ```bash
   git commit --allow-empty -m "<task-id> :: <task-name-slug> (start)"
   ```

2. Push the branch:
   ```bash
   git push -u origin $(git branch --show-current)
   ```

3. Create the draft PR:
   ```bash
   gh pr create --draft --title "<TASK-ID> :: <description>" --body "$(cat <<'EOF'
   ## Asana Task
   <asana-task-url>
   EOF
   )"
   ```

4. Capture the draft PR URL — it will be included in the Asana start comment and threaded through to ship-it.

### Step 9a: Move to In Progress

**This happens automatically — no permission needed.**

Move the task to "In Progress" on the Sprint board. Skip if already there. See **`references/asana-patterns.md`** for the section move API pattern. If the move fails, report why but do not block the workflow — proceed to Step 9b.

### Step 9b: Post Start Comment

**This happens automatically — no permission needed.**

Post a start comment on the task with the branch name and draft PR URL. Deduplicate by checking for an existing 🏁 comment for this branch. See **`references/asana-patterns.md`** for the comment format.

### Step 10: Route to the Right Workflow

Compile full task context (name, notes, custom fields, task ID, subtasks, comments, attachments, branch name) and route based on **Category** custom field:

**If `fast_mode`** — skip all skill routing regardless of category. Implement the solution directly in this conversation using built-in tools (Read, Edit, Bash, Grep, etc.). Do not invoke `feature-dev`, `brainstorming`, `fix-bug`, or any QA skill. Skip Step 11 (QA sub-flow) entirely and proceed to Step 12 when done.

**Otherwise:**

- **"Bug"** — Follow the QA sub-flow: verify → fix → verify loop.
- **Anything else** (Feature Request, Tech Debt, etc.):
  - If `workflow_choice` is `brainstorm` — invoke `superpowers:brainstorming` with the full context.
  - If `workflow_choice` is `feature-dev` — invoke `feature-dev:feature-dev` with the full context.
  - If `workflow_choice` is unset — ask (blocking):
    > "How do you want to approach this?
    > 1. Brainstorm the design first (`superpowers:brainstorming`)
    > 2. Go straight to implementation (`feature-dev:feature-dev`)"
    Wait for explicit answer before routing. No default assumed.
  - **Handoff instruction:** When passing context to `feature-dev` or `brainstorming`, include:
    > "When this workflow is complete, return to `start-task` for non-bug QA verification and the ship-it handoff. Do not end the session — there are more steps."
- **Category missing** — Prompt: "Is this a bug fix or a feature?" then apply the routing above.

The branch is already created and checked out — the downstream skill works on it directly.

### Step 11: QA Sub-flow

Run the QA sub-flow for the task's category. Resolve the QA skill (web-qa / mobile-qa / none) per **`plugins/asana-workflow/references/qa-routing.md`** → "Resolving the QA Skill". That reference is the shared resolve logic; this section is the enforcement contract.

**In fast mode** the sub-flow is skipped entirely. Mark every QA row in the checkpoint as `skipped` with reason `fast mode` (via `checkpoint.sh skip`).

#### Bug path — invoke, don't infer

The bug sub-flow (`QA: Resolve` → `QA: Investigate Bug` → `QA: Fix Bug` → `QA: Verify Fix`) runs only by **invoking the respective skills**. Runtime evidence from those invocations is what the sub-flow produces. Do not substitute reasoning for invocation:

- ❌ "I read the code and see the bug" — invoke the QA skill in investigate mode for reproduction evidence.
- ❌ Inlining a fix directly — invoke `fix-bug` so it passes through systematic-debugging + TDD.
- ❌ "Tests pass so the fix works" — invoke the QA skill in verify mode; runtime replay of the original repro is the evidence.

No runtime evidence = the row is not complete. See `references/qa-routing.md` for the exact invocation sequence of each sub-step.

**When `QA: Verify Fix` passes — proceed to Step 12.** Step 11 is only done when execution has advanced; do not end the session after the QA loop completes.

#### Non-bug path — exact prompt, no substitution

After the development workflow returns, ask the operator **using this exact wording**. Do not rephrase, do not inline into another question, do not substitute an approval prompt:

> "Implementation is complete. The changes can be visually verified before shipping — I'll build, deploy to the simulator/browser, and check the affected flows. A screenshot or video will be uploaded to the Asana task as proof of completion.
>
> Run QA verification? [yes / skip]"

Wait for the operator's answer. This is a **HARD GATE** — auto mode's "minimize interruptions" directive does NOT override. Skip asking only if the operator passed `skip QA` in start-task arguments or said "skip QA" / "run QA" earlier in the conversation as a direct utterance.

Anti-patterns:

- ❌ "Do you approve this for ship?" — this is a verification offer, not an approval question. A "yes" to ship-approval does NOT count as a "yes" to run QA.
- ❌ Self-generated static checklist ("Package.resolved has correct versions", "Build succeeded", "Tests pass") substituting for the QA skill invocation. These are pre-conditions the model already knows; they are not visual verification evidence.
- ❌ Inferring a "yes" from a prior answer to any different question. If the prior answer wasn't to this exact prompt (or to `skip QA` / `run QA`), re-ask.

If **yes** → invoke the resolved QA skill with a summary of what was built. The QA skill posts `✅ QA Verification — Feature Complete` to Asana with evidence. Only the QA skill's actual posting counts as evidence; a model-generated claim that QA passed does not. **After the QA skill returns with a posted Asana comment — proceed to Step 12.** Do not end the session at Step 11.

If **skip** → proceed to Step 12. `pre-ship-check` will offer one more chance at ship time if no QA evidence is found on Asana.

### Step 12: Ship It

**This step runs after the bug QA verify loop (for bugs) or the non-bug QA verification (for non-bugs) completes — or when the operator skips QA.** Do not wait for the user to ask.

Invoke `ship-it`. The following context is already in this session — pass it through, do not re-ask:

| What | Source |
|------|--------|
| Task GID | Extracted in Step 1 |
| Task URL | Provided in `$ARGUMENTS` |
| Task ID | From task custom fields (Step 2) |
| Branch name | Created in Step 7 |
| Draft PR URL | Captured in Step 8 |
| Sprint project GID | From board cache `active_sprint.gid` (loaded in Step 3) |
| Section mappings | Discovered when moving to "In Progress" (Step 9a) |

`ship-it` will run pre-ship-check, generate a work summary, promote the draft PR to ready, move the Asana task to "In Review", and post a completion comment.

After `ship-it` returns successfully, delete `~/.claude/asana-workflow/checkpoints/<task-gid>.md` (via `checkpoint.sh delete <gid>`). Post-ship work (code-review fixes, follow-up commits) is out of scope for this checkpoint — see **`references/checkpoints.md`** → "Lifecycle End".

## Pause Flow

Triggered either by a step going into `State = blocked` during the flow or by the operator saying "park this", "I'm blocked", "pause task", or similar. Commits WIP, drafts a blocking question for user approval, posts to Asana (@mentioning the blocker), updates the checkpoint, and pushes. See **`references/checkpoints.md`** → "Pause Flow" for the full sequence and **`references/asana-patterns.md`** for the Asana comment formats.

## Important Notes

- This skill orchestrates the full lifecycle: start → develop → ship. It hands off to `ship-it` when development is done.
- Include the task ID in branch names and commit messages for traceability.
- Route all Asana API calls through the `asana-api` skill — no raw curl.

## Reference Files

- **`references/skill-dependencies.md`** — External plugin dependencies, install commands, check instructions
- **`references/validation-rules.md`** — Sprint-readiness checks, failure display, skip rules
- **`references/asana-patterns.md`** — URL formats, API fields, section moves, comment posting
- **`references/git-workflow.md`** — Existing work detection, branch creation, naming convention
- **`references/checkpoints.md`** — Checkpoint file format, initialization, per-step updates, resume flow, lifecycle end, edge cases
- **`plugins/asana-workflow/references/qa-routing.md`** — QA skill resolution and the QA sub-flow (plugin-level shared reference with pre-ship-check)
