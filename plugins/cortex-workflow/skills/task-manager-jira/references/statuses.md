# Jira status mapping

> The neutral lifecycle is defined in `../../../references/workflow/lifecycle.md`. This file maps those neutral names onto Jira statuses. Not a skill — referenced from `../SKILL.md`.

Jira models the whole lifecycle as **one transition-driven `status` field** (not a separate board-column axis). `set_status` is realized via `acli jira workitem transition --key <KEY> --status "<name>" --yes`, where `<name>` is the **target status name** and `acli` resolves the transition.

## Map by statusCategory, not by literal name

Status **names are project-configurable** and vary per instance; **categories are stable**. Every Jira status carries `status.statusCategory.key`, always one of three universal values:

| Category key | Category name | Typical statuses |
|---|---|---|
| `new` | To Do | `New`, `Backlog`, `To Do`, `Selected for Development` |
| `indeterminate` | In Progress | `In Progress`, `In Review`, `Test & Review`, `Code Review` |
| `done` | Done | `Done`, `Ready`, `Closed`, `Resolved`, `Won't do`, `Cancelled` |

Gate and classify on `statusCategory.key` (portable), not on specific status names.

## Neutral lifecycle → Jira statusCategory

The neutral lifecycle collapses onto Jira's three categories:

| Neutral state | statusCategory | Notes |
|---|---|---|
| Requirements | `new` | not-started bucket |
| Sizing | `new` | not-started bucket |
| Refinement | `new` | not-started bucket |
| Unassigned | `new` | not-started bucket |
| Scheduled | `new` | not-started bucket |
| Assigned | `new` | not-started bucket |
| In Progress | `indeterminate` | active work |
| In Review | `indeterminate` | active work |
| Ready | `done` | cleared for release / downstream handoff |
| Done | `done` | merged / closed |
| Cancelled | `done` | terminal exit (e.g. `Won't do`) |

Several neutral "not-started" states (`Unassigned`, `Scheduled`, `Assigned`, etc.) all map onto the single `new` bucket — Jira does not distinguish them as separate statuses unless the project's workflow happens to define matching status names. Do **not** assume a neutral state survives a 1:1 round-trip.

## Resolving a target status name for a transition

`set_status(task, <neutral-name>)`:

1. Determine the target `statusCategory` from the table above.
2. List the issue's available transition targets and their categories (each transition leads to a status with a `statusCategory.key`). The transition targets can be read from the issue, e.g. `GET /rest/api/3/issue/<KEY>/transitions` (each entry's `to.statusCategory.key`), or by inspecting the project's workflow.
3. Pick the status whose category matches; if several match, prefer the one whose name best matches the neutral intent (e.g. neutral `In Review` → a Jira status named like "Review"/"Test & Review" within `indeterminate`).
4. Pass that exact status **name** to `acli jira workitem transition --status "<name>"` (strict name comparison).

If a project has well-known fixed names, they may be recorded in the machine-local `~/.cortex/` cache to skip the lookup — never hard-coded in this reference, since names differ per instance.

## Validation gate

For readiness checks ("is this issue startable?"), gate on the category, not the name:

| Category | Meaning | Behavior |
|---|---|---|
| `new` | not started | ready to pick up |
| `indeterminate` | active | already started — confirm resume |
| `done` | closed | must reopen first |
