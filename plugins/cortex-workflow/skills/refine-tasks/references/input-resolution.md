# Input Resolution

`refine-tasks` accepts any input that resolves to a **deterministic, ordered list of tasks** in Refinement status. This reference defines the resolution rules. All task and board resolution goes through the `task-manager` interface — this skill never parses provider URLs or addresses tasks by raw identifier.

## Accepted Input Shapes

### 1. One or more task URLs

Resolve each URL to a task handle via `find_task(ref)`. The provider extracts whatever identifier it needs from the URL; the skill only holds the returned handle.

If multiple URLs are provided, resolve each independently. Order them by their dependencies once status filtering is done.

### 2. A project URL + milestone (grouping) name

User says something like:

- "refine M1 in this project: <project-url>"
- "refine the Core Data Layer milestone: <project-url>"
- "/refine-tasks <project-url> M1"

Resolve by:
1. Resolve the project from the URL via the `task-manager` interface.
2. List the project's groupings (milestones) through the interface.
3. Match the grouping by:
   - **Exact name** (e.g., `M1 :: Core Data Layer`)
   - **`M<n>` prefix** (e.g., user says "M1", match the grouping whose name starts with `M1 ::`)
   - **Substring on the descriptive part** (e.g., "Core Data Layer" matches `M1 :: Core Data Layer`)
4. If multiple groupings match, show the candidates and ask the user to pick.
5. List the tasks in that grouping via the interface.

### 3. A project URL alone

Implies "every task in Refinement status across the project."

1. Resolve the project from the URL.
2. List all tasks in the project (across all groupings) through the interface.
3. Phase 1 then filters down to Refinement status only.
4. Order by dependencies.

This shape is for bulk refinement runs. If the resolved set is large (>10 tasks), surface the count in the confirmation prompt and let the user narrow down before proceeding.

### 4. A project URL + user-described filter

User says something like:

- "refine all backend Refinement tasks in M2"
- "refine the Refinement tasks that depend on the Employee entity task"
- "<project-url> — refine only backend tasks"

For these cases:

1. Resolve the broader scope (project, optionally grouping).
2. Apply the user's filter on the fetched task list. Common filters:
   - **Platform:** filter by the Platform field's value.
   - **Dependencies:** filter by dependency relationships (e.g., tasks that depend on a specific task).
   - **Title substring:** filter by name match.
3. If the filter is ambiguous (e.g., "backend tasks" but the project doesn't use the Platform field), surface the ambiguity to the user before proceeding.

---

## Ordering by Dependencies

After status filtering, sort tasks topologically:

1. Fetch each task's dependency relationships via `get_task(task)`.
2. Build a directed graph: an edge from A → B if A depends on B.
3. Topological sort. If a cycle exists (unexpected — task managers usually reject cycles), warn the user and proceed in the original order.

Tasks whose dependencies are *outside* the current refinement set are fine — they go where they normally would by the sort.

---

## The Confirmation Prompt

After resolution and ordering, always show the user the resolved set before proceeding:

```
About to refine 4 tasks (in dependency order):
  1. Employee entity + repository
  2. Employee CRUD API endpoints
  3. Employee list page
  4. Employee create/edit form
Proceed? [Y/n]
```

If 0 tasks resolved, abort with:

> No tasks matched the input in Refinement status. Either: (a) the resolved set is empty, (b) all matched tasks are in a different Product Status, or (c) the input couldn't be resolved. Tasks must be in Refinement to be refined — adjust status manually if you intended to re-refine.

If many tasks resolved (>10), warn before proceeding:

> 14 tasks resolved in Refinement status. Refinement reads the codebase and asks per-task questions, which can take 5–10 minutes per task. Proceed with all 14, or narrow down?
> 1. Proceed with all
> 2. Narrow down (specify milestone, platform, or specific T-labels)
