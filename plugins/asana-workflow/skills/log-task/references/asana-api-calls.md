# Asana API Calls Reference

All calls require `Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN`.

## Discover custom fields for a project

```bash
curl -s -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  "https://app.asana.com/api/1.0/projects/<active_sprint_gid>/custom_field_settings\
?opt_fields=custom_field.gid,custom_field.name,custom_field.type,\
custom_field.enum_options,custom_field.enum_options.gid,custom_field.enum_options.name"
```

## Fetch current user

```bash
curl -s -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  "https://app.asana.com/api/1.0/users/me?opt_fields=gid,name,email"
```

## 6a. Create the task

**Do NOT include custom fields here** — the Asana API rejects them until the task belongs to a project.

```bash
curl -s -X POST -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "name": "<title>",
      "notes": "<description>",
      "workspace": "<workspace_gid>",
      "assignee": "<user_gid or null>"
    }
  }' \
  "https://app.asana.com/api/1.0/tasks"
```

Save the returned `task_gid`. Send `"assignee": null` explicitly for Plan Only.

## 6b. Add to Sprint project

```bash
curl -s -X POST -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"data":{"project":"<active_sprint_gid>"}}' \
  "https://app.asana.com/api/1.0/tasks/<task_gid>/addProject"
```

The `<active_sprint_gid>` comes from the board cache's `active_sprint.gid`.

## 6c. Add to Backlog boards

Loop over the user-confirmed backlog boards. Call `addProject` once per board:

```bash
# Repeat for each confirmed backlog board GID
curl -s -X POST -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"data":{"project":"<backlog_board_gid>"}}' \
  "https://app.asana.com/api/1.0/tasks/<task_gid>/addProject"
```

A task can belong to multiple projects — each call adds one membership. If any single call fails, report the error but continue with the remaining boards.

## 6d. Set custom fields

Only after the task is in a project. Only include fields that were successfully discovered.

```bash
curl -s -X PUT -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "custom_fields": {
        "<priority_gid>": "<selected_enum_gid>",
        "<sizing_gid>": "<selected_enum_gid>",
        "<estimate_gid>": "<selected_enum_gid>",
        "<product_status_gid>": "<assigned_enum_gid>"
      }
    }
  }' \
  "https://app.asana.com/api/1.0/tasks/<task_gid>"
```

**Estimate**: Plan Only → omit the `<estimate_gid>` key. Fix Done → set it to the `00:00` enum option.

## 6d (cont). Fetch the auto-assigned task ID

Asana automation assigns an ID (e.g. `MT251-182`) once the task is in the right project. Retry up to 3 times waiting 10 seconds between each attempt.

```bash
curl -s -H "Authorization: Bearer $ASANA_PERSONAL_ACCESS_TOKEN" \
  "https://app.asana.com/api/1.0/tasks/<task_gid>?opt_fields=custom_fields,custom_fields.name,custom_fields.display_value,custom_fields.type"
```

Look for a text-type custom field whose `display_value` matches `[A-Z]+-\d+`. Save as `<task_id>`.
