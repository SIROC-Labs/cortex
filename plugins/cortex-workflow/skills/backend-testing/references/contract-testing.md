# Contract Testing via Spec-Driven Fakes

External services are not mocked ad-hoc and are not called for real in the test suite. Instead, run a **fake that implements the external contract**, seeded from the contract artifact, and validate its responses against that artifact so it can't drift.

## The artifact is the source of truth

The contract lives as a spec: OpenAPI / Swagger for HTTP, AsyncAPI for messaging, or a JSON-schema set. If the third party publishes one, vendor it into the repo (pinned to a version). If they don't, write the slice you consume as a spec — that becomes the contract you test against.

## Running the fake

Run a mock server in a container alongside the app under test, seeded from the spec:

| Tool | Good for |
|---|---|
| **Prism** (`stoplight/prism`) | OpenAPI → mock server that serves spec-valid responses, including examples |
| **WireMock** | HTTP stubbing with stateful scenarios and request matching |
| **MockServer** | HTTP expectations + verification, JVM-friendly |

Point the app's config at the fake's container URL (via the random host port) for the duration of the integration test. The app talks real HTTP to a real server — only the implementation behind it is fake.

**This requires the client to take its base URL as a constructor/config argument** — a client that hardcodes the scheme+host cannot be pointed at the fake. If it hardcodes, make the base URL injectable (default to the real host so production is unchanged) before writing the contract test; that injection seam is the whole point.

**Set the fake's response `Content-Type`.** Strict clients reject a body whose media type doesn't match — e.g. aiohttp's `response.json()` raises on a JSON body served without `application/json`. WireMock's `jsonBody` does not always set it; make your stub helper default `Content-Type: application/json`. Also mind falsy-body bugs in stub helpers: `body or {}` turns a legitimate empty-list response (`[]`) into `{}` — use `body if body is not None else {}`.

## The drift guard (non-negotiable)

A fake that returns hand-typed data silently rots when the real service changes. Prevent it:

1. **Validate every fake response against the spec schema** in the test (or rely on Prism, which only emits spec-valid responses). A response that doesn't match the schema fails the test.
2. **Keep the spec pinned and updated deliberately** — bumping the vendored spec is a reviewed change, so a contract change is visible in the diff.
3. **Optionally, a thin real-sandbox contract check** — a separate, local-only suite that hits the real service's sandbox and asserts the response still matches the pinned spec. This catches the provider drifting without telling you. Keep it out of the fast suite.

## What this is not

- Not consumer-driven contract publishing (Pact provider verification) — we **consume** specs, we don't author contracts for others to verify.
- Not a reason to skip integration: the fake replaces the *external* dependency only. The app, its DB, and its own logic are still exercised for real.

## When the external is reached through a vendored SDK with no base-URL seam

Some third parties are consumed via a vendored SDK (an OAuth/authlib client, a vendor library) that hardcodes its host and offers no way to point it at the fake. You cannot WireMock what you cannot redirect. The legitimate fallback: substitute the SDK boundary to **inject the failures/responses your own branch logic must handle** (OAuth `invalid_grant`, a not-found, a rate-limit) and assert *your* handling — not the SDK's HTTP. This is error-injection of a boundary you don't control, not the mock-the-DB anti-pattern; keep it narrow, and prefer the real fake the moment the SDK exposes a base-URL/transport seam (check for one first — some expose a settable module-level `api_url` or a `transport=` argument).
