# Skill Dependencies

`start-task` orchestrates several external skills that are **not bundled** with the `asana-workflow` plugin. These must be installed separately before start-task can route work correctly.

## Required External Skills

### `feature-dev:feature-dev`
- **Plugin:** `feature-dev@claude-plugins-official`
- **Used for:** Routing Feature Request, Tech Debt, and all non-bug task categories (Step 10)
- **Install:**
  ```
  /plugin install feature-dev@claude-plugins-official
  ```

### `superpowers:systematic-debugging`
- **Plugin:** `superpowers@claude-plugins-official`
- **Used for:** Root cause investigation inside `fix-bug` (Step 1 of fix-bug, invoked when start-task routes a Bug category task)
- **Install:**
  ```
  /plugin install superpowers@claude-plugins-official
  ```

### `superpowers:brainstorming` _(optional)_
- **Plugin:** `superpowers@claude-plugins-official` _(same as above)_
- **Used for:** Brainstorm workflow for non-bug tasks when `brainstorm` argument is passed to start-task (Step 10)
- **Install:** Included with `superpowers` above

### `superpowers:using-git-worktrees` _(optional)_
- **Plugin:** `superpowers@claude-plugins-official` _(same as above)_
- **Used for:** Worktree setup if user chooses worktree mode in Step 6a
- **Install:** Included with `superpowers` above

## How to Check If Dependencies Are Installed

Before routing in Step 10, verify the required skill is available by checking if its trigger phrases are recognized. If a skill is missing, Claude cannot invoke it.

To check installed plugins:

```bash
# List installed plugins — match JSON keys like "feature-dev@..." or "superpowers@..."
cat ~/.claude/plugins/installed_plugins.json | grep -E '"feature-dev|"superpowers'
```

## Dependency Check at Start-Task Launch (Step 0)

At the very beginning of start-task (before fetching the Asana task), check which routing path may be needed and confirm the relevant plugin is installed.

**If `feature-dev` is missing:**

> ⚠️ The `feature-dev` plugin is required for feature and tech debt tasks but doesn't appear to be installed.
> Install it with: `/plugin install feature-dev@claude-plugins-official`
> Continue anyway and install manually before Step 10, or install now and re-run `/start-task`.

**If `superpowers` is missing:**

> ⚠️ The `superpowers` plugin is required for bug tasks (via `fix-bug`) and for the brainstorm workflow on non-bug tasks, but doesn't appear to be installed.
> Install it with: `/plugin install superpowers@claude-plugins-official`
> Continue anyway and install manually before Step 10, or install now and re-run `/start-task`.

**Behavior:** These checks are **advisory**, not hard-blocking — the user may know the task type in advance and only need one of the two. Warn clearly, then ask:

> The task category will determine which skill is invoked at Step 10. Do you want to install the missing plugin(s) now, or continue?

Wait for the user's answer before proceeding.

## Bundled Skills (No Installation Needed)

These skills are included in the `asana-workflow` plugin itself:

| Skill | Purpose |
|---|---|
| `asana-workflow:asana-api` | All Asana API calls |
| `asana-workflow:git-check` | Git state validation |
| `asana-workflow:pre-ship-check` | Readiness gate |
| `asana-workflow:work-summary` | Session summary |
| `asana-workflow:create-pr` | PR creation |
| `asana-workflow:ship-it` | Shipping orchestrator |
| `asana-workflow:web-qa` | Web QA investigation & verification |
| `asana-workflow:mobile-qa` | Mobile QA investigation & verification |
