---
name: work-summary
version: 0.1.0
description: >
  This skill should be used when the user says "summarize my work", "what did I do", "session recap",
  "standup notes", "handoff", "write a summary", "what changed", "wrap up summary", "give me a recap",
  or "work report". Produces a concise, reusable work summary that other skills (ship-it, create-pr,
  task-manager) can consume. Standalone use cases include standups, handoffs, Slack posts, and task
  comments without running the full ship-it flow.
---

# Work Summary

Generate a concise report of the current session's work — what was done, why, and what comes next. The output is designed for humans first (standups, handoffs, Slack posts) and can also be consumed by other skills that need a work summary.

## Output Format

The summary has three parts: the **task summary**, the **body**, and the **footer**.

### Task Summary (max 3 sentences)

A high-level, non-technical description for the task comment. Written for a product manager or stakeholder, not an engineer. Focus on what changed at the feature/product level and highlight anything critical (a constraint overcome, a tradeoff made, a risk resolved). Do NOT name hooks, files, endpoints, or implementation details.

Examples:
- *"Replaced the Dynamic Creative sidebar with the Instant Creative sidebar. The main constraint was keeping the shared code inside the app package due to an API dependency limitation. All four locales were updated."*
- *"Fixed premature session logouts for users outside UTC. Root cause was a timezone mismatch in the expiry check."*

### Body (max 3 paragraphs)

A technical, flowing summary for the PR description and handoffs. Use as many paragraphs as needed, up to three:

1. **What and why** — What work was done and what motivated it. Be specific: name endpoints, components, files, configs. Mention technical details when they matter (e.g., "migrated from polling to WebSocket" not just "improved performance").

2. **Key changes** (if needed) — Expand on significant changes that deserve more detail than paragraph 1 can hold. Include architectural decisions, tradeoffs, or notable implementation details. Skip this paragraph for small or straightforward work.

3. **Blockers and next steps** (if needed) — Mention anything that blocked progress, remaining work, known issues, or follow-up tasks. Skip this paragraph when the work is fully complete with no loose ends.

Use fewer paragraphs when the work is simple. A 2-line summary for a config tweak is better than 3 padded paragraphs.

### Footer

After the body, append a **mandatory** stats line and attribution. This line is NOT optional — it MUST appear in every summary, even for trivial changes:

```
~Xh Ym | Files changed: N | Commits: N
🤖 Done
```

- **Duration** — Estimated session duration (see Duration Measurement below). ALWAYS include this, even for short sessions (`~5m` is valid).
- **Files changed** — Count of files modified/added/deleted from `git diff $BASE...HEAD --stat`
- **Commits** — Number of commits on the branch from `git log $BASE..HEAD --oneline | wc -l`
- **Attribution** — `🤖 Done` on its own line is mandatory. It signals AI-assisted work is complete and ready for review.

The stats line must follow this exact format. Do not inline file/commit counts into the body prose — they go on this dedicated line.

Do NOT include estimated cost.

## Context Gathering

To build the summary, gather data from three sources:

### Detect base branch

```bash
BASE=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|origin/||' || echo "main")
```

Use `$BASE` in all subsequent git commands.

### Git diff for scope

```bash
git diff $BASE...HEAD --stat
```

Shows which files changed and how much. Use to ground the summary in concrete file/module names.

### Git log for narrative

```bash
git log $BASE..HEAD --oneline
```

Shows commit messages that tell the story of the work — its progression and intent.

### Conversation history

Review the conversation to understand:
- What the user originally asked for and why
- Decisions made along the way
- Problems encountered and how they were solved

The conversation provides the **why** that git data alone cannot.

## Duration Measurement

Estimate session duration by combining two signals:

1. **Git timestamps** — First and last commit on the branch define the time window:
   ```bash
   git log $BASE..HEAD --format="%ai" --reverse | head -1  # session start
   git log $BASE..HEAD --format="%ai" | head -1             # most recent work
   ```

2. **Conversation turns** — Count user messages, estimate ~2-3 minutes each. This is the primary estimator.

When git timestamps span a much larger window than conversation turns suggest (e.g., overnight gap), prefer the conversation-based estimate. Format as `~Xh Ym` for sessions over an hour, `~Xm` for shorter ones. Round to nearest 5 minutes.

## Example Output

**Small change:**

Task summary:
```
Fixed premature session logouts for users outside UTC. Root cause was a timezone
mismatch in the session expiry check.
```

Body + footer (for PR and handoffs):
```
Fixed the timezone offset bug in the session expiry check. The comparison
was using UTC timestamps against local time, causing premature logouts
for users in positive UTC offsets.

~20m | Files changed: 1 | Commits: 1
🤖 Done
```

**Larger feature:**

Task summary:
```
Added admin endpoints for listing and exporting presale code pool codes.
Needed for reconciliation with the payment provider. Frontend table still
needs to wire up to the new endpoints.
```

Body + footer (for PR and handoffs):
```
Added superadmin endpoints for listing and exporting presale code pool
codes. The pool management UI needed a way to inspect and export codes
for reconciliation with the payment provider.

New paginated endpoint GET /admin/presale-pools/:id/codes returns codes
with filtering by status. A companion /codes/export endpoint generates
CSV downloads. Both endpoints reuse the existing PresaleCodePool
repository with new query helpers for pagination and status filtering.

Next: the frontend table component needs to wire up to these endpoints.
The export button can use a direct download link since the endpoint
streams CSV.

~45m | Files changed: 3 | Commits: 2
🤖 Done
```

## Behavior

1. **Gather context** — Run git commands and review conversation history.
2. **Draft the summary** — Write the body and footer following the format above.
3. **Return the result** — Output the summary. Do not ask the user to validate it.

Do not ask clarifying questions before producing the summary — use available context to write the best summary possible and return it. Bias toward action.

## Integration with Other Skills

This skill produces output that other skills consume:

- **ship-it** — Uses the **task summary** (high-level, 1-3 sentences) for the task comment.
- **create-pr** — Uses the **body** (technical paragraphs) for the PR description.
- **task-manager** — Uses the task summary + stats footer as a task comment.

When called by another skill, return both the task summary and the body so the caller can pick the right one. When called standalone, present both to the user. In both cases, do not prompt the user to validate or adjust the summary.
