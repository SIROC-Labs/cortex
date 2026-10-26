# What to watch on the first run

The first week of Dependabot PRs shows what the config got wrong. Check them with
`gh pr list --author app/dependabot --state open`, then fix the config, not the PRs.

| Symptom | Cause | Fix |
|---|---|---|
| Dependabot jobs stay queued, no PRs | Org runs Dependabot on self-hosted runners and none has the `dependabot` label | Add the runner or turn the org setting off. |
| Two PRs for one framework, both fail to install (`ERESOLVE`, peer conflicts) | Packages whose peer ranges couple them were bumped separately | Add a group for that framework's majors, placed before `<eco>-minor-patch`. |
| PR only raises a `>=` floor in the manifest | Default versioning strategy on a floors-only manifest | `versioning-strategy: lockfile-only`. |
| A major PR that can never pass (peer range elsewhere caps it) | Upstream not ready | `ignore` that major, with a comment naming what to watch. |
| Type or SDK packages jump to a runtime major the project doesn't run | The registry's latest, not the pinned runtime | Ignore their majors; bump them with the version file. |
| CI fails with missing env var or auth error | Workflows triggered by Dependabot get no Actions secrets | Add the secret under Dependabot secrets, scoped to what the job needs. Skip the job for `dependabot[bot]` only if it isn't validation (a deploy or a preview, say); never skip tests, builds or security checks, since those are the point of the PR. |
| CI fails on a PR that only changes a lock file, with lint or type errors | Either a transitive update changed types or lint rules, or the failure already exists on the default branch | Run the same check on the base revision first. If it fails there too, fix the default branch; if not, the update is the cause, so treat it like any breaking update. |
| PR has merge conflicts in the lock file | Base moved on | Comment `@dependabot rebase`. |
| Too many PRs | Missing groups or limit | Check every entry has a minor+patch group, and the policy's limit. |

Security PRs show up outside the schedule. If one appears in the first week, handle it before the routine ones.
