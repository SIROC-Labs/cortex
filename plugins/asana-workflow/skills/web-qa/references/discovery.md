# SUT Discovery

The SUT (System Under Test) is a running web application — either a local dev server or a remote staging/production URL. The skill must identify it before investigation begins.

## Discovery Sources

Check these in order:

1. **`$ARGUMENTS`** — If the operator passed a URL, use it directly. Still confirm it's reachable.

2. **CLAUDE.md** — Look for:
   - Dev server commands (`npm run dev`, `yarn dev`, `pnpm dev`)
   - Port numbers (`localhost:3000`, `localhost:5173`)
   - Staging/preview URLs
   - Environment setup instructions

3. **package.json scripts** — Look for:
   - `dev`, `start`, `serve`, `start:local` scripts
   - Port configurations in the script commands

4. **docker-compose.yml** — Look for:
   - Service port mappings
   - Frontend service definitions

5. **docs/** — Look for:
   - Setup guides mentioning URLs
   - Architecture docs with service maps

## Inference Patterns

Common patterns to recognize:

| Framework | Default Port | Start Command |
|-----------|-------------|---------------|
| Vite | 5173 | `vite dev` |
| Next.js | 3000 | `next dev` |
| Create React App | 3000 | `react-scripts start` |
| Strapi | 1337 | `strapi develop` |
| Express | 3000 | `node server.js` |

## Confirmation Flow

**Never assume.** After gathering information, present findings:

> "I found `npm run dev` in package.json which starts a Vite server on port 5173. Is this the app to test, or should I use a different URL?"

If no SUT information is found:

> "I couldn't determine where the app is running. Can you provide the URL or tell me how to start the dev server?"

If the operator provides a URL, verify it's reachable using the testing tool (`navigate` to the URL and confirm a page loads).

## SUT is Blocking

Investigation cannot begin without a confirmed, reachable SUT. If the SUT cannot be reached:
- Report the failure clearly
- Suggest troubleshooting (is the server running? correct port? firewall?)
- Ask the operator for help

Do NOT proceed with source-code-only analysis and call it "investigation."
