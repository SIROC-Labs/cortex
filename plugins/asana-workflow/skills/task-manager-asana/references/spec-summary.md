# Asana API Endpoints (Auto-Generated)

> Updated: 2026-03-20
> Source: https://raw.githubusercontent.com/Asana/openapi/master/defs/asana_sdk_oas.yaml

**Total:** 232 endpoints across 45 resources

## Access requests

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/access_requests` | `getAccessRequests` | Get access requests |
| `POST` | `/access_requests` | `createAccessRequest` | Create an access request |
| `POST` | `/access_requests/{access_request_gid}/approve` | `approveAccessRequest` | Approve an access request |
| `POST` | `/access_requests/{access_request_gid}/reject` | `rejectAccessRequest` | Reject an access request |

## Allocations

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/allocations` | `getAllocations` | Get multiple allocations |
| `POST` | `/allocations` | `createAllocation` | Create an allocation |
| `DELETE` | `/allocations/{allocation_gid}` | `deleteAllocation` | Delete an allocation |
| `GET` | `/allocations/{allocation_gid}` | `getAllocation` | Get an allocation |
| `PUT` | `/allocations/{allocation_gid}` | `updateAllocation` | Update an allocation |

## Attachments

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/attachments` | `getAttachmentsForObject` | Get attachments from an object |
| `POST` | `/attachments` | `createAttachmentForObject` | Upload an attachment |
| `DELETE` | `/attachments/{attachment_gid}` | `deleteAttachment` | Delete an attachment |
| `GET` | `/attachments/{attachment_gid}` | `getAttachment` | Get an attachment |

## Batch API

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `POST` | `/batch` | `createBatchRequest` | Submit parallel requests |

## Events

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/events` | `getEvents` | Get events on a resource |

## Goals

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/goals` | `getGoals` | Get goals |
| `POST` | `/goals` | `createGoal` | Create a goal |
| `DELETE` | `/goals/{goal_gid}` | `deleteGoal` | Delete a goal |
| `GET` | `/goals/{goal_gid}` | `getGoal` | Get a goal |
| `PUT` | `/goals/{goal_gid}` | `updateGoal` | Update a goal |

## Memberships

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/memberships` | `getMemberships` | Get multiple memberships |
| `POST` | `/memberships` | `createMembership` | Create a membership |
| `DELETE` | `/memberships/{membership_gid}` | `deleteMembership` | Delete a membership |
| `GET` | `/memberships/{membership_gid}` | `getMembership` | Get a membership |
| `PUT` | `/memberships/{membership_gid}` | `updateMembership` | Update a membership |

## Projects

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/projects` | `getProjects` | Get multiple projects |
| `POST` | `/projects` | `createProject` | Create a project |
| `DELETE` | `/projects/{project_gid}` | `deleteProject` | Delete a project |
| `GET` | `/projects/{project_gid}` | `getProject` | Get a project |
| `PUT` | `/projects/{project_gid}` | `updateProject` | Update a project |
| `GET` | `/projects/{project_gid}/sections` | `getSectionsForProject` | Get sections in a project |
| `GET` | `/projects/{project_gid}/task_counts` | `getTaskCountsForProject` | Get task count of a project |
| `GET` | `/tasks/{task_gid}/projects` | `getProjectsForTask` | Get projects a task is in |

## Sections

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/projects/{project_gid}/sections` | `getSectionsForProject` | Get sections in a project |
| `POST` | `/projects/{project_gid}/sections` | `createSectionForProject` | Create a section in a project |
| `DELETE` | `/sections/{section_gid}` | `deleteSection` | Delete a section |
| `GET` | `/sections/{section_gid}` | `getSection` | Get a section |
| `PUT` | `/sections/{section_gid}` | `updateSection` | Update a section |
| `POST` | `/sections/{section_gid}/addTask` | `addTaskForSection` | Add task to section |

## Stories

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `DELETE` | `/stories/{story_gid}` | `deleteStory` | Delete a story |
| `GET` | `/stories/{story_gid}` | `getStory` | Get a story |
| `PUT` | `/stories/{story_gid}` | `updateStory` | Update a story |
| `GET` | `/tasks/{task_gid}/stories` | `getStoriesForTask` | Get stories from a task |
| `POST` | `/tasks/{task_gid}/stories` | `createStoryForTask` | Create a story on a task |

