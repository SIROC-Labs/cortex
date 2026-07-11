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

### Suggest Creating CLAUDE.local.md

If `CLAUDE.local.md` does not exist at all, also suggest creating it:

> "You don't have a `CLAUDE.local.md` file yet. You can create one to store credentials, test credit cards, and other local secrets so I can authenticate automatically next time. **Important: this file must be added to `.gitignore` — it should never be committed.** Want me to create it for you?"

If the operator agrees:

1. Check whether `.gitignore` already ignores `CLAUDE.local.md`:
   ```bash
   grep -q "CLAUDE.local.md" .gitignore 2>/dev/null
   ```
2. Create the file with a starter template:
   ```markdown
   # Local secrets — never commit this file
   # Add credentials, test accounts, credit cards for testing, API keys, etc.
   ```
3. If `CLAUDE.local.md` is not already in `.gitignore`, append it:
   ```bash
   echo "CLAUDE.local.md" >> .gitignore
   ```
4. Confirm to the operator: "Created `CLAUDE.local.md` and added it to `.gitignore`. Add your credentials there and I'll use them automatically on the next run."

If the operator declines, proceed without creating the file.

## Notes

- `CLAUDE.local.md` is for local secrets — it must be gitignored and never committed.
- After authenticating, take a screenshot of the authenticated state as the first evidence capture.
