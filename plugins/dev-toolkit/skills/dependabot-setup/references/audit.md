# Daily audit workflow

Dependabot alerts cover manifests it can parse. This workflow covers two gaps:

1. **Lock files between PRs.** PR CI usually audits only the trees a PR touches. An advisory published against an unchanged lock file waits until someone edits that tree.
2. **Runtimes.** A version in a version file (`.nvmrc`, `.python-version`, `.tool-versions`, `mise.toml`, `engines`, and the like) has no lock file and no Dependabot alert.

## Audit command per lock file

Pick the command from the tool, not from memory:

1. **The package manager's own audit**, if it has one: check `<tool> --help` and `<tool> audit --help` for the installed version. Use its flags for production dependencies only, the committed lock file as-is (no new resolution), and the policy's severity threshold.
2. **Otherwise, OSV-Scanner**, which reads most lock file formats: `osv-scanner scan source --lockfile=<path>`. Use its GitHub Action (`google/osv-scanner-action`) so no install step is needed.

Whichever tool it is, confirm from its documentation that the **exit code** follows the threshold and the production-only filter, not just the printed output. Some flags only filter what is shown (Yarn Classic's `--level` doesn't change the exit code), and OSV-Scanner fails on any finding of any severity. When the tool can't enforce the policy itself, write its JSON output and fail the job on that: count findings at or above the threshold in production dependencies.

If the native audit is experimental or behind a flag, say so in a comment and in the report.

Verified behaviour of audits this skill has used:

| Tool | Command | Exit code |
|---|---|---|
| pnpm 10 | `pnpm audit --prod --audit-level high` | Follows both: non-zero only for advisories at or above the level, with dev dependencies dropped before the query. Reads the lock file without installing. |
| npm | `npm audit --package-lock-only --omit=dev --audit-level=high` | Follows both. |
| uv | `uv audit --frozen --no-dev --preview-features audit-command,json-output --output-format json` | Preview. Exits 1 on a finding of any severity, and the JSON carries no severity. Read the report, rate each advisory from OSV (`https://api.osv.dev/v1/vulns/<GHSA id>`, `.database_specific.severity`, preferring the GHSA alias), and fail on high, critical or unrated. An exit code above 1 means the audit did not run. A library audits every extra by default: add `--no-extra <name>` for extras that are not runtime (samples, docs). |

## Runtime check per version file

Derive the product from endoflife.date's catalog, not a list. `https://endoflife.date/api/v1/products` returns each product's name and aliases; match the version file's tool name against those. Identifiers (`pkg:docker/...` and the like) are only in the product details, at each summary's `uri` or `/api/v1/products/full`, so fetch those when a name match fails. Then, for the pinned release cycle (`/api/v1/products/<product>/releases/<cycle>`):

- Fail when `isEol` is true.
- If the product publishes a per-release security flag (Node's `https://nodejs.org/dist/index.json` has `security` on each release): fail when any release newer than the full pin on the same cycle has the flag set to true. Check every release between the pin and the latest, not only the latest; a routine release with `security: false` must not fail the job.
- Without such a flag, warn when `latest.name` is newer, don't fail: a newer patch isn't always a security fix.

A floating pin (`24`, `lts/*`, `3.13`) can only be checked for end of life. Say so, and suggest a full pin.

## Policy (fixed)

| Policy | Value |
|---|---|
| Frequency | daily at 05:00 UTC, before the first Dependabot slot, plus `workflow_dispatch` |
| Fails on | high and critical |
| Dependencies | production only |
| Permissions | `contents: read` |
| Timeout | on every job |

## Needs (from the repository)

| Choice | Source |
|---|---|
| Runner labels, setup actions | The repository's existing CI workflows. |
| Action pins | If existing workflows pin to commit SHAs, pin the same way: resolve each tag with `gh api repos/<owner>/<action>/commits/<tag> -q .sha`, keep the tag in a trailing comment, and prefer a release at least two weeks old. Reuse a SHA an existing workflow already pins. Otherwise follow the repository's style. |
| Working directory | Where each lock file is. |
| Notification | A scheduled failure emails only the last editor of the cron. Offer the team's channel (an issue, or a webhook the user names); don't add one without it. |

## Skeleton

```yaml
name: Audit

# Pull requests audit only the tree they touch, so an advisory against an unchanged lock file would otherwise go unseen.
on:
  schedule:
    - cron: '0 5 * * *'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  <lock file>:
    runs-on: <the repo's runner>
    timeout-minutes: 10
    steps:
      - uses: <checkout, pinned the repo's way>
      - uses: <setup action the repo's CI uses, reading the version file>
      - run: <audit command for this lock file>
        working-directory: <dir>

  <runtime>:
    runs-on: <the repo's runner>
    timeout-minutes: 5
    steps:
      - uses: <checkout>
      - run: <read the version file; query endoflife.date and the product's security feed; fail as above>
```
