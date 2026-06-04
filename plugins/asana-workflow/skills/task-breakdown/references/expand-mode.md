# Expand Mode

Expand the tasks for a single, already-authored milestone. This mode runs when the user wants to focus a session on one milestone's tasks — typically after a prior session authored milestone-first and stopped before expansion, or to refine/extend an existing milestone's tasks.

## Triggers

Three input shapes activate EXPAND mode:

1. **Direct milestone-task URL**
   `/task-breakdown https://app.asana.com/.../task/<gid>`
   Skill fetches the task and verifies `resource_subtype == "milestone"`. If the subtype is not `milestone`, this is not an EXPAND trigger — fall back to PLAN mode.

2. **Project URL + milestone name**
   `/task-breakdown https://app.asana.com/.../project/<gid> expand milestone "Employee Management"`
   Skill fetches the project's sections, finds the section by name, lists tasks in that section, and locates the `resource_subtype == "milestone"` task inside it. Confirm the match with the user before proceeding.

3. **Breakdown md file + M-label hint**
   `/task-breakdown docs/cortex/task-breakdowns/<file>.md M3`
   Md-driven; the user picks an M-label whose block has no tasks under it. Asana is not consulted at this stage — the milestone block's content drives expansion. (Submit-breakdown will reconcile with Asana later.)

## Flow

### Step 1: Resolve target milestone

- Fetch the milestone task (Asana) or load the milestone block (md).
- For trigger #2: explicitly confirm the matched milestone with the user before proceeding.
- **Pre-flight: "milestone has not been expanded yet"** means the section contains zero tasks with `resource_subtype == "default_task"`. The milestone-subtype task itself doesn't count.
  - If the section already has implementation tasks, ask the user: "M2 already has N implementation tasks. Add more, or stop?" Default to stop. Continue only on explicit confirmation.

### Step 2: Load context from Asana ONLY (for triggers #1 and #2)

Read the milestone task description into a structured form:

- Purpose
- Description
- Product Requirements
- Acceptance Criteria
- Out of scope (if present)
- References

Then follow each reference:

- Repo file paths → Read tool
- Figma URLs → `mcp__claude_ai_Figma__get_design_context` if Figma context is needed for the milestone
- Asana cross-task URLs → asana-api fetch
- External URLs → WebFetch

**Never look for a breakdown md file in the repo.** The Asana milestone task description is canonical. (Trigger #3 is the exception: md is the source by definition.)

### Step 3: Decompose into tasks

Apply `references/decomposition-principles.md`:

- One platform per task
- Single-session sized (00:30–04:00)
- Foundational before dependent, read before write, backend before frontend, design before implementation
- Cleanup task when the milestone earns one

### Step 4: Validate

Run `references/decomposition-principles.md` validation checks: platform / size / split / redundancy. Resolve issues before writing the output file.

### Step 5: Write a local single-milestone markdown file

Path: `<repo-root>/docs/cortex/task-breakdowns/<YYYY-MM-DD>-<project-slug>-<milestone-slug>.md`

File contents:

- File header (overall title, Delivers, file-level References — copied from the milestone's References if no broader context exists)
- One milestone block (rendered from the Asana milestone task description, in the rich format from `output-format.md`)
- The expanded task entries under that milestone block

This is a single-milestone working artifact for `submit-breakdown` to consume.

### Step 6: Offer to submit

> "Expanded M2 into N tasks. Saved to `<path>`. Want to submit it to Asana now? [Y/n]"

If yes, hand off to `submit-breakdown`. On submit, the existing milestone task is detected by `(section, name, resource_subtype == "milestone")` and reused; only the new implementation tasks are created.
