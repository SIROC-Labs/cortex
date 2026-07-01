# Asana Custom Field Discovery

> Field *meanings* are defined neutrally in `../../../references/workflow/fields.md`. This file is the Asana-specific discovery + mapping of those fields.
>
> **Discovery + name→GID mapping is code-enforced by `../scripts/tm.py fields`** (`fields list <project-gid>` / `fields resolve <project-gid> <CanonicalName>` / `fields discover <project-gid>`). The rules below — the discovery call, the fuzzy match-pattern table, Assignee-is-native, and the Estimate unit handling — are what that script implements; do not re-ingest full field JSON and fuzzy-match by hand. Read this file to understand or change those rules.

Discovering custom field GIDs in an Asana project. Field names are standard across projects but GIDs vary per project — discover them dynamically.

## Discovery Call

Fetch the project's custom field settings to get GIDs and enum options:

```
GET /projects/<project_gid>/custom_field_settings
  ?opt_fields=custom_field.gid,custom_field.name,custom_field.type,
              custom_field.enum_options,custom_field.enum_options.gid,
              custom_field.enum_options.name
```

## Field Matching

Match fields by name using fuzzy, case-insensitive patterns:

| Field | Match patterns |
|-------|---------------|
| Platform | "platform" |
| Priority | "priority", "urgency", "severity" |
| Sizing | "size", "sizing", "story points", "points", "t-shirt" |
| Estimate | "estimate", "estimated time", "time estimate", "effort" |
| Category | "category", "type" |
| Product Status | "product status", "status", "state" |

Assignee is handled natively by Asana — not a custom field.

## The project ID / key field is READ-ONLY

The per-project **ID field** (the auto-incrementing key like `PD268-49`, `MT251-47`) is **assigned and managed by Asana** and **cannot be written via the API** — a `PUT` to it returns `400 cannot_manually_create_or_update_custom_id_field`. It is **read-only**: read it (for branch names, PR titles, the checkpoint `task_id`) but **never set it**. It is not a settable canonical field — `tm.py task set-field` must refuse it (see the script's ID-field guard), and no skill should offer to "set the ID via the task manager." If a task lacks one, Asana assigns it / it is set in the Asana UI — not through this provider.

**Discovery rule:** the key field is surfaced **read-only** as the projection's top-level **`task_id`** by `tm.py task get` (used for branch/PR naming and the checkpoint) and is never added to the canonical `fields` map. Two storage shapes exist across projects, detected in this order:

1. An auto-managed **custom_id** field — detected by `resource_subtype == "custom_id"` (NOT by name).
2. A plain **text** custom field holding the key — detected by **value pattern** `^[A-Z][A-Z0-9]*-\d+$` (e.g. a field named `PD268` holding `PD268-72`). Names vary per project (`PD268`, `MT251`), so match by the value shape, not the name.

Most projects use shape 2 today. Either way the key is treated as read-only here — `tm.py task set-field` accepts only canonical names, so it refuses the ID field regardless.

## Recording Results

For each matched field, record:
- The field's GID
- The field's type (enum, number, text)
- For enum fields: the full list of option GIDs and names

If a field has no match in the project, skip it gracefully — not all projects have all fields.

## Estimate Field

The Estimate field appears in three shapes across projects; `tm.py task set-field <task> Estimate <value>` handles all three. **Input is always tolerant** — it accepts decimal hours (`1.5` / `1.5h`), `hh:mm` (`01:30` / `1:30`), and `1h 30m` / `1h30m` / `90m` / `2h`, normalizing to canonical **minutes** via `parse_estimate_to_minutes`. A **bare integer** is read in the *field's own unit* (so on an `(hours)` field `1` means **1 hour**, not 1 minute — input and output use the same `_estimate_unit_is_hours(entry)` rule, which is what fixed `1` → `0.02h`); a **bare decimal** is always hours. Explicit-unit forms always win. Unparseable input (e.g. `soon`) errors (exit 1) rather than writing a wrong number. `hh:mm` → minutes is `hh * 60 + mm` (`01:30` → `90`).

How the canonical minutes are **written** depends on the field descriptor (discovered into the cache as `type`/`name`/`format`/`precision`), via `estimate_number_value`:

| Field shape | Detected by | Stored value |
|-------------|-------------|--------------|
| **enum** of `hh:mm` options (`00:30`, `01:00`, …) | `type == "enum"` | the matching option GID (handled by the enum branch, not the converter) |
| **number** named with a unit — `"… (hours)"` / `"hr"` | `type == "number"`, name has `hour`/`hr` | decimal **hours** (`minutes/60`, rounded to the field's `precision`) |
| **number** named with `min` | name has `minute`/`(min` | integer **minutes** |
| **number**, no unit in the name (e.g. `"Estimated time"`) | default | integer **minutes** (original convention) |
| **number**, `format == "duration"` (paid time field) | `format == "duration"` | integer **minutes** (Asana's time convention) |

The unit of a plain Asana number field is **not** in the API — only the field **name** signals it, so naming drives the choice (adaptive-by-name). Read-back uses the field's own `display_value` (`1.50`, `01:30`, …) so the stored unit is always visible.

> Asana rejects API writes to **`duration`-format** fields on accounts without that feature (`cannot_manually_create_or_update_custom_field_with_duration_format`); `set-field` surfaces a clear "set it in the Asana UI" message in that case. The value remains readable for display/readiness.
>
> The paid **native time-tracking** entries API (`time_tracking_entries`, `actual_time_minutes`) is *actual* logged time — distinct from the Estimate field above and not used here.
