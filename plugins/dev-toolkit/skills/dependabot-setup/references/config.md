# dependabot.yml policy

## Per key

| Key | Value | Why |
|---|---|---|
| `schedule` | `weekly`, same day, one ecosystem per 30-minute slot from 06:00 UTC | PRs don't land together, and CI isn't flooded at once. |
| `open-pull-requests-limit` | `3` | With grouping, three open PRs per ecosystem is plenty. A higher limit only grows the review queue. |
| `cooldown.default-days` | `7` | Most malicious releases are caught and yanked within days. Security updates ignore the cooldown. |
| `cooldown.semver-major-days` | `30` where supported | Majors break more and get more fixes in their first weeks. |
| `groups.<eco>-security` | `applies-to: security-updates`, `patterns: ['*']` | One security PR per ecosystem instead of one per advisory. |
| `groups.<eco>-minor-patch` | `update-types: [minor, patch]` | One routine PR per ecosystem per week. Majors stay as their own PRs. |
| `commit-message.prefix` | Matches the repo's convention, e.g. `chore(deps)`, `chore(ci)`, `chore(infra)` | Commit and PR titles pass commit linting. The prefix also applies to security-update PRs. |
| `commit-message.prefix-development` | e.g. `chore(deps-dev)` | Supported by bundler, composer, mix, maven, npm, pip and uv. |
| `versioning-strategy` | `lockfile-only` when every constraint is a `>=` floor | Otherwise Dependabot raises the floor in the manifest, which is noise. Keep the default when the manifest pins exact versions. |

Don't change `target-branch` unless the repo merges into a branch other than its default.

## SemVer cooldown keys

`semver-major-days`, `semver-minor-days` and `semver-patch-days` only apply to ecosystems with SemVer versioning, among them bundler, bun, cargo, composer, gomod, gradle, maven, npm, nuget, pip, pub, swift and uv. `github-actions`, `docker`, `docker-compose`, `helm`, `terraform` and `pre-commit` don't support them: use `default-days` alone. If you're unsure about one, check the options reference; the schema check accepts the key either way.

## Group order

A dependency joins the first group it matches. Put narrow groups (a framework's majors) before the broad `<eco>-minor-patch` group.

## Coupled majors

Packages that must move together go into one group for majors. If they don't, Dependabot opens one PR per package and each fails to install on its own (`ERESOLVE`, peer conflicts). Typical sets:

- React: `react`, `react-dom`, `@types/react`, `@types/react-dom`, plus a router that follows React's major.
- Angular: `@angular/*`. Vue: `vue`, `@vue/*`. ESLint: `eslint`, `@eslint/*`, `typescript-eslint`.

Only add a coupled group for packages the repo actually uses, and only when their current versions show the coupling (a peer range in the lock file, a shared major). The sets above are illustrations, not a checklist.

## Ignores worth having

- `@types/node` majors when the Node major is pinned in `.nvmrc`. The types should follow the runtime, not npm's latest.
- A major blocked by a peer range elsewhere (e.g. `typescript` while `typescript-eslint` caps it). The comment says which package to watch.

Add an ignore only when the repo's own versions or peer ranges show the conflict today; don't copy these examples. Ignores only affect version updates. Security updates still arrive.

## Ecosystem notes

- **Workspaces** (uv, npm, pnpm, yarn): one entry at the workspace root.
- **github-actions:** `directory: /` covers `.github/workflows`. If actions are pinned to a SHA with the tag in a trailing comment, Dependabot updates both.
- **docker:** one entry per directory that has a Dockerfile, or `directories:` with globs.
- **terraform:** watch the root stacks that own provider constraints and lock files, not the modules. `directories:` with globs plus `group-by: dependency-name` in the minor-patch group (it needs `directories:`) gives one PR per provider across every stack, so the stacks stay on the same version.
- **docker-compose:** use `package-ecosystem: docker-compose` for image tags in compose files.

## Example

```yaml
version: 2

# Weekly, one ecosystem every half hour from 06:00 UTC so the pull requests do not land together. Minors and patches
# arrive as one grouped pull request per ecosystem; a major arrives on its own, after a longer cooldown where the
# ecosystem supports SemVer. Security updates skip the cooldown and the schedule, and arrive grouped per ecosystem.
# Dependabot pull requests are never auto-merged.
updates:
  - package-ecosystem: uv
    directory: /
    schedule: { interval: weekly, day: monday, time: '06:00' }
    open-pull-requests-limit: 3
    cooldown: { default-days: 7, semver-major-days: 30 }
    # Every constraint is a floor, so an update only moves uv.lock; a raised floor would be noise.
    versioning-strategy: lockfile-only
    commit-message: { prefix: chore(deps), prefix-development: chore(deps-dev) }
    groups:
      uv-security: { applies-to: security-updates, patterns: ['*'] }
      uv-minor-patch: { update-types: [minor, patch] }

  - package-ecosystem: npm
    directory: /apps/web
    schedule: { interval: weekly, day: monday, time: '06:30' }
    open-pull-requests-limit: 3
    cooldown: { default-days: 7, semver-major-days: 30 }
    commit-message: { prefix: chore(web) }
    groups:
      npm-security: { applies-to: security-updates, patterns: ['*'] }
      # React's majors move together: react-dom pins react as a peer.
      react:
        patterns: [react, react-dom, '@types/react', '@types/react-dom']
        update-types: [major]
      npm-minor-patch: { update-types: [minor, patch] }
    ignore:
      # @types/node follows the Node major in .nvmrc, not npm's latest.
      - dependency-name: '@types/node'
        update-types: ['version-update:semver-major']

  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly, day: monday, time: '07:00' }
    open-pull-requests-limit: 3
    cooldown: { default-days: 7 }
    commit-message: { prefix: chore(ci) }
    groups:
      actions-security: { applies-to: security-updates, patterns: ['*'] }
      actions-minor-patch: { update-types: [minor, patch] }

  - package-ecosystem: terraform
    directories: [/infra/envs/*]
    schedule: { interval: weekly, day: monday, time: '07:30' }
    open-pull-requests-limit: 3
    cooldown: { default-days: 7 }
    commit-message: { prefix: chore(infra) }
    groups:
      terraform-security: { applies-to: security-updates, patterns: ['*'] }
      terraform-minor-patch: { update-types: [minor, patch], group-by: dependency-name }
```

Write the real file in block style if the repo's YAML is block style; the flow style here is for brevity.
