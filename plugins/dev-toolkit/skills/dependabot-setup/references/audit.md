# Daily audit workflow

Dependabot alerts cover manifests it can parse. This workflow covers two gaps:

1. **Lock files between PRs.** PR CI usually audits only the trees a PR touches. An advisory published against an unchanged lock file waits until someone edits that tree.
2. **Runtimes.** A Node or Python version in `.nvmrc` or `.python-version` has no lock file and no Dependabot alert.

## Audit commands

Production dependencies only, failing on high and critical. Use the lock file as-is, never resolve again.

| Package manager | Command |
|---|---|
| uv | `uv audit --locked --no-dev --preview-features audit-command` (experimental; fall back to `uvx pip-audit` on an exported requirements file if the installed uv lacks it) |
| pip / Poetry | `uvx pip-audit -r requirements.txt` (export first with `poetry export` or `uv export --no-dev`) |
| npm | `npm audit --omit=dev --audit-level=high` |
| pnpm | `pnpm audit --prod --audit-level high` |
| yarn (berry) | `yarn npm audit --environment production --severity high` |
| Bundler | `bundle exec bundle-audit check --update` |
| Go | `go run golang.org/x/vuln/cmd/govulncheck@latest ./...` |
| Cargo | `cargo audit` (install with `cargo install cargo-audit --locked`) |
| Composer | `composer audit --no-dev` |

Before writing a command, check the installed tool's `--help`: flags differ between major versions.

## Runtime security check (Node)

nodejs.org publishes every release with a `security` flag. Fail when a newer security release exists on the pinned major:

```yaml
  # No lock file or Dependabot covers the Node runtime in .nvmrc.
  node:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@<sha> # <tag>
      - run: |
          pinned="$(tr -d '[:space:]' < .nvmrc)"
          newer="$(curl -fsSL https://nodejs.org/dist/index.json | jq -r --arg pinned "$pinned" '
            def parts: ltrimstr("v") | split(".") | map(tonumber);
            ($pinned | parts) as $p
            | .[] | select(.security and ((.version | parts) as $r | $r[0] == $p[0] and $r > $p)) | .version')"
          if [ -n "$newer" ]; then
            echo "::error file=.nvmrc::Node $pinned has newer security releases: $(echo "$newer" | xargs)"
            exit 1
          fi
          echo "Node $pinned: no newer security release on its line"
```

This needs a full `major.minor.patch` pin. If `.nvmrc` holds `24` or `lts/*`, tell the user: a floating pin can't be checked, and CI installs whatever is latest that day. Suggest pinning the full version.

For other runtimes, check end of life with `https://endoflife.date/api/v1/products/<product>/` (`isEol` per release cycle) and fail when the pinned cycle is end of life. Only add this when the repo pins the runtime.

## Workflow skeleton

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
  <ecosystem>:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: <dir>   # only when the lock file is not at the root
    steps:
      - uses: actions/checkout@<sha> # <tag>
      - uses: <setup action>@<sha> # <tag>   # reads the runtime pin file when one exists
      - run: <audit command>
```

- Run before the Dependabot slot (05:00 UTC when Dependabot starts at 06:00), so a red audit and the security PR show up together.
- If the repo pins actions to SHAs, resolve each tag to its commit with `gh api repos/<owner>/<action>/commits/<tag> -q .sha` and keep the tag in a trailing comment. Pick a release at least two weeks old.
- Reuse the runner labels and setup actions the repo's CI already uses.
- A scheduled workflow's failure emails the person who last edited the cron. For team visibility, suggest a Slack or issue notification step, but don't add one without a webhook the user names.
