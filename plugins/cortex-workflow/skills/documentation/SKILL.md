---
name: documentation
version: 0.1.0
description: >
  Use when a task is done and verified, before shipping, committing the final change or opening a
  pull request, to bring the project's documentation in line with what the task changed. Also use
  when the user asks to refresh, update or check the docs for this branch or recent work. Never run
  it mid-task, while tests fail, or for a one-off doc edit, release notes or a changelog.
---

# Documentation

Make every guide the task touched describe the project as it is after the change. Run it once the work is done and verified: documenting unfinished work records behavior that may still change. If the work is still in progress or failing, stop and say so.

## Inputs from the invoker (all optional)

- `commit: true` — commit the edits (see Finish). Without it, leave them in the working tree.
- `unattended: true` — never ask; make factual edits only and list anything that needs judgment in the report.

## Step 1: Learn the project's documentation rules

Read the project's instruction and contributor files (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, the README's contributing section). Note where current documentation lives, where plans, specs and dated notes go, and any rule about how docs are written. Those rules override the defaults below.

## Step 2: Find what changed

1. Base: the merge-base with the default branch (`git merge-base HEAD origin/<default>`), or the fixed point the invoker names. Include uncommitted changes.
2. Read `git diff --stat <base>` first, then the diffs that matter, one file at a time.
3. List each change a reader of the docs would notice: behavior, commands, flags, CLI output, settings, environment variables, file locations, UI labels, states, error messages, contracts between components, limits and known gaps. Refactors and test-only changes usually have none — say so and go to Finish.

## Step 3: Find the documentation that covers it

Search tracked docs for each change's names (function, command, flag, setting, label, file) and for the concept it belongs to: the docs directory, the README, agent instruction files, skill or prompt files, and help text or in-app copy the task did not already update. A guide that describes the behavior without naming it is a candidate too, so search by concept as well as by name.

## Step 4: Update it

- Edit the existing guide. Create a new page only when nothing covers the area, and link it from the closest existing one.
- Describe current behavior in the present tense. Never write history — "now", "previously", "no longer", "as of this change", dates, ticket narratives. History belongs in the PR, the task and git.
- Plans, specs, research and verification notes go wherever the project keeps working notes, never in a guide.
- Fix what sits next to your edit: a statement in the same section that the code now contradicts gets corrected. Leave unrelated sections alone.
- Check every claim against the code, not the diff summary or memory of the task: names, defaults, paths, flags and commands must match what the code does. Run a documented command when it is cheap.
- Match the guide's voice, heading depth and table style.
- Removing a section or rewriting more than a paragraph is a judgment call: ask first (unattended: skip it and list it in the report).

## Finish

1. Run the project's formatter or linter if it covers the files you edited.
2. With `commit: true` and at least one edit: stage the edited files by name and make one conventional commit, `docs(<scope>): <what the docs now cover>`. Never push.
3. Report to the invoker:

```
Documentation: <updated N files | up to date>
- <path> — <one line on what it now says>
No change needed: <change> — <reason>
Needs judgment: <item>            (only when something was skipped)
Commit: <sha | none>
```

Then return control to the invoking workflow, or stop when invoked standalone.
