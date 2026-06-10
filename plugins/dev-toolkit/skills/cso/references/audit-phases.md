**Scope gate (read first).** This section holds every scope-dependent phase (2-11), but you run ONLY the phases your resolved mode selected back in `## Mode Resolution` (in the main SKILL.md). Phases 0, 1, 12, 13, 14 always run; Phases 2-11 are scope-gated. "Execute in full" means work through this section applying that selection, NOT run a phase your mode did not select just because its prose lives here. Example: `--owasp` runs Phase 9 from this section, not Phases 2-8/10/11.

### Phase 2: Secrets Archaeology

Scan git history for leaked credentials, check tracked `.env` files, find CI configs with inline secrets.

**Credential pattern catalog (self-contained).** The HIGH-tier credential shapes
below are genuinely-secret tokens — a match in committed code or git history is a
CRITICAL finding. Treat the list as the canonical set for this audit; extend it for
any provider the target stack uses.

| Provider | Shape (regex) |
|---|---|
| AWS access key | `\bAKIA[0-9A-Z]{16}\b` |
| AWS secret key | 40-char base64 string near `aws_secret_access_key` |
| GitHub PAT (classic) | `\bghp_[A-Za-z0-9]{36}\b` |
| GitHub OAuth | `\bgho_[A-Za-z0-9]{36}\b` |
| GitHub fine-grained PAT | `\bgithub_pat_[A-Za-z0-9_]{82}\b` |
| Anthropic API key | `\bsk-ant-[A-Za-z0-9_\-]{20,}\b` |
| OpenAI API key | `\bsk-(proj\|svcacct\|admin)-[A-Za-z0-9_-]{20,}\b` or legacy `\bsk-[A-Za-z0-9]{32,}\b` |
| Stripe live secret | `\bsk_live_[A-Za-z0-9]{24,}\b` |
| Slack token | `\bxox[baprs]-[A-Za-z0-9-]{10,}\b` |
| Slack webhook | `https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{24}` |
| Google API key | `\bAIza[0-9A-Za-z_\-]{35}\b` |
| Private key block | `-----BEGIN (RSA\|EC\|OPENSSH\|DSA\|PGP)? ?PRIVATE KEY-----` |
| Generic high-entropy | `password\|secret\|token\|api_key` assigned a non-placeholder literal |

**Git history — known secret prefixes:**
```bash
git log -p --all -S "AKIA" --diff-filter=A -- "*.env" "*.yml" "*.yaml" "*.json" "*.toml" 2>/dev/null
git log -p --all -G "sk-ant-|sk_live_|sk-proj-|sk-[A-Za-z0-9]{32,}" --diff-filter=A -- "*.env" "*.yml" "*.json" "*.ts" "*.js" "*.py" 2>/dev/null
git log -p --all -G "ghp_|gho_|github_pat_" 2>/dev/null
git log -p --all -G "xox[baprs]-|hooks\.slack\.com/services" 2>/dev/null
git log -p --all -G "AIza[0-9A-Za-z_-]{35}" 2>/dev/null
git log -p --all -G "BEGIN [A-Z ]*PRIVATE KEY" 2>/dev/null
git log -p --all -G "password|secret|token|api_key" -- "*.env" "*.yml" "*.json" "*.conf" 2>/dev/null
```

**.env files tracked by git:**
```bash
git ls-files '*.env' '.env.*' 2>/dev/null | grep -v '.example\|.sample\|.template'
grep -q "^\.env$\|^\.env\.\*" .gitignore 2>/dev/null && echo ".env IS gitignored" || echo "WARNING: .env NOT in .gitignore"
```

**CI configs with inline secrets (not using secret stores):**
```bash
for f in $(find .github/workflows -maxdepth 1 \( -name '*.yml' -o -name '*.yaml' \) 2>/dev/null) .gitlab-ci.yml .circleci/config.yml; do
  [ -f "$f" ] && grep -n "password:\|token:\|secret:\|api_key:" "$f" | grep -v '\${{' | grep -v 'secrets\.'
done 2>/dev/null
```

