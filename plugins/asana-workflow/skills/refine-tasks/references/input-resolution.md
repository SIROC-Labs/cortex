# Input Resolution

`refine-tasks` accepts any input that resolves to a **deterministic, ordered list of Asana task GIDs** in Refinement status. This reference defines the resolution rules.

## Accepted Input Shapes

### 1. One or more Asana task URLs

```
https://app.asana.com/0/<project_gid>/<task_gid>
https://app.asana.com/0/<project_gid>/<task_gid>/f
```

Extract the task GID — the trailing numeric segment that corresponds to the task. Asana URLs come in several shapes; the parser should handle these forms (always extracting the segment that is the task GID, not the project / org / inbox):

- `https://app.asana.com/0/<project_gid>/<task_gid>`
- `https://app.asana.com/0/<project_gid>/<task_gid>/f`
- `https://app.asana.com/1/<org_gid>/project/<project_gid>/task/<task_gid>`
- `https://app.asana.com/1/<org_gid>/inbox/<inbox_gid>/item/<task_gid>/...`

If multiple URLs are provided, resolve each independently. Order them by their dependencies once status filtering is done.

### 2. A project URL + milestone (section) name

User says something like:

- "refine M1 in this project: <project-url>"
- "refine the Core Data Layer milestone: <project-url>"
- "/refine-tasks <project-url> M1"

Resolve by:
1. Parse the project GID from the URL.
2. List sections in the project: `GET /projects/<project_gid>/sections?opt_fields=name`.
3. Match the section by:
   - **Exact name** (e.g., `M1 :: Core Data Layer`)
   - **`M<n>` prefix** (e.g., user says "M1", match the section whose name starts with `M1 ::`)
   - **Substring on the descriptive part** (e.g., "Core Data Layer" matches `M1 :: Core Data Layer`)
4. If multiple sections match, show the candidates and ask the user to pick.
5. List tasks in that section.

### 3. A project URL alone

Implies "every task in Refinement status across the project."

1. Parse the project GID.
2. List all tasks in the project (across all sections).
3. Phase 1 then filters down to Refinement status only.
4. Order by dependencies.

This shape is for bulk refinement runs. If the resolved set is large (>10 tasks), surface the count in the confirmation prompt and let the user narrow down before proceeding.

### 4. A project URL + user-described filter

User says something like:

- "refine all backend Refinement tasks in M2"
- "refine the Refinement tasks that depend on the Employee entity task"
- "<project-url> — refine only backend tasks"

For these cases:

1. Resolve the broader scope (project, optionally section).
2. Apply the user's filter on the fetched task list. Common filters:
   - **Platform:** filter by the Platform custom field's enum value.
   - **Dependencies:** filter by `dependencies` field (e.g., tasks that depend on a specific GID).
   - **Title substring:** filter by name match.
3. If the filter is ambiguous (e.g., "backend tasks" but the project doesn't use the Platform field), surface the ambiguity to the user before proceeding.

---

## Ordering by Dependencies

After status filtering, sort tasks topologically:

1. Fetch each task's `dependencies` array (Asana API field `dependencies` on a task).
2. Build a directed graph: an edge from A → B if B is in A's `dependencies` (i.e., A depends on B).
3. Topological sort. If a cycle exists (unexpected — Asana usually rejects cycles), warn the user and proceed in the original order.

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
