# Boards (neutral)

The siroc workflow organizes tasks on two kinds of board, independent of the task manager:

- **Sprint board** — the current iteration's work. Exactly one is *active* at a time.
- **Backlog board** — longer-lived collections of not-yet-scheduled work.

**Active-sprint policy:** the active sprint is the current, not-yet-finished iteration. When more than one candidate qualifies, the latest-ending one wins.

How sprint vs. backlog boards are *identified*, and how the active sprint is *discovered and cached*, is provider-specific — see the active provider skill. Skills request boards by intent (`resolve_board("active sprint")`, `resolve_board("backlog")`), never by a provider-specific name pattern.
