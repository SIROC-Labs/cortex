# Repository settings

| Setting | Read | Enable | Notes |
|---|---|---|---|
| Dependency graph | `gh api repos/{o}/{r}/dependency-graph/sbom -i` (200 on; an error means off or no access) | Settings → Code security | On by default for public repos. Alerts need it. |
| Dependabot alerts | `gh api repos/{o}/{r}/vulnerability-alerts -i` (204 on, 404 off) | `gh api -X PUT repos/{o}/{r}/vulnerability-alerts` | Admin rights. |
| Security updates | `gh api repos/{o}/{r}/automated-security-fixes` | `gh api -X PUT repos/{o}/{r}/automated-security-fixes` | Needs alerts on first. Turn on after `dependabot.yml` reaches the default branch: before that, each advisory opens its own ungrouped PR. |
| Secret scanning, push protection, Code Security, Advanced Security | `gh api repos/{o}/{r} -q .security_and_analysis`: each feature has `.status` `enabled` or `disabled` | Not via this skill | Private repos need GitHub Advanced Security. |
| Code scanning | `gh api repos/{o}/{r}/code-scanning/default-setup -q .state` (`configured` or `not-configured`). A 403 saying Code Security must be enabled means off. | Not via this skill | Only meaningful when Code Security is enabled. |
| Private vulnerability reporting | `gh api repos/{o}/{r}/private-vulnerability-reporting -q .enabled`: `false` is off. GitHub offers it for public repositories, so a 404 on a private repository is off; a 404 on a public repository is unknown (it can also mean no access). | Not via this skill | |

Report each of these as on, off or unknown. The responses named above are known states. Any other error, or a missing field, is unknown, never off.

Without admin rights the PUT calls return 403 or 404. Give the user the commands to pass to an admin instead of failing silently.

If the repository belongs to an org that attaches a security configuration, the configuration wins: an enforced setting can't be changed per repository. Check with `gh api repos/{o}/{r}/code-security-configuration`.

## Self-hosted runners for Dependabot

If the org enabled "Dependabot on self-hosted runners", Dependabot jobs queue until a runner labelled `dependabot` exists. If the first run never starts, check this setting before anything else.
