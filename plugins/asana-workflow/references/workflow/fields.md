# Workflow Fields (neutral)

The canonical fields the siroc workflow uses, by meaning. Provider-agnostic: this file names no task manager and holds no field identifiers. A provider skill is responsible for discovering and mapping each field in its own system; concrete identifiers live in the machine-local cache.

| Field | Meaning |
|-------|---------|
| Key | The human-readable task identifier (e.g. `ABC-123`); read-only, provider-assigned. A first-class attribute, not a custom field. |
| Assignee | The person responsible for the task. Treated as a first-class attribute, not a custom field. |
| Platform | Which platform the work targets. |
| Priority | Urgency / severity of the task. |
| Sizing | Relative size estimate (story points / t-shirt). |
| Estimate | Expected effort. Input is flexible (decimal hours, `hh:mm`, `1h 30m`); the stored unit and display format are provider-defined. |
| Type / Category | The kind of work (Bug, Feature/Story, Task…). A provider may realize it as a native issue type (e.g. Jira) or as a custom field (e.g. Asana). Used for routing (e.g. Bug → bug flow). |
| Labels | Free-form tags on a task. |
| Parent / Epic | The task's parent or epic membership (hierarchy). |
| Product Status | Where the task sits in the lifecycle (see `lifecycle.md`). |

Not every board carries every field. A missing field is skipped gracefully, never invented.

`Estimate` and `Sizing` are siroc workflow conventions, not universal task-manager primitives — providers map them onto whatever native mechanism exists. `Sizing` may be the provider's native estimate (e.g. Jira story points) while `Estimate` (time) is secondary.
