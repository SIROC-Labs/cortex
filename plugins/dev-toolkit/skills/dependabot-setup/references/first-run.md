# What to watch on the first run

The first week of Dependabot PRs shows what the config got wrong. Check them with
`gh pr list --author app/dependabot --state open`, then fix the config, not the PRs.

| Symptom | Cause | Fix |
|---|---|---|
| Dependabot jobs stay queued, no PRs | Org runs Dependabot on self-hosted runners and none has the `dependabot` label | Add the runner or turn the org setting off. |
| Two PRs for one framework, both fail `npm ci` with `ERESOLVE` | Coupled packages bumped separately (e.g. `react-dom` without `react`) | Add a group for that framework's majors, placed before `<eco>-minor-patch`. |
| PR only raises a `>=` floor in the manifest | Default versioning strategy on a floors-only manifest | `versioning-strategy: lockfile-only`. |
| A major PR that can never pass (peer range elsewhere caps it) | Upstream not ready | `ignore` that major, with a comment naming what to watch. |
| `@types/node` jumps to a Node major the project doesn't run | npm's latest, not the runtime | Ignore `@types/node` majors; bump them with `.nvmrc`. |
| CI fails with missing env var or auth error | Workflows triggered by Dependabot get no Actions secrets | Add the secret under Dependabot secrets, or skip that job when `github.actor == 'dependabot[bot]'`. |
| CI fails on a PR that only changes a lock file, with lint or type errors | Failure already on the default branch | Fix the default branch; the update isn't the cause. |
| PR has merge conflicts in the lock file | Base moved on | Comment `@dependabot rebase`. |
| Too many PRs | Missing groups or limit | Check every entry has `<eco>-minor-patch` and `open-pull-requests-limit: 3`. |

Security PRs show up outside the schedule. If one appears in the first week, handle it before the routine ones.
