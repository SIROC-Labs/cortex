# Repository settings

| Setting | Read | Enable | Notes |
|---|---|---|---|
| Dependency graph | `gh api repos/{o}/{r} -q .security_and_analysis` | Settings → Code security | On by default for public repos. Alerts need it. |
| Dependabot alerts | `gh api repos/{o}/{r}/vulnerability-alerts -i` (204 on, 404 off) | `gh api -X PUT repos/{o}/{r}/vulnerability-alerts` | Admin rights. |
| Security updates | `gh api repos/{o}/{r}/automated-security-fixes` | `gh api -X PUT repos/{o}/{r}/automated-security-fixes` | Needs alerts on first. |
| Secret scanning, code scanning | `gh api repos/{o}/{r} -q .security_and_analysis` | Not via this skill | Private repos need GitHub Advanced Security. Report the state only. |

Without admin rights the PUT calls return 403 or 404. Give the user the commands to pass to an admin instead of failing silently.

If the repository belongs to an org that attaches a security configuration, the configuration wins: an enforced setting can't be changed per repository. Check with `gh api repos/{o}/{r}/code-security-configuration`.

## Self-hosted runners for Dependabot

If the org enabled "Dependabot on self-hosted runners", Dependabot jobs queue until a runner labelled `dependabot` exists. If the first run never starts, check this setting before anything else.
