---
name: dependabot-setup
version: 0.1.0
description: Use when setting up, auditing or tightening Dependabot and dependency vulnerability scanning, for one repository or a whole GitHub organization. Covers "set up dependabot", "add a dependabot.yml", "our dependabot PRs are noisy", "turn on security alerts", "scan dependencies daily", "audit our lock files on a cron", "which of our repos have dependabot", "enable dependabot across the org", or a repo with no `.github/dependabot.yml`. Project mode writes a grouped, cooldown-gated, staggered dependabot.yml, turns on alerts and security updates, and adds a daily audit workflow. Organization mode reports coverage across every repository and applies an org security configuration.
---

# Dependabot Setup

Set up dependency updates and vulnerability scanning so the team gets few, reviewable pull requests and still hears about a security advisory within a day. Every choice here comes from a failure seen in a real repository; the references explain each one.

## Pick the mode

- **Project mode** (default): the current repository, or one the user names. Writes files in that repository.
- **Organization mode**: the user names an org or asks about "all our repos". Needs org admin rights. Reads every repository, applies settings at org level, and runs project mode per repository only when the user picks which ones. Follow `references/organization.md`.

If the request is ambiguous, ask which mode. Organization mode changes many repositories at once, so never fall into it by default.

## Project mode

### 1. Inventory

Find out what exists before writing anything:

- **Ecosystems and directories:** manifests and lock files (`uv.lock`, `poetry.lock`, `requirements*.txt`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Gemfile.lock`, `go.sum`, `Cargo.lock`, `composer.lock`, `Dockerfile*`, `compose*.yml`, `*.tf` with `.terraform.lock.hcl`, `.github/workflows/*.yml`). Skip `node_modules`, `.venv` and vendored trees. A workspace (uv, npm, pnpm) is one entry at its root.
- **Existing config:** `.github/dependabot.yml`, audit or CI workflows, Renovate config. If Renovate is present, ask which tool should own updates; running both doubles every PR.
- **Conventions:** commit style from `git log` (prefixes must match it), default branch, whether actions are pinned to commit SHAs.
- **Runtime pins:** `.nvmrc`, `.node-version`, `.python-version`, `.tool-versions`, `engines`. Dependabot neither updates nor alerts on these.
- **Constraint style:** floors (`>=`) or exact pins. This decides `versioning-strategy`.

### 2. Repository settings

Read first, then turn on Dependabot alerts and security updates. Commands and admin-rights handling are in `references/settings.md`. Report secret scanning and code scanning state; don't try to enable them.

### 3. Write `.github/dependabot.yml`

Follow `references/config.md`: policy per key, a full example, and ecosystem-specific rules. If a config exists, keep its working parts and explain each change.

### 4. Write `.github/workflows/audit.yml`

Follow `references/audit.md`: one job per lock file with that package manager's audit command, one job per pinned runtime with a security feed, a daily cron plus `workflow_dispatch`, `permissions: contents: read`, a timeout on every job, and SHA-pinned actions if the repo already pins them.

PR CI usually runs only on the trees a PR touches, so an advisory against an unchanged lock file goes unseen. The daily job closes that gap.

### 5. Validate

```bash
uvx check-jsonschema --builtin-schema vendor.dependabot .github/dependabot.yml
actionlint .github/workflows/audit.yml      # if installed
```

Run each audit command locally and report the result. If one fails today, say so: the workflow will be red from its first run, and that is a finding, not a reason to loosen the threshold.

### 6. Report

Lead with what was turned on and what was written. Keep what you observed (a failing PR, a peer range in the lock file) separate from what you expect; without PR history, causes are predictions, so say so. Then list each ecosystem and directory with its schedule slot, anything left out on purpose and why, and what to watch on the first run (`references/first-run.md`).

Do not commit or push unless the user asks.

## Rules in both modes

- **Never auto-merge Dependabot PRs.** A cooldown delays a compromised release; it does not replace review.
- **No `multi-ecosystem-groups`.** One PR across ecosystems is harder to review and to roll back.
- **Every `ignore` gets a comment** saying why and when to lift it.
- **Read before writing** any setting, and show the user what will change before changing more than one repository.
- **Check option names against the [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)** when unsure. The schema check catches typos, not semantics.
