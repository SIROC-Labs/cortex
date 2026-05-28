# Asana Patterns

## URL Formats and GID Extraction

Asana URLs come in several formats. The task GID is always a numeric segment:

- `https://app.asana.com/0/<project-gid>/<task-gid>`
- `https://app.asana.com/0/<project-gid>/<task-gid>/f`
- `https://app.asana.com/1/<org-gid>/project/<project-gid>/task/<task-gid>`
- `https://app.asana.com/1/<org-gid>/inbox/<inbox-gid>/item/<task-gid>/...`

Extract the numeric segment that corresponds to the task.

## API Fields for Task Fetch

Request the following `opt_fields` when fetching task details:

```
name,notes,assignee,assignee.gid,assignee.name,custom_fields,custom_fields.name,
custom_fields.display_value,custom_fields.enum_value,custom_fields.enum_value.name,
custom_fields.type,memberships,memberships.project,memberships.project.name,
memberships.section,memberships.section.name,projects,projects.name
```

### Task Summary Fields

Present a quick summary for confirmation:
- **Task name**
- **Assignee**
- **Category** (from custom field)
- **Task ID** (e.g., MT251-47)
- **Sprint** (e.g., "ENG | Sprint 25.12")

## Subtask Fetch

Fetch subtasks with `opt_fields=name,completed,gid`. Group by status:
- Incomplete subtasks — remaining work
- Completed subtasks — already done (may indicate partially-completed work)

Include subtasks in downstream context so feature-dev or debugging understands what "done" looks like.

## Comments and Attachments

Fetch task stories (comments) and filter for `type: "comment"` to get human-written context.

### Attachments

List attachments by calling:

```
GET /tasks/<task-gid>/attachments?opt_fields=name,resource_subtype,download_url,parent.gid,host
```

Classify each attachment:

- **Image** — mime type starts with `image/`, or filename extension is `.png`, `.jpg`, `.jpeg`, `.gif`, or `.webp`. Note in the task summary so the user can open it in Asana if relevant; do not download.
- **Non-image** — every other attachment (markdown, PDF, plain text, JSON, etc.). Download the file via `download_url`. Include the body in the task context bundle passed to the routed sub-skill in Step 10.

This generic handling lets `start-task` consume any document that earlier-stage skills attach to a task (for example, `implementation-plan.md` from `refine-tasks`) without coupling to a specific filename.

If a non-image attachment is unreasonably large (>200 KB), summarize first 200 KB and note that the body was truncated.

## Fetching the Current User

```
GET /users/me?opt_fields=gid,name
```

Returns the authenticated user's GID and name. Use this in Step 2a to compare against `task.assignee.gid`.

## Assigning or Reassigning a Task

```
PUT /tasks/<task-gid>
Body: {"data":{"assignee":"me"}}
```

Use `"me"` as the assignee value — Asana resolves it to the authenticated user automatically.

## Moving to In Progress

Automatically move the task to "In Progress" on the Sprint board — no need to prompt for permission. The intent to start is implicit.

1. Check the task's current section (from memberships data). If already "In Progress", skip.
2. List sections in the Sprint project:
   ```
   GET /projects/<sprint-project-gid>/sections?opt_fields=name
   ```
3. Find the section named "In Progress".
4. Move the task:
   ```
   POST /sections/<in-progress-section-gid>/addTask
   Body: {"data":{"task":"<task-gid>"}}
   ```

If the move fails, report why but do not block the workflow.

## Posting the Start Comment

Post a comment on the task (only if one with the flag emoji doesn't already exist for this branch):

> 🏁 Starting work — branch: `<task-id>/<slug>`
> PR: `<draft-pr-url>`

Include the draft PR URL so teammates can find the GitHub PR from Asana immediately. The counterpart is 🚀 posted by `ship-it` when the work ships.

**Formatting:** post via the `asana-api` skill's `data.text` field (plain text — no HTML). Asana auto-links the PR URL.

## Posting a Blocking Question (Pause)

When pausing a task (see `checkpoints.md` → "Pause Flow"), draft a blocking question and present it for user approval before posting. Never post without explicit approval.

Format the comment to @mention the person who should answer:

> @Maria — Need clarification: should the CSV export include filtered-out rows as a separate sheet, or exclude them entirely? This blocks the export logic implementation.

## Checking for Answers on Resume

On resume, if the resuming row has `State = blocked`, fetch task stories posted after the checkpoint's `last_updated` timestamp:

```
GET /tasks/<task-gid>/stories?opt_fields=text,created_by.name,type,created_at
```

Filter for `type: "comment"` and `created_at` after `last_updated`. Present any new comments as potential answers to the blocking question.

## Posting a Resume Comment

When resuming work on a previously blocked task, post a brief comment for team visibility:

> Resuming work on branch `<task-id>/<slug>`

## All Asana API Calls

Route all Asana API operations through the `asana-api` skill — do not use raw curl directly.
