---
name: dependabot-setup
version: 0.1.0
description: Use when setting up, auditing or tightening Dependabot and dependency vulnerability scanning, for one repository or a whole GitHub organization. Covers "set up dependabot", "add a dependabot.yml", "our dependabot PRs are noisy", "turn on security alerts", "scan dependencies daily", "audit our lock files on a cron", "which of our repos have dependabot", "enable dependabot across the org", or a repo with no `.github/dependabot.yml`. Project mode applies a fixed policy (weekly, grouped, cooldown-gated, staggered, never auto-merged) to the ecosystems, directories and runtimes it finds in the repository, turns on alerts and security updates, and adds a daily audit workflow. Organization mode reports coverage across every repository and applies an org security configuration.
---

# Dependabot Setup

Set up dependency updates and vulnerability scanning so the team gets few, reviewable pull requests and still hears about a security advisory within a day. Every choice here comes from a failure seen in a real repository; the references explain each one.

## Pick the mode

- **Project mode** (default): the current repository, or one the user names. Writes files in that repository.
- **Organization mode**: the user names an org or asks about "all our repos". Needs org admin rights. Reads every repository, applies settings at org level, and runs project mode per repository only when the user picks which ones. Follow `references/organization.md`.

If the request is ambiguous, ask which mode. Organization mode changes many repositories at once, so never fall into it by default.

## Project mode

### 1. Inventory

The policy (schedule, limits, cooldowns, grouping, audit threshold) is fixed and lives in the references. The needs come from this step: what to cover, where, what couples and how commits are named. Nothing about the repository is assumed or copied from an example.

- **Ecosystems and directories:** the ecosystems Dependabot supports come from its schema; find each one's manifests in the tree (skip dependency and vendored directories) and cross-check with GitHub's dependency graph.
- **Existing setup:** `.github/dependabot.yml`, CI and scheduled workflows, any other update bot. If another bot owns updates, ask which tool should; running both doubles every PR.
- **Conventions:** commit types and scopes from `git log`, the default branch and any integration branch, runner labels, and how actions are pinned.
- **Private dependencies:** private registries and private Git dependencies, and whether Dependabot secrets exist for them. Without access, every update fails to resolve.
- **History:** if Dependabot ran before, its open, merged and failed PRs. They show which groups and ignores the repository needs.
- **Version files:** any file that pins a runtime or tool version. Dependabot neither updates nor alerts on these.
- **Constraint style and peer ranges:** floors or exact pins in manifests, and peer dependencies in lock files. These decide `versioning-strategy`, coupled groups and ignores.

### 2. Repository settings

Read first, then turn on Dependabot alerts and security updates. Commands and admin-rights handling are in `references/settings.md`. Report secret scanning and code scanning state; don't try to enable them.

### 3. Write `.github/dependabot.yml`

Follow `references/config.md`: the fixed policy, where each need comes from, and the shape of the file. If a config exists, keep its working parts and explain each change.

### 4. Write `.github/workflows/audit.yml`

Follow `references/audit.md`: one job per lock file with that package manager's audit command, one job per pinned runtime with a security feed, the policy's daily schedule and severity threshold, and actions pinned the way the repository pins them.

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

- **The policy is fixed; the needs are found.** Don't tune the policy per repository, and don't add a need (ecosystem, group, ignore, runtime check) the repository doesn't show.
- **Never auto-merge Dependabot PRs.** A cooldown delays a compromised release; it does not replace review.
- **Every `ignore` gets a comment** saying why and when to lift it.
- **Read before writing** any setting, and show the user what will change before changing more than one repository.
- **Check option names against the [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)** when unsure. The schema check catches typos, not semantics.
