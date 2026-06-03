---
name: create-prd
description: Creates a Product Requirements Document from one or more content sources. Sources can be passed as arguments — Asana task URL, Jira URL, Notion URL, Google Drive URL, Figma URL, any web URL, a local folder path, or left empty to read the current folder. Use when the user says "/create-prd" or asks to create a PRD.
---

# Create PRD

Produces a complete, well-formatted PRD. Follow the four phases below **in strict order**. Never skip or reorder phases.

---

## Absolute Rules

1. **Read everything before asking anything.** Exhaust all available resources first.
2. **Ask everything before writing anything.** Not a single section of the PRD gets written until the interview is complete.
3. **Never write TBD.** If something is unknown, ask. Only mark as TBD if the user explicitly says "not yet decided" after being asked.
4. **Ask one question at a time**, conversationally. Do not batch all questions into a form.
5. **Never assume relationships between systems or features.** Ask if anything is unclear.

---

## Phase 1: Ingest All Sources

Before asking the user anything, ingest every source provided. Sources come from the skill arguments and/or the current folder.

### Source detection

Inspect each argument or input for its type and fetch accordingly:

| Source type | How to detect | How to ingest |
|---|---|---|
| Asana task or project | `app.asana.com` in URL | Use the `asana-api` skill (the plugin's only sanctioned Asana entry point) to fetch the task/project and all subtasks |
| Jira issue or board | `atlassian.net/browse/` or `atlassian.net/jira/` | Use Atlassian MCP tools to fetch the issue and linked items |
| Notion page or database | `notion.so` or `notion.site` in URL | Use Notion MCP tools to fetch the page or database content |
| Google Drive file or folder | `drive.google.com` or `docs.google.com` | Use Google Drive MCP tools to fetch the document or list the folder |
| Figma file or frame | `figma.com` in URL | Use Figma MCP (`get_design_context`, `get_metadata`, `get_screenshot`) |
| Any other URL | starts with `http://` or `https://` | WebFetch the URL and read the content |
| Local file path | path resolves to a regular file (e.g. `./spec.pdf`, `/Users/.../onepager.pdf`) | Read the file directly (PDF, HTML, Markdown, docs) |
| Local folder path | path resolves to a directory (e.g. `./specs/`, a bare directory name) | List and read all files in that folder (PDFs, HTML, Markdown, docs) |
| No argument given | — | Read every file in the current working directory |

**Important:** Only fall back to reading local files when no argument was provided at all. If any URL or remote source is given as an argument, do NOT also read the current working directory — only ingest the explicitly provided sources. Local files are read when: (a) a local path was explicitly passed as an argument, or (b) no argument was given at all.

If multiple sources are provided (e.g. an Asana task URL + a Figma URL + a local folder), ingest all of them before moving on.

### What to extract from each source

From any source, pull out:
- The core problem being solved
- What is already shipped vs what is new
- Every screen, user flow, state, and edge case
- Any existing feature flags, TBDs, or open questions already noted
- Names of stakeholders, owners, or teams mentioned
- Any referenced external resources (linked docs, specs, designs) — note their URLs

---

## Phase 2: Collect Any Remaining Resources

After ingesting all provided sources, ask:

> "Are there any other resources I should read before we start? For example: Figma designs, backend or API specs, Notion docs, Loom walkthroughs, or anything else not already shared?"

If additional URLs or paths are provided, fetch and read them before continuing.

If a resource is referenced but doesn't have a URL yet (e.g. Figma designs not started, backend spec not written), note it — it will appear in the PRD as explicitly missing, not omitted.

---

## Phase 3: The Interview — Ask Everything

Work through every topic below, **one question at a time**, waiting for the answer before asking the next. Never batch questions. Never assume an answer.

If at any point the user says "leave that as TBD" or "not decided yet", note it as a genuine TBD — this is the only valid reason for a TBD in the final document.

### 3.0 Output format
- Ask: "What format would you like the PRD in — HTML (recommended, styled and linkable), Markdown, or plain text?"
- Default to HTML if the user has no preference. If HTML, follow the structure and component patterns defined in `references/html-template.md`.

### 3.1 Ownership & Timeline
- Who is the PM owner?
- What is the target launch date or quarter?

### 3.2 Scope decisions — for each feature or area identified in Phase 1
- Is this in scope for v1 or a future consideration?
- Are there variants (e.g. supported values, formats, server types) — which are in scope for v1?
- What is explicitly out of scope?

### 3.3 Feature behaviour — for each in-scope feature
- What happens in the error or edge case? (e.g. empty values, missing data, no match found)
- Is there a fallback behaviour? Who or what defines it?
- Are there any system relationships you should NOT assume? Ask about any dependency that seems implied but isn't confirmed.
- Can items be edited after they are published / submitted / finalised?

### 3.4 KPIs — for every metric
- What metric should we track?
- How will we measure it — what instrumentation or logging is needed?
- What is the baseline today?
- What is the target? If unknown, say so — do not leave blank.

### 3.5 Dependencies
- For each dependency: is it already built, or being built as part of this initiative?
- If being built: what specific data or events does it need to emit for KPI tracking?
- Is there a separate spec for it, or does this PRD need to cover its requirements?

### 3.6 Access & Lifecycle
- Who can use this feature — any role restrictions?
- Where do created items live after they are published? Is there a history or management view?
- Are there any notifications (in-product or external) when key actions happen?

---

## Phase 4: Write the PRD

Only start writing once **every question in Phase 3 has been answered**.

### Output formats

**HTML** (default): A single file named `PRD - [Feature Name].html`. Self-contained with inline styles. Follow every component pattern in `references/html-template.md` exactly — CSS block, section structure, feature cards, tables, scope chips, requirement pills, and link cards. All links must be real `<a>` tags pointing to actual files or URLs. Never write placeholder link text inside an anchor.

**Markdown**: A single file named `PRD - [Feature Name].md`. Use the same section order as HTML. Tables for KPIs, dependencies, open questions. No TBDs in feature bodies — open questions table only.

**Plain text / PDF-ready**: Clean prose with clear section headings. Same structure. Tables as plain ASCII. Delivered as `.md` for the user to copy into their tool of choice.

### Document structure (all formats, in this order)

1. **Header** — title, PM owner, status (Draft), last updated, version, target launch
2. **Table of contents** — anchored links to every section
3. **Problem & KPIs**
   - Problem statement: what is happening, who is affected, why it matters
   - KPI table: Metric | Baseline | Target | How we measure
4. **Scope**
   - Prose description of what the initiative adds to the product
   - Scope list with in / out / TBD tags for each decision
   - Future Considerations list
5. **Features** — one block per feature:
   - Feature name
   - User story ("As a [role], I want to…")
   - Functional Requirements (FR-1, FR-2…) — what the system does
   - Business Rules (BR-1, BR-2…) — constraints and invariants
   - Figma link — always shown. If a real URL exists, link it. If design hasn't been started yet, show as "Design not yet available."
6. **Dependencies & Integrations** — System | Nature of dependency | Impact / Risk
7. **Open Questions** — Question | Owner | Due Date | Status (only confirmed TBDs)
8. **Links** — every resource referenced in the PRD, with a clickable link. If a resource has no URL yet (spec not written, designs not started), list it explicitly as "Not yet available" — never omit it.

### Writing rules
- FRs: what the system does — actions, behaviours, UI elements
- BRs: what is always or never true — limits, formats, invariants
- Never repeat the same point across FRs and BRs
- No TBD inside any feature section — unresolved items go in Open Questions only
- KPI table must always include "How we measure" — never omit it
- Every dependency must state: already built, or being built as part of this initiative
- If being built as part of this initiative, state what data/events it must emit
- Every referenced resource (spec, design, doc) must appear in the Links section — with its URL if available, or explicitly marked "Not yet available" if it doesn't have one yet

---

## Common Mistakes to Avoid

| Mistake | Prevention |
|---------|-----------|
| Writing TBD without asking | Ask first. Always. |
| Assuming system A drives system B | Confirm every relationship explicitly |
| KPIs without measurement method | "How we measure" is mandatory for every metric |
| Omitting a resource because it has no URL yet | List it in Links with "Not yet available" — never silently skip it |
| Figma link missing from a feature card | Always show the Figma slot; mark "Design not yet available" if no URL |
| Treating prototype as 100% spec | Ask "is this demo-only?" when in doubt |
| Missing error states and fallback behaviour | Always ask what happens when things go wrong |
| Skipping "already built vs being built" | Ask for every dependency |
| Not asking for URLs upfront | Phase 2 must collect URLs for every resource before the interview starts |
| Batching questions | One at a time, wait for the answer |
| Asking about output format last | Ask it first, in 3.0, before the rest of the interview |
