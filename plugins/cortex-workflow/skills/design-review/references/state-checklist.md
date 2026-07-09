# State-Type Checklist

For **each screen, view, and reusable component** the requirements imply, verify a design exists for every
state type that applies. You need **at least one example of each applicable type** — not every variant.

Walk this list per screen/component and mark each as: designed / missing / N/A.

## Data & content states
- **Default / filled** — the normal populated state.
- **Empty (no data)** — table/list/collection with zero items; first-run / nothing-created-yet.
- **No results after filtering or search** — distinct from empty: the data exists but the current
  query/filter matches nothing. A screen with a search box or filters *must* have this state.
- **Partial / truncated** — long content, overflow, "+N more", pagination edges.

## Async / lifecycle states
- **Loading (initial)** — first fetch; skeleton or spinner.
- **Loading (action in progress)** — submitting, saving, publishing, uploading; the triggering control
  is usually disabled or shows a spinner.
- **Polling / progress** — long-running work with a progress indicator (e.g. "X / N ready"); and the
  terminal transitions that stop it.
- **Success / confirmation** — completed action; toast, confirmation screen, or inline success.
- **Transient micro-states** — "Copied!", optimistic UI, auto-save indicator.

## Error & validation states
- **Field-level validation error** — inline, immediate (bad format, out of range, wrong dimensions).
- **Form/submit error** — server rejects the submission; form stays editable; error shown inline.
- **Full-page / fatal error** — resource failed to load, entity in an `error` status, with a recovery path.
- **Permission / not-found / unauthorized** — if reachable in the flows.
- **Retry affordance** — where a failed action can be retried.

## Interaction states
- **Disabled / enabled gating** — controls that are blocked until preconditions are met (and the enabled
  counterpart).
- **Hover / focus / active** — for interactive entry points where the spec calls them out.
- **Selected vs unselected** — pickers, toggles, radio groups.
- **Modal / dialog / confirmation** — including destructive-action confirmations.
- **Read-only vs editable** — when the same data appears in both modes.

## Entry & exit states
- **Entry point / empty CTA** — the "start here" affordance and its states.
- **Already-exists / returning** — what a user sees on returning when the thing was already created.
- **Navigation guards** — back/away with unsaved state; resume-after-leaving.

## How to use this against requirements
Acceptance criteria phrasing maps directly to required states:
- "shown while / during …" → a **loading** state
- "disabled until …" / "enabled only when …" → a **disabled/enabled gating** pair
- "on error / on failure …" → an **error** state (+ retry)
- "if empty / no items / no matches" → an **empty** or **no-results** state
- "the first time / once …" → a **transient/one-time** state

If the requirement names a state and no design shows it → that's a gap.
If a design shows values/behavior that contradict the requirement → that's a *discrepancy*, not a gap.