## Tags

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/tags` | `getTags` | Get multiple tags |
| `POST` | `/tags` | `createTag` | Create a tag |
| `DELETE` | `/tags/{tag_gid}` | `deleteTag` | Delete a tag |
| `GET` | `/tags/{tag_gid}` | `getTag` | Get a tag |
| `PUT` | `/tags/{tag_gid}` | `updateTag` | Update a tag |
| `GET` | `/tasks/{task_gid}/tags` | `getTagsForTask` | Get a task's tags |

## Tasks

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/projects/{project_gid}/tasks` | `getTasksForProject` | Get tasks from a project |
| `GET` | `/sections/{section_gid}/tasks` | `getTasksForSection` | Get tasks from a section |
| `GET` | `/tasks` | `getTasks` | Get multiple tasks |
| `POST` | `/tasks` | `createTask` | Create a task |
| `DELETE` | `/tasks/{task_gid}` | `deleteTask` | Delete a task |
| `GET` | `/tasks/{task_gid}` | `getTask` | Get a task |
| `PUT` | `/tasks/{task_gid}` | `updateTask` | Update a task |
| `POST` | `/tasks/{task_gid}/addDependencies` | `addDependenciesForTask` | Set dependencies for a task |
| `POST` | `/tasks/{task_gid}/addProject` | `addProjectForTask` | Add a project to a task |
| `POST` | `/tasks/{task_gid}/addTag` | `addTagForTask` | Add a tag to a task |
| `GET` | `/tasks/{task_gid}/dependencies` | `getDependenciesForTask` | Get dependencies from a task |
| `POST` | `/tasks/{task_gid}/duplicate` | `duplicateTask` | Duplicate a task |
| `POST` | `/tasks/{task_gid}/setParent` | `setParentForTask` | Set the parent of a task |
| `GET` | `/tasks/{task_gid}/subtasks` | `getSubtasksForTask` | Get subtasks from a task |
| `POST` | `/tasks/{task_gid}/subtasks` | `createSubtaskForTask` | Create a subtask |
| `GET` | `/workspaces/{workspace_gid}/tasks/search` | `searchTasksForWorkspace` | Search tasks in a workspace |

## Teams

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `POST` | `/teams` | `createTeam` | Create a team |
| `GET` | `/teams/{team_gid}` | `getTeam` | Get a team |
| `PUT` | `/teams/{team_gid}` | `updateTeam` | Update a team |
| `POST` | `/teams/{team_gid}/addUser` | `addUserForTeam` | Add a user to a team |
| `POST` | `/teams/{team_gid}/removeUser` | `removeUserForTeam` | Remove a user from a team |

## Users

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/users` | `getUsers` | Get multiple users |
| `GET` | `/users/{user_gid}` | `getUser` | Get a user |
| `GET` | `/users/{user_gid}/favorites` | `getFavoritesForUser` | Get a user's favorites |

## Webhooks

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/webhooks` | `getWebhooks` | Get multiple webhooks |
| `POST` | `/webhooks` | `createWebhook` | Establish a webhook |
| `DELETE` | `/webhooks/{webhook_gid}` | `deleteWebhook` | Delete a webhook |
| `GET` | `/webhooks/{webhook_gid}` | `getWebhook` | Get a webhook |
| `PUT` | `/webhooks/{webhook_gid}` | `updateWebhook` | Update a webhook |

## Workspaces

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `GET` | `/workspaces` | `getWorkspaces` | Get multiple workspaces |
| `GET` | `/workspaces/{workspace_gid}` | `getWorkspace` | Get a workspace |
| `PUT` | `/workspaces/{workspace_gid}` | `updateWorkspace` | Update a workspace |

## Custom fields

| Method | Path | SDK Method | Description |
|--------|------|------------|-------------|
| `POST` | `/custom_fields` | `createCustomField` | Create a custom field |
| `DELETE` | `/custom_fields/{custom_field_gid}` | `deleteCustomField` | Delete a custom field |
| `GET` | `/custom_fields/{custom_field_gid}` | `getCustomField` | Get a custom field |
| `PUT` | `/custom_fields/{custom_field_gid}` | `updateCustomField` | Update a custom field |
| `POST` | `/custom_fields/{custom_field_gid}/enum_options` | `createEnumOptionForCustomField` | Create an enum option |
