# dependabot.yml

Two kinds of value go into the file:

- **The policy** is fixed. It is the same in every repository and the skill applies it as written.
- **The needs** come from the repository: which ecosystems and directories to cover, what couples, what to ignore, and how commits are named. Nothing about them is assumed or copied from an example.

## Policy (fixed)

| Key | Value | Why |
|---|---|---|
| `schedule` | `weekly`, Monday, one entry per 30-minute slot from 06:00 UTC | PRs don't land together, and CI isn't flooded at once. |
| `open-pull-requests-limit` | `3` | Per entry, version updates only; security updates have their own fixed limit of 10. A grouped PR counts as one, so 3 is the weekly minor+patch PR plus up to two majors. A further major waits until one closes: backpressure, so stalled majors stay visible instead of piling up. GitHub's default is 5. |
| `cooldown.default-days` | `7` | Most malicious releases are caught and yanked within days. Security updates skip the cooldown. |
| `cooldown.semver-major-days` | `30`, where the ecosystem supports it | Majors break more and get more fixes in their first weeks. |
| `groups.<eco>-security` | `applies-to: security-updates`, `patterns: ['*']` | One security PR per entry instead of one per advisory. |
| `groups.<eco>-minor-patch` | `update-types: [minor, patch]` | One routine PR per entry per week. Majors stay as their own PRs. |
| Auto-merge | never | A cooldown delays a compromised release; it doesn't replace review. |
| `multi-ecosystem-groups` | none | One PR across ecosystems is harder to review and roll back. |

## Needs (from the repository)

| Key | Source |
|---|---|
| `package-ecosystem` | The `package-ecosystem` enum in the Dependabot schema: `curl -fsSL https://json.schemastore.org/dependabot-2.0.json \| jq -c '.. \| objects \| select(.enum? and (.enum \| index("npm"))) \| .enum'`. For each value, look for that ecosystem's manifests in the tree. |
| `directory` / `directories` | Where those manifests are. Cross-check with what GitHub detected: `gh api graphql -f query='{repository(owner:"<o>",name:"<r>"){dependencyGraphManifests(first:100){nodes{blobPath}}}}'`. The dependency graph misses some ecosystems (Docker, Terraform), so the tree is the source of truth. A workspace (its root manifest declares members) is one entry at its root. |
| `commit-message.prefix` | `git log` subjects: the convention, and the type and scope used for each directory. `prefix-development` only where the options reference allows it for that ecosystem. |
| `versioning-strategy` | The manifest's constraint style and the lock file. `lockfile-only` only when every constraint is a floor (`>=`), the entry's directory has a committed lock file Dependabot updates, and the options reference lists the strategy for that ecosystem; an update then moves only the lock file. A floors-only manifest without a lock file (typical for a library), exact pins, or mixed → the default. |
| Where `semver-major-days` applies | The SemVer column of the cooldown table in the [options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference). Without SemVer support, `default-days` alone. The schema accepts the key either way. |
| Coupled-major groups | The lock file's peer dependencies. Packages whose peer ranges pin each other's major must move together, or each PR fails to install on its own (`ERESOLVE`). Group them for majors, before `<eco>-minor-patch`: a dependency joins the first group it matches. |
| `ignore` | A conflict visible today: a major that a peer range in the lock file excludes, or type packages that follow a runtime pinned in a version file. The comment names the constraint and when to lift it. Use the `update-types` form (`version-update:semver-major`); only that form leaves security updates untouched. Ignoring a dependency outright, or by `versions`, can also block its security updates: don't add one, and flag any existing one in the report. |
| `registries` | Private registries and private Git dependencies: registry URLs in `.npmrc`, `pip.conf`, `uv`/Poetry sources, `Gemfile` sources, Go `GOPRIVATE`, Git URLs in manifests. Add a `registries` block per source and reference it from the entry, using Dependabot secrets for credentials. Report which secrets must exist; without them every update for that entry fails to resolve, even though the file validates. |
| `group-by: dependency-name` | Several directories that pin the same dependencies, each with its own lock file: one PR per dependency across all of them. Needs `directories:`. |
| `target-branch` | Only if the repository merges into a branch other than its default. An entry with `target-branch` applies to version updates only, so its security group stops working. Keep a second entry for the same ecosystem and directory on the default branch with the security group and `open-pull-requests-limit: 0` (security updates only), so the policy's grouped security PRs still apply. |

If a config exists, bring it to the policy, keep the needs it already covers correctly, and explain every change.

## Shape

Policy values as written; placeholders are needs from the repository.

```yaml
version: 2

# Weekly, one entry every half hour from 06:00 UTC so the pull requests do not land together. Minors and patches
# arrive as one grouped pull request per entry; a major arrives on its own, after a longer cooldown where the ecosystem
# supports SemVer. Security updates skip the cooldown and the schedule, and arrive grouped. Never auto-merged.
updates:
  - package-ecosystem: <schema enum value>
    directory: <manifest location>
    schedule:
      interval: weekly
      day: monday
      time: '<next 30-minute slot from 06:00>'
    open-pull-requests-limit: 3
    cooldown:
      default-days: 7
      semver-major-days: 30              # only where supported
    versioning-strategy: lockfile-only # only when every constraint is a floor
    commit-message:
      prefix: <type(scope) from git log>
    groups:
      <eco>-security:
        applies-to: security-updates
        patterns: ['*']
      # <the peer range that couples these>
      <coupled-set>:
        patterns: [<packages>]
        update-types: [major]
      <eco>-minor-patch:
        update-types: [minor, patch]
    ignore:
      # <the constraint, and when to lift this>
      - dependency-name: <package>
        update-types: ['version-update:semver-major']
```

Match the repository's YAML style.
