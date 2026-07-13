# Provider Implementation Guide

How to add a task-manager provider (e.g. `task-manager-jira`). **Documentation only** — never loaded during normal task operations; read solely when building or maintaining a provider.

## What a provider is

A skill named `task-manager-<provider>` that implements every neutral operation defined in `../../task-manager/SKILL.md` ("Neutral operations"). That SKILL.md is the **single source of truth** for the operation list — do not duplicate it here; map each operation it lists.

Name tokens per the plugin's convention (see "Naming Conventions for Interface Tokens" in the plugin `CLAUDE.md`): operations are `lower_snake()`, the skill is `kebab-case` (`task-manager-<provider>`).

## Obligations

For each neutral operation, a provider must:
- **Map intent to its native model.** e.g. `set_status(task, "In Review")` becomes whatever the provider uses (enum value, board column, workflow transition). There is no 1:1 translation across providers — own the realization.
- **Map the neutral field set** in `../../../references/workflow/fields.md` to native fields, discovering identifiers at runtime (do not hard-code them).
- **Honor the neutral board policy** in `../../../references/workflow/boards.md` using its own identification mechanism.
- **Accept Markdown** comment bodies and convert to the provider's rich-text format.
- **Choose the native link type for dependencies.** `add_dependency` maps to whatever relationship the provider exposes (e.g. Jira "Blocks" vs "Relates"); the chosen link type may be a provider-local setting.
- **Return faithfully:** on success, return the data the operation describes; on failure, surface the status code and message — never skip silently. When the primary transport cannot perform a neutral op (e.g. some CLIs can't upload attachments or add an issue to a sprint), the provider MUST either route through an alternate transport or return a clear, operator-actionable prompt — never silently no-op.

## Status mapping hint

Providers whose statuses are categorized (e.g. Jira's `statusCategory`: new / indeterminate / done) should map neutral lifecycle names via the **category**, not by matching literal status strings. Status names vary per instance and project; categories are stable, so category-based mapping is robust across instances.

## Transports

- **Auth is resolved inside the provider, and is broader than env-var tokens.** It may be an env-var token (e.g. an Asana PAT), OAuth managed by an external CLI (e.g. Jira's `acli`, where the provider holds no secret and only checks auth status), or another scheme. The seam never sees credentials.
- **A provider may use multiple transports.** Different operations can be realized via different mechanisms internally — e.g. a CLI for most ops plus a separate MCP/REST call for fields the CLI can't set. Pick the transport per-operation; the neutral op signature does not change.

## Board-resolution script contract

Every provider exposes **one `tm.py` CLI per provider** at `skills/task-manager-<provider>/scripts/tm.py`, dispatched by **family + verb** (`tm.py <family> <verb> [args]`). Families namespace operation groups so future op groups (`fields`, `task`, etc.) can be added to the same CLI without collision. `resolve_board(intent)` is implemented as a code-enforced cache lifecycle under the **`board` family**, not as ad-hoc prose steps. All providers expose the **same CLI shape and the same exit-code contract** so orchestrators (and the seam) treat them identically:

- **`board` family verbs:** `board key` · `board read <key>` · `board resolve <key> <active-sprint|backlog>` · `board discover <key>` · `board refresh <key>` · `board write <key> <json>`.
  - `board key` prints the cache key (the git-repo identity, shared across providers in one `~/.cortex/` namespace).
  - `board read` reports freshness via exit code; `board resolve` is the high-level entry point (cache-first, auto-refresh only when stale, bootstrap on miss); `board discover`/`board refresh` hit the live provider transport; `board write` persists provider config (used by bootstrap).
- **`fields` family verbs:** `fields list <project-ref>` · `fields resolve <project-ref> <CanonicalName>` · `fields discover <project-ref>`. Code-enforces custom-field DISCOVERY + neutral-name→native-id mapping (the read/mapping side — implements `list_fields`; the future `set_field` write path resolves an id through `fields resolve` first). The discovered map lives in the SAME per-repo cache file under a `"fields"` section keyed by project/board id, inheriting the provider marker.
  - `fields list` returns the compact canonical field map (`{ "<CanonicalName>": {"id","type","enum_options"?}, … }`); `fields resolve` returns one field's descriptor and exits non-zero/empty when the field is not on the project (skip gracefully — not every project has every field); `fields discover` forces a fresh discovery from the provider and writes it back.
  - **Unlike `board`, fields have no date-staleness** (they change rarely): `list`/`resolve` discover-on-miss and write back, and forced refresh is `fields discover` only — there is no auto-refresh path. `<project-ref>` is provider-defined (Asana: a project GID; Jira: a project key or a representative issue key).
- **`task` family verbs:** `task get <task-ref>` · `task create <project-ref> --title T [--description D] [--assignee A]` · `task set-field <task-ref> <CanonicalName> <value>` · `task attach <task-ref> <file-path>` · `task set-status <task-ref> <status-name>` · `task add-dependency <task-ref> <depends-on-ref>` · `task set-parent <task-ref> <parent-ref>` · `task add-to-board <task-ref> <board-ref>`. Implements `get_task` (read) plus the **sandbox-safe task WRITES** (`create_task`, `set_field`, `upload_attachment`, `set_status`, `add_dependency`, `set_parent`, `add_to_board`).
  - `task get` fetches the task and returns a **compact neutral projection** (`{ref,name,description,assignee,status,board,fields}`) instead of the raw provider blob — a token win over "fetch the full task and parse it" (the raw `opt_fields`/`*all` recipe stays available for unusual long-tail needs). Custom/native field names are mapped to canonical names via the `fields` logic. `task create` creates the task and adds it to the board/project; `task set-field` resolves the field through the `fields` logic (reusing `fields resolve` internally) and writes it; `task attach` uploads an attachment.
  - `task set-status`, `task add-dependency`, `task set-parent`, `task add-to-board` realize the corresponding neutral ops, mapping the neutral name in `../../../references/workflow/lifecycle.md` (for status). **`set-status` is two-axis on Asana** — it tries the `Product Status` custom field first (resolve via `fields`; status matching an enum option → field write) and falls back to a board **section** move (status matching a section name); on **Jira** it is transition-based — resolve the neutral name to a target status by `statusCategory`, list the issue's available transitions, pick the matching transition, then transition. Per the partial-support rule below, the **Jira** provider exits non-zero with the MCP/REST (or operator) fallback signal for `set-parent` and `add-to-board` (acli reaches neither on an existing issue/sprint) and for `add-dependency` when its acli build has no `workitem link` command.
  - **HTTP writes use a single top-level Python `urllib` process, never `curl`.** `curl -F` (multipart) and `curl -d "$(…)"` (command-substituted bodies) intermittently fail under the Bash sandbox's restrictive profile (`failed to change group ID`); the script builds the request (incl. the multipart body + boundary) in Python to avoid it. This is why attachment/field writes are scripted rather than left as prose `curl` recipes.
- **`comment` family verbs:** `comment add <task-ref> (<body> | --body-file <path>)` · `comment list <task-ref>`. Implements `add_comment` and `get_comments`.
  - `comment add` authors the body as **Markdown** and the provider converts it to its rich-text format (Asana → HTML via urllib; Jira → ADF via `acli`), then posts. `--body-file` keeps large/multiline bodies off the command line (avoids the command-substitution sandbox fragility); on Asana it also routes through the correct field (`text` vs `html_text`) and defends against `<br>`.
  - `comment list` returns a compact list of **human** comments — `[{author, text, created_at}]` (Asana: stories filtered to `type:comment`; Jira: reads `.comments` from the `comment list --json` object, not the top level).
- **`ref` family verbs:** `ref parse <url-or-ref>`. Implements `find_task` AND is the recognition probe the seam uses to detect the active provider. Each provider OWNS its own URL/ref recognition: it extracts the canonical task reference from THIS provider's URL formats (or a bare id/key) and prints **only** that ref to stdout. Exit **0** when the input is recognized as this provider's reference; exit **2** (no output) when it is not this provider's (a foreign-host URL, another provider's id form, or garbage). `ref parse` must NOT hit the network — it is pure parsing so the seam can probe every installed provider cheaply and offline. (Asana: numeric task GID from `app.asana.com` URLs or a bare numeric id; Jira: issue key via `[A-Z][A-Z0-9_]+-\d+` first match from a `*.atlassian.net` URL or a bare key.)
- **Exit codes (uniform):** `0` cache present & fresh / write succeeded / `ref parse` recognized · `2` cache missing / foreign, a `fields`/`set-field` target not present, **or `ref parse` did not recognize the input as this provider's** (skip gracefully) · `3` cache present but stale · `4` bootstrap needed (miss with no provider config to discover with) · `1` argument/auth/transport/parse error, **or a write the transport cannot perform** (partial support — see below).
- **Partial-support rule (writes):** when a provider's transport CANNOT perform a write (e.g. a CLI that cannot upload attachments, or cannot set certain fields on an existing issue), `task` MUST exit **non-zero with an operator/agent-actionable fallback signal** — a clear message naming the alternate transport the invoking skill must use (e.g. "needs Atlassian MCP `editJiraIssue` fallback (agent-handled)"). It MUST NOT silently no-op, and MUST NOT invent an unsupported transport. The skill prose owns invoking that fallback (e.g. the MCP tool) when it sees the signal. (Jira: `acli` reaches create + edit of assignee/labels/type and status transitions; priority/story-points/time-tracking/sprint/parent/customfields, attachments, `set-parent` and `add-to-board` on an existing issue, and `add-dependency` when the acli build has no `workitem link` command all signal the MCP/REST fallback.)
- **Cache-first, no manual discovery on a hit:** when the script returns a board, the provider MUST NOT issue manual discovery queries (REST list, `acli board search`, etc.). Live discovery runs only on a genuine miss via the script's `board discover` path, which then writes the result back.
- **Provider marker:** each cache carries a top-level `"provider"` string; a provider only reads its own caches (mismatch → treat as a miss). Whether an *unmarked* cache is adopted is a per-provider decision (Asana self-heals legacy unmarked caches as its own; a later provider like Jira treats unmarked as foreign).
- **Shared lifecycle helpers:** the neutral key derivation, cache path, read/write, timestamping, and date-staleness math live in `../scripts/cache_util.py` and are reused by every provider's `tm.py`. A provider supplies only (a) the discovery logic against its own transport and (b) the opaque cached payload shape; it never reimplements the lifecycle.

## Neutral seam scripts (policy, NOT a provider concern)

Some scripts live at the **seam** (`../scripts/`), not in any provider's `tm.py`, because they encode siroc's neutral **workflow policy** rather than task-manager mechanics. A provider implements primitives; it never owns the gate.

- **`readiness.py`** — the sprint-readiness verdict (`readiness.py check [--url <u>] <task-ref>`). It resolves the active provider (reusing `resolve_provider.py`), then **composes the provider's primitives** — `tm.py task get <ref>` (status, fields incl. Estimate, board membership) and `tm.py board resolve <key> active-sprint` — and applies the gate policy from `start-task/references/validation-rules.md` + `../../../references/workflow/lifecycle.md` as a pure function. It does **not** re-implement fetching, and **providers do not implement the gate**: a provider only needs its `task get`/`board resolve` projections to be faithful (status as an Asana string or a Jira `{name,category}`; board membership as the Asana `[{project,section}]` list or the Jira `{project,sprint}` dict; an `Estimate` canonical field). The verdict (`{ready, checks:[active_sprint, estimate, status, task_key]}`) is the same regardless of provider.

## Provider resolution (how the seam picks a provider)

The seam resolves the active provider via `../scripts/resolve_provider.py [--url <u>]`, **detection-only** — there is no committed selector file. Providers own only their own URL recognition (`ref parse`); the seam orchestrates the layers:

1. **Per-repo cache provider-marker** (`cache_util.read_cache(project_key())` → `cache_provider`) → authoritative when present. If `--url` is also given and a *different* installed provider's `ref parse` recognizes it, the resolver exits **3** (conflict) and surfaces both (cached vs detected) — the seam asks the operator and persists the choice with `--set`, rather than silently flipping the cached marker. Otherwise the cached provider wins (exit **0**, `source=cache`).
2. Else, with `--url` → **URL detection**: glob the installed sibling providers (`../task-manager-*/scripts/tm.py`), run each provider's `ref parse <url>`, and the first that exits 0 wins. The resolver **persists** the marker into the per-repo cache (merging with any existing cache) and exits **0** (`source=detected`).
3. Else → exit **4**: ask the operator (no cache marker, no URL).

`--set <provider>` mode writes/merges the provider marker into the cache and exits **0** — the seam calls it to persist the operator's answer after an ask (exit 4) or a conflict (exit 3).

Resolver exit codes: `0` resolved · `3` conflict · `4` ask-needed · `1` error. This is why `ref parse` must be offline and must exit 2 (not 1) for "not mine" — the resolver treats only exit 0 as recognition.

## Configuration & data boundaries

- Provider selection is **detected**, never committed: a task URL (via `ref parse`) or the per-repo cache provider-marker selects the provider (see "Provider resolution" above). A new provider is selected automatically the first time its URL is recognized or its marker is cached — no committed file. A provider must not require any committed file to choose it.
- Concrete instance values (the provider marker, workspace ids, discovered field identifiers, cached boards) belong in the machine-local `~/.cortex/` cache, never committed and never in workflow references.
- Auth is resolved inside the provider — see "Transports" below. It is not limited to environment-variable tokens; the seam and callers never handle credentials.

## Wiring a new provider

1. Create `skills/task-manager-<provider>/SKILL.md` implementing the operations.
2. Put native mechanics in `skills/task-manager-<provider>/references/`.
3. Nothing to commit for selection: the provider is detected automatically once its `ref parse` recognizes a task URL (which persists the marker) — or persist it directly with `resolve_provider.py --set <provider>`.

No orchestrator skill changes when a provider is added or swapped.
