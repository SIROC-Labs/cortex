# Authentication Gates

When navigation lands on a login/auth page instead of the app, follow this process before investigating.

## Step 1: Check CLAUDE.local.md

Look for a `CLAUDE.local.md` file in the project root:

```bash
ls CLAUDE.local.md 2>/dev/null
```

If the file exists, read it and look for credentials (username, password, test accounts, API keys, credit cards for testing, etc.) relevant to the app being tested. Use them to authenticate via the Chrome DevTools MCP (fill the login form and submit).

## Step 2: No File — Ask the Operator

If `CLAUDE.local.md` does not exist (or exists but has no relevant credentials), tell the operator:

> "I reached a login page and couldn't find credentials in `CLAUDE.local.md`. Please enter your credentials in the browser window and confirm when you're logged in — I'll continue from there."

**HARD GATE** — wait for the operator's confirmation before proceeding. Do not attempt to bypass, guess, or skip authentication.

## Notes

- `CLAUDE.local.md` is for local secrets — it should be gitignored and never committed.
- After authenticating, take a screenshot of the authenticated state as the first evidence capture.
