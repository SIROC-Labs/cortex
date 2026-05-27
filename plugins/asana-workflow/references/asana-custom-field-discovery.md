# Asana Custom Field Discovery

Shared reference for discovering custom field GIDs in an Asana project. Field names are standard across projects but GIDs vary per project — discover them dynamically.

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

## Recording Results

For each matched field, record:
- The field's GID
- The field's type (enum, number, text)
- For enum fields: the full list of option GIDs and names

If a field has no match in the project, skip it gracefully — not all projects have all fields.

## Estimate Field

The Estimate field is a **number** field in Asana. The value is stored as decimal hours (e.g., `1.5` for one and a half hours).

When displaying estimates in conversation (tables, confirmations, progress updates), use `hh:mm` format for readability (e.g., `01:30`). When writing to Asana, submit the decimal number (e.g., `1.5`).

Conversion: `hh:mm` → decimal is `hh + mm/60`. Estimates use 0.25h increments (0.25, 0.50, 0.75, 1.00, ...), so valid `mm` values are `00`, `15`, `30`, `45`.
