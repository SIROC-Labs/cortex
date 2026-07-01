# Task Patterns

Comment templates `start-task` authors and posts through the `task-manager` interface. Author each body as Markdown and post it via `add_comment(task, body)`; the provider converts. To read comments back, use `get_comments(task)`.

## Posting the Start Comment

Post a comment on the task (only if one with the flag emoji doesn't already exist for this branch):

> 🏁 Starting work — branch: `<task-id>/<slug>`
> PR: `<draft-pr-url>`

Include the draft PR URL so teammates can find the GitHub PR from the task immediately. The counterpart is 🚀 posted by `ship-it` when the work ships.

## Posting a Blocking Question (Pause)

When pausing a task (see `checkpoints.md` → "Pause Flow"), draft a blocking question and present it for user approval before posting. Never post without explicit approval.

Format the comment to @mention the person who should answer:

> @Maria — Need clarification: should the CSV export include filtered-out rows as a separate sheet, or exclude them entirely? This blocks the export logic implementation.

## Posting a Resume Comment

When resuming work on a previously blocked task, post a brief comment for team visibility:

> Resuming work on branch `<task-id>/<slug>`

## Checking for Answers on Resume

On resume, if the resuming row has `State = blocked`, fetch the task's comments via `get_comments(task)` and keep only those created after the checkpoint's `last_updated` timestamp. Present any new comments as potential answers to the blocking question.
