# Report Template

Default output is Markdown. Offer an HTML rendering of the *same* content for easier reading if useful.

## Conventions
- Group findings by **state type** (Loading / Empty / Error / Transient), then **discrepancies**.
- Give each finding a **stable ID** (`L1`, `E2`, `ER3`, `T1`, `D1`) so the team can reference it.
- Every row cites the **source requirement** (which doc / acceptance criterion drove it) and the
  **location** where the new state belongs (deep link, frame name, page, or artboard).
- Separate **missing states** (no design exists) from **discrepancies** (design contradicts the spec).
- Lead with a one-line **verdict**: which state-type categories pass and which fail the "one of each" bar.

## Markdown skeleton

```markdown
# <Feature> — Design Gap Report

**Scope:** design-vs-requirements completeness audit
**Sources:** <requirement docs>  ·  **Designs:** <links/paths to artifacts>

**Verdict:** <one line — which categories pass, which fail>

## 1. Loading states — TO ADD
| # | What's missing | Source requirement | Where to add it |
|---|---|---|---|
| L1 | … | … | <link / frame / page> |

## 2. Empty states — TO ADD
| # | What's missing | Source requirement | Where to add it |
| E1 | empty <table> | … | … |
| E2 | no-results-after-filter | … | … |

## 3. Error states — TO ADD
| # | What's missing | Source requirement | Where to add it |
| ER1 | … | … | … |

## 4. Transient / micro-states — TO ADD
| # | … |

## 5. Discrepancies — TO CHANGE / CONFIRM
| # | Issue | Detail (design vs spec) | Where |
| D1 | … | spec says X, design shows Y | … |

## 6. Suggested priority order
1. …

## Appendix — what the designs already cover well
<short paragraph>
```

## HTML version
When the operator wants HTML, render the identical findings as a single self-contained `.html` file
(inline `<style>`, no external assets) with: a header (feature, scope, sources, design links), a
highlighted verdict block, one table per state-type section with colored type pills, a priority list, and
the "already covered" appendix. Make every location a real clickable link. Keep it readable offline.
