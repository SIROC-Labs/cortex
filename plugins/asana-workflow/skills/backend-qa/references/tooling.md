# Testing Tools: HTTP, Logs, DB

A backend has no GUI. Observation comes from three tools; each produces a saved evidence artifact. Save everything under the evidence directory from `../../generic-qa/process.md` → Step 4 (`/tmp/qa-evidence/<task-gid>/`, or a timestamped dir standalone).

## 1. HTTP client (primary)

Drive the API with `curl -v` or `httpie`. Capture the **full transcript** — request line, headers, body, response status, headers, body, and timing.

```bash
curl -sS -D - -o /tmp/qa-evidence/<gid>/resp-body.json \
  -w '\n--- timing: %{time_total}s status: %{http_code}\n' \
  -H "Authorization: Bearer $QA_TOKEN" \
  https://staging.example.com/api/orders/42 \
  | tee /tmp/qa-evidence/<gid>/orders-42.http
```

- Save one transcript file per request you assert on. Name it for the behavior (`create-order-422.http`).
- Redact the token in saved files (`Authorization: Bearer ***`).

## 2. Application logs

Tail the running app's logs and correlate to the request via a request-id / trace-id.

- Local: the dev-server stdout, `docker compose logs -f <service>`, or the app's log file.
- Capture only the **relevant excerpt** around the reproduction, not the whole log. Save as `<behavior>.log`.

## 3. Database access

Query the DB to confirm side effects. Capture **before/after** snapshots of the affected rows.

```bash
psql "$QA_DB_URL" -c "select id,status,updated_at from orders where id=42" \
  | tee /tmp/qa-evidence/<gid>/orders-42-after.txt
```

- Read-only queries for observation. If a write is needed to set up the scenario, do it through the API, not raw SQL.
- Snapshot the same query before and after the action to prove the effect.

## Verification

Before investigating, confirm the tools you need actually work:

1. **HTTP reachability** — an unauthenticated/health request to the base URL returns a response. **Blocking.**
2. **Auth** — the bootstrap token (see `discovery.md`) is accepted by a protected endpoint. **Blocking for protected flows.**
3. **DB** (if side effects are in scope) — the connection string connects and a trivial `select 1` succeeds.

If a needed tool fails, tell the operator what's missing and how to provide it — don't caveat the report around a missing tool.
