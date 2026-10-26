# Organization mode

For an org admin who wants every repository covered, and new ones covered by default. Per-repo settings drift: a repository created tomorrow starts with everything off.

## 1. Check access

```bash
gh api user/memberships/orgs/{org} -q .role        # must be "admin"
gh api orgs/{org} -q .plan.name                    # free, team, enterprise
```

Not an admin: stop after the coverage report (step 2) and hand it to the user for an admin. The GitHub plan decides what's available: secret scanning and code scanning on private repositories need GitHub Advanced Security.

## 2. Coverage report

List active repositories, skipping archived, forks (unless the user wants them) and empty ones:

```bash
gh api --paginate orgs/{org}/repos -q '.[] | select(.archived|not) | select(.size>0) | [.name, .fork, .private, .default_branch, .pushed_at] | @tsv'
```

For each, read:

- Dependabot alerts on (`repos/{org}/{r}/vulnerability-alerts`, 204 or 404)
- Security updates (`repos/{org}/{r}/automated-security-fixes`)
- A `.github/dependabot.yml` on the default branch (`repos/{org}/{r}/contents/.github/dependabot.yml`, 200 or 404)
- A scheduled audit workflow (any `.github/workflows/*.yml` with `schedule:` that runs an audit command)
- Attached security configuration (`repos/{org}/{r}/code-security-configuration`)

Run the calls in parallel batches; a sequential loop over 100 repositories takes minutes. Present a table sorted worst first, plus totals: how many repositories have alerts, security updates, a dependabot.yml and an audit workflow. Mark repositories with no push in over a year: they are candidates to archive rather than to configure.

Also count open alerts by severity:

```bash
gh api --paginate 'orgs/{org}/dependabot/alerts?state=open&per_page=100' -q '.[] | [.repository.name, .security_advisory.severity] | @tsv'
```

## 3. Policy source

Ask whether a repository in the org already has the setup the team wants (a reviewed `dependabot.yml` and audit workflow). If so, compare it with the skill's policy and point out differences, so the org settles on one policy. Every repository still finds its own needs: ecosystems, directories, prefixes, coupled groups, ignores and runtimes.

## 4. Exclusions

Ask which repositories to leave out: archived-to-be, demos, forks, third-party mirrors. Keep the list in the report so the next run uses it.

## 5. Org security configuration

Show the user the commands and the number of repositories they touch. Run them only after an explicit yes.

**Guard: don't switch anything off.** The configuration below is about Dependabot. Settings it leaves out, and `advanced_security=disabled`, could turn off a protection a repository already has. Before attaching, read each selected repository's other security features (see `settings.md`): secret scanning, push protection, code scanning default setup, private vulnerability reporting, Advanced Security. If any is on in a repository, stop for that repository: leave it out of the attach list and report it with what is on, for a separate decision. The usual procedure carries on for every other repository. Repositories whose state reads as unknown are treated as on.

```bash
# Reuse one if it exists
gh api orgs/{org}/code-security/configurations -q '.[] | [.id, .name] | @tsv'

# Otherwise create one: dependency graph, alerts and security updates on, enforced
gh api -X POST orgs/{org}/code-security/configurations \
  -f name="dependabot baseline" -f description="Dependency graph, Dependabot alerts and security updates" \
  -f dependency_graph=enabled -f dependabot_alerts=enabled \
  -f dependabot_security_updates=enabled -f enforcement=enforced \
  -f advanced_security=disabled -f secret_scanning=not_set -f code_scanning_default_setup=not_set

# Attach to the chosen repositories, then make it the default for new ones
gh api -X POST orgs/{org}/code-security/configurations/{id}/attach \
  -f scope=selected -F 'selected_repository_ids[]=<id>' ...
gh api -X PUT orgs/{org}/code-security/configurations/{id}/defaults -f default_for_new_repos=all
```

Set `advanced_security=disabled` explicitly: the built-in "GitHub recommended" configuration turns on features that are paid on private repositories. The new-repo default can't exclude repositories by name, so a new demo repository gets it too.

On repositories untouched for a long time, security updates open a burst of PRs at once. To size it first, attach with `dependabot_security_updates=not_set`, read the alert counts, then turn security updates on.

Repository IDs come from `gh api repos/{org}/{r} -q .id`. Use `scope=all` only when there are no exclusions. Attaching replaces any configuration a repository already has; list those first.

## 6. Org-wide alert notifications (optional)

Repository alerts only notify people who watch the repository. For one channel that sees every new high or critical alert, offer a daily workflow in a central repository:

- Reads `orgs/{org}/dependabot/alerts?state=open&severity=high,critical` with a GitHub App token (`vulnerability-alerts: read`, `contents: read`). A personal token works but ties the job to one person.
- Skips excluded and archived repositories.
- Posts only alerts not yet sent, and records an alert as sent only after Slack accepts the message. Commit that record back to the central repository so the next run reads it.

Build this only when the user names the central repository and the webhook secret. Don't create repositories or secrets on their behalf.

## 7. Per-repository rollout

The org configuration turns alerts on; it does not write `dependabot.yml` or audit workflows. From the coverage report, list repositories missing either and ask which to do. For each one picked, run project mode in a clone of that repository on a feature branch, and open one PR per repository only when the user asks. Do a few first and check their first Dependabot run (`first-run.md`) before doing the rest: a mistake in the policy is cheaper to fix in three repositories than in fifty.

## 8. Report

Before and after totals from step 2, what was changed and where, exclusions, repositories proposed for archiving, and open PRs from step 7.
