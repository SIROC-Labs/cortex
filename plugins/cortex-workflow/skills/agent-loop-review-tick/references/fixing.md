# Fixing

The review tick fixes what a reviewer would fix in place and hands back what needs the builder. The line is the table, not the reviewer's appetite.

## Fix here or hand back

| Fix here | Hand back |
|---|---|
| A simplify or refactor finding whose fix changes no test assertion | A Definition of done line not met: **missing functionality** is the builder's |
| A correctness or security defect with one mechanism, fixed inside the card's Scope boundary | A fix that changes a Contract item, a wire name, an enum value, a payload key or a user-visible number |
| A suppression removable by fixing the cause in place | A fix that needs a decision the card does not answer |
| A red CI check the budget below covers | A rebase conflict; CI red beyond the budget |
| **Budget across all fixes: 150 changed lines, 8 files.** | The fix that would cross the budget, and every fix after it |

Any hand-back finding hands the whole card back. Fixable findings are still fixed and pushed first, so the rework starts from the better tree; the hand-back comment says which findings were fixed and which remain.

A security or data-loss defect that predates the card is fixed here when it fits the fix-here column; any other pre-existing defect is reported in the PR review and left.

## How a fix is proved

- **Behavioural defect**: write the regression test, run it, **confirm it fails for the intended reason** and keep the red output; make the smallest structural fix; run to green. A test green on first run tested nothing.
- **Refactor or simplify**: the affected fast suite green before the first edit and after the last, no test assertion changed. A refactor that needs an assertion changed altered behaviour: revert it.
- **Non-runnable defect** (dead import, wrong log field, stale comment): the gate or linter that catches it stands in for the red run; name it. Nothing catches it → cite the standard and label the fix **unverified** in the report.
- **Suppression**: the underlying rule passes on the file after the marker is gone.

Whole-file quality debt the repo's gate raises on a file the fix touches is cleared in the same fix and counts toward the budget. Never widen an ignore, lower a threshold or add a marker to get a gate green.

## Commits

One commit per pass that changed code, with the prefix the branch uses: `fix(<scope>): …` for correctness and security, `refactor(<scope>): …` for simplify, `test(<scope>): …` when only tests changed. Stage explicit paths from `git status --short`, including new files; confirm each shows `A` or `M`. Any trailer the repository's standards require goes in at commit time.

## The per-fix verdict

After the last fix commit, one fresh validator (not a reviewer from the passes) reads `git -C <wt> diff <synced head>..HEAD` and the claim each fix makes. Per fix: **SOUND**, or the specific thing the fix gave up: a type guarantee, a test's coverage, a line now dead, a behaviour the card wanted. A non-SOUND fix is reverted (`git revert` of its commit, or the hunk dropped before the push) and its finding moves to the hand-back list with the verdict quoted.
