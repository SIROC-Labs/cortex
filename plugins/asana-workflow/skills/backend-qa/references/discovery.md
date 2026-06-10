# SUT Discovery

Identify **three things** before investigation: the **base URL**, the **API surface**, and a **valid auth credential**.

## Step 1: Resolve the base URL

Find where the backend is running. Check in order:

1. **`$ARGUMENTS`** — an explicit URL.
2. **Project files** — `docker-compose*.yml` (exposed ports), `.env`/`.env.example` (`BASE_URL`, `PORT`), `README`/`CLAUDE.md` run instructions, framework dev-server default (e.g. `:8000`, `:3000`, `:8080`).
3. **Ask the operator** which environment to hit — local or staging.

Confirm reachability with a health/root request before going further. **The running SUT is blocking** — cannot investigate without a reachable backend.

> Run against local or staging. **Never** investigate against production with writes.

## Step 2: Resolve the API surface

Find the endpoints relevant to the question:

1. **OpenAPI/Swagger** — `/openapi.json`, `/swagger.json`, `/docs`, or a spec file in the repo. The fastest map of the surface.
2. **Route definitions in source** — the framework's router/controllers.
3. **The operator's description** — the specific endpoint or flow in question.

## Step 3: Auth bootstrap (blocking for protected endpoints)

Most backends require an initial authentication that can only be performed manually, even on local/staging. The agent cannot perform an interactive login.

**Resolution:** the operator logs in **once**, manually, and hands the agent the resulting credential. The agent reuses it for the whole session.

Ask the operator:

> "This API needs authentication I can't perform myself. Please log in on `<environment>` and give me a valid token (or session cookie). I'll use it for this QA session and redact it from saved evidence."

- Accept a bearer token, an API key, or a session cookie — whatever the API uses.
- Store it only in the session (an env var like `QA_TOKEN`); **never** write it to a committed file; redact it in evidence transcripts.
- If the token expires mid-session, ask the operator for a fresh one.

**Blocking** for any protected flow — if the question targets authenticated endpoints and no credential is provided, stop and ask.

## Confirmation

Present findings and confirm before proceeding:

> "I'll QA `https://staging.example.com` — the `POST /api/orders` flow, using the token you provided. Is that the right environment and surface?"

**HARD GATE:** confirm the base URL, the surface, and the credential with the operator before investigating.