**Severity:** CRITICAL for active secret patterns in git history (AKIA, sk_live_, sk-ant-, ghp_, xoxb-, private key blocks). HIGH for .env tracked by git, CI configs with inline credentials. MEDIUM for suspicious .env.example values.

**FP rules:** Placeholders ("your_", "changeme", "TODO", "example", AWS docs convention `AKIAIOSFODNN7EXAMPLE`) excluded. Test fixtures excluded unless same value in non-test code. Stripe publishable keys (`pk_live_`), Google `AIza` keys, and JWTs (`eyJ...`) are context-variable / high-FP — flag them only with corroborating context, not as standalone HIGH. Rotated secrets still flagged (they were exposed). `.env.local` in `.gitignore` is expected.

**Diff mode:** Replace `git log -p --all` with `git log -p <base>..HEAD`.

### Phase 3: Dependency Supply Chain

Goes beyond `npm audit`. Checks actual supply chain risk.

**Package manager detection:**
```bash
[ -f package.json ] && echo "DETECTED: npm/yarn/bun"
[ -f Gemfile ] && echo "DETECTED: bundler"
[ -f requirements.txt ] || [ -f pyproject.toml ] && echo "DETECTED: pip"
[ -f Cargo.toml ] && echo "DETECTED: cargo"
[ -f go.mod ] && echo "DETECTED: go"
```

**Standard vulnerability scan:** Run whichever package manager's audit tool is available. Each tool is optional — if not installed, note it in the report as "SKIPPED — tool not installed" with install instructions. This is informational, NOT a finding. The audit continues with whatever tools ARE available.

**Install scripts in production deps (supply chain attack vector):** For Node.js projects with hydrated `node_modules`, check production dependencies for `preinstall`, `postinstall`, or `install` scripts.

**Lockfile integrity:** Check that lockfiles exist AND are tracked by git.

**Severity:** CRITICAL for known CVEs (high/critical) in direct deps. HIGH for install scripts in prod deps / missing lockfile. MEDIUM for abandoned packages / medium CVEs / lockfile not tracked.

**FP rules:** devDependency CVEs are MEDIUM max. `node-gyp`/`cmake` install scripts expected (MEDIUM not HIGH). No-fix-available advisories without known exploits excluded. Missing lockfile for library repos (not apps) is NOT a finding.

### Phase 4: CI/CD Pipeline Security

Check who can modify workflows and what secrets they can access.

**GitHub Actions analysis:** For each workflow file, check for:
- Unpinned third-party actions (not SHA-pinned) — search for `uses:` lines missing `@[sha]`
- `pull_request_target` (dangerous: fork PRs get write access)
- Script injection via `${{ github.event.* }}` in `run:` steps
- Secrets as env vars (could leak in logs)
- CODEOWNERS protection on workflow files

**Severity:** CRITICAL for `pull_request_target` + checkout of PR code / script injection via `${{ github.event.*.body }}` in `run:` steps. HIGH for unpinned third-party actions / secrets as env vars without masking. MEDIUM for missing CODEOWNERS on workflow files.

