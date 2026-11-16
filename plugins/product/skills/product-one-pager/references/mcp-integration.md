# Analytics MCP integration

State machine for workflow step 3. Detection runs at the start of Q&A, before the first owner-facing question, and always resolves the **project match** — which product the MCP points at — not merely connection state.

## States

**Connected to the right product.** Confirm the connected project/org corresponds to the product this brief is about. Then:

- For each verifiable numerical claim, run a scoped query (discovery → verification) and carry the result into Q&A as a decision, not an open question.
- Read the platform's existing event/metric conventions so success measures are proposed in the team's own naming.
- Render verified numbers in clean prose: "Current 30-day active rate is 23% (verified via PostHog)."

**Connected, but to the wrong project/product.** Run no queries against it — another product's numbers are never attributed to this one. The first Q&A turn surfaces the mismatch and offers a choice: "The connected analytics ([name]) is pointed at [project] — a different product from [this brief]. Want to point it at the right project so I can verify [claims], or skip verification and supply these numbers manually?" Either way, still gather manual Evidence and success-measure input.

**Available but not connected.** The first Q&A turn offers: "Want to connect [name]? It would let me verify [list claims]." Frame as an option, not a requirement.

**Unavailable.** Note once — "No analytics MCP is available; numbers will be owner-confirmed or owner-accepted inferences" — and proceed.

## Query scope

Queries run only in service of a specific surfaced claim, and only against the right product's project — no free-form exploration. If a claim cannot be verified (event not instrumented), surface it as "claim unverifiable: `[event]` not instrumented" and resolve in Q&A: reframe qualitatively, plan instrumentation, or accept an owner-stated value.

## Graceful degradation

The skill produces a useful one-pager with no usable MCP. Availability sharpens specific claims; its absence weakens them but never blocks the workflow — Evidence and success measures are then gathered from the owner in Q&A.