**FP rules:** First-party `actions/*` unpinned = MEDIUM not HIGH. `pull_request_target` without PR ref checkout is safe (precedent #11). Secrets in `with:` blocks (not `env:`/`run:`) are handled by runtime.

### Phase 5: Infrastructure Shadow Surface

Find shadow infrastructure with excessive access.

**Dockerfiles:** For each Dockerfile, check for missing `USER` directive (runs as root), secrets passed as `ARG`, `.env` files copied into images, exposed ports.

**Config files with prod credentials:** Search for database connection strings (postgres://, mysql://, mongodb://, redis://) in config files, excluding localhost/127.0.0.1/example.com. Check for staging/dev configs referencing prod.

**IaC security:** For Terraform files, check for `"*"` in IAM actions/resources, hardcoded secrets in `.tf`/`.tfvars`. For K8s manifests, check for privileged containers, hostNetwork, hostPID.

**Severity:** CRITICAL for prod DB URLs with credentials in committed config / `"*"` IAM on sensitive resources / secrets baked into Docker images. HIGH for root containers in prod / staging with prod DB access / privileged K8s. MEDIUM for missing USER directive / exposed ports without documented purpose.

**FP rules:** `docker-compose.yml` for local dev with localhost = not a finding (precedent #12). Terraform `"*"` in `data` sources (read-only) excluded. K8s manifests in `test/`/`dev/`/`local/` with localhost networking excluded.

### Phase 6: Webhook & Integration Audit

Find inbound endpoints that accept anything.

**Webhook routes:** Search for files containing webhook/hook/callback route patterns. For each file, check whether it also contains signature verification (signature, hmac, verify, digest, x-hub-signature, stripe-signature, svix). Files with webhook routes but NO signature verification are findings.

**TLS verification disabled:** Search for patterns like `verify.*false`, `VERIFY_NONE`, `InsecureSkipVerify`, `NODE_TLS_REJECT_UNAUTHORIZED.*0`.

**OAuth scope analysis:** Find OAuth configurations and check for overly broad scopes.

**Verification approach (code-tracing only — NO live requests):** For webhook findings, trace the handler code to determine if signature verification exists anywhere in the middleware chain (parent router, middleware stack, API gateway config). Do NOT make actual HTTP requests to webhook endpoints.

**Severity:** CRITICAL for webhooks without any signature verification. HIGH for TLS verification disabled in prod code / overly broad OAuth scopes. MEDIUM for undocumented outbound data flows to third parties.

**FP rules:** TLS disabled in test code excluded. Internal service-to-service webhooks on private networks = MEDIUM max. Webhook endpoints behind API gateway that handles signature verification upstream are NOT findings — but require evidence.

### Phase 7: LLM & AI Security

Check for AI/LLM-specific vulnerabilities. This is a new attack class.

Search for these patterns:
- **Prompt injection vectors:** User input flowing into system prompts or tool schemas — look for string interpolation near system prompt construction
- **Unsanitized LLM output:** `dangerouslySetInnerHTML`, `v-html`, `innerHTML`, `.html()`, `raw()` rendering LLM responses
- **Tool/function calling without validation:** `tool_choice`, `function_call`, `tools=`, `functions=`
- **AI API keys in code (not env vars):** `sk-` patterns, hardcoded API key assignments
- **Eval/exec of LLM output:** `eval()`, `exec()`, `Function()`, `new Function` processing AI responses

**Key checks (beyond pattern matching):**
- Trace user content flow — does it enter system prompts or tool schemas?
- RAG poisoning: can external documents influence AI behavior via retrieval?
- Tool calling permissions: are LLM tool calls validated before execution?
- Output sanitization: is LLM output treated as trusted (rendered as HTML, executed as code)?
- Cost/resource attacks: can a user trigger unbounded LLM calls?

**Severity:** CRITICAL for user input in system prompts / unsanitized LLM output rendered as HTML / eval of LLM output. HIGH for missing tool call validation / exposed AI API keys. MEDIUM for unbounded LLM calls / RAG without input validation.

**FP rules:** User content in the user-message position of an AI conversation is NOT prompt injection (precedent #13). Only flag when user content enters system prompts, tool schemas, or function-calling contexts.

### Phase 8: Skill Supply Chain

Scan installed AI coding agent skills for malicious patterns. 36% of published skills have security flaws, 13.4% are outright malicious (Snyk ToxicSkills research).

**Tier 1 — repo-local (automatic):** Scan the repo's local agent skill/config directories for suspicious patterns. Common locations include `.claude/skills/`, `.cursor/`, `.github/copilot-instructions.md`, and similar agent config paths:

```bash
ls -la .claude/skills/ .cursor/ 2>/dev/null
```

Search all local skill / agent-instruction files for suspicious patterns:
- `curl`, `wget`, `fetch`, `http`, `exfiltrat` (network exfiltration)
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `env.`, `process.env` (credential access)
- `IGNORE PREVIOUS`, `system override`, `disregard`, `forget your instructions` (prompt injection)

**Tier 2 — global skills (requires permission):** Before scanning globally installed skills or user settings, ask the user:
"Phase 8 can scan your globally installed AI coding agent skills and hooks for malicious patterns. This reads files outside the repo. Want to include this?"
Options: A) Yes — scan global skills too  B) No — repo-local only

If approved, run the same patterns on globally installed skill files and check hooks in user settings.

**Severity:** CRITICAL for credential exfiltration attempts / prompt injection in skill files. HIGH for suspicious network calls / overly broad tool permissions. MEDIUM for skills from unverified sources without review.

**FP rules:** First-party skills from a known, trusted toolchain are trusted (verify the skill path resolves to a known trusted source). Skills that use `curl` for legitimate purposes (downloading tools, health checks) need context — only flag when the target URL is suspicious or when the command includes credential variables.

### Phase 9: OWASP Top 10 Assessment

For each OWASP category, perform targeted analysis. Search code scoped to the file extensions of stacks detected in Phase 0.

#### A01: Broken Access Control
- Check for missing auth on controllers/routes (skip_before_action, skip_authorization, public, no_auth)
- Check for direct object reference patterns (params[:id], req.params.id, request.args.get)
- Can user A access user B's resources by changing IDs?
- Is there horizontal/vertical privilege escalation?

#### A02: Cryptographic Failures
- Weak crypto (MD5, SHA1, DES, ECB) or hardcoded secrets
- Is sensitive data encrypted at rest and in transit?
- Are keys/secrets properly managed (env vars, not hardcoded)?

#### A03: Injection
- SQL injection: raw queries, string interpolation in SQL
- Command injection: system(), exec(), spawn(), popen
- Template injection: render with params, eval(), html_safe, raw()
- LLM prompt injection: see Phase 7 for comprehensive coverage

#### A04: Insecure Design
- Rate limits on authentication endpoints?
- Account lockout after failed attempts?
- Business logic validated server-side?

#### A05: Security Misconfiguration
- CORS configuration (wildcard origins in production?)
- CSP headers present?
- Debug mode / verbose errors in production?

#### A06: Vulnerable and Outdated Components
See **Phase 3 (Dependency Supply Chain)** for comprehensive component analysis.

#### A07: Identification and Authentication Failures
- Session management: creation, storage, invalidation
- Password policy: complexity, rotation, breach checking
- MFA: available? enforced for admin?
- Token management: JWT expiration, refresh rotation

#### A08: Software and Data Integrity Failures
See **Phase 4 (CI/CD Pipeline Security)** for pipeline protection analysis.
- Deserialization inputs validated?
- Integrity checking on external data?

#### A09: Security Logging and Monitoring Failures
- Authentication events logged?
- Authorization failures logged?
- Admin actions audit-trailed?
- Logs protected from tampering?

#### A10: Server-Side Request Forgery (SSRF)
- URL construction from user input?
- Internal service reachability from user-controlled URLs?
- Allowlist/blocklist enforcement on outbound requests?

### Phase 10: STRIDE Threat Model

For each major component identified in Phase 0, evaluate:

```
COMPONENT: [Name]
  Spoofing:             Can an attacker impersonate a user/service?
  Tampering:            Can data be modified in transit/at rest?
  Repudiation:          Can actions be denied? Is there an audit trail?
  Information Disclosure: Can sensitive data leak?
  Denial of Service:    Can the component be overwhelmed?
  Elevation of Privilege: Can a user gain unauthorized access?
```

### Phase 11: Data Classification

Classify all data handled by the application:

```
DATA CLASSIFICATION
═══════════════════
RESTRICTED (breach = legal liability):
  - Passwords/credentials: [where stored, how protected]
  - Payment data: [where stored, PCI compliance status]
  - PII: [what types, where stored, retention policy]

CONFIDENTIAL (breach = business damage):
  - API keys: [where stored, rotation policy]
  - Business logic: [trade secrets in code?]
  - User behavior data: [analytics, tracking]

INTERNAL (breach = embarrassment):
  - System logs: [what they contain, who can access]
  - Configuration: [what's exposed in error messages]

PUBLIC:
  - Marketing content, documentation, public APIs
```
