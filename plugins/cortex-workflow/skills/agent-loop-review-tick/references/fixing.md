# Fixing

The review tick fixes what a reviewer would fix in place and hands back what needs the builder. The line is **complexity, judged by the reviewer**, not size: a simple and clear change lands here however many files it touches; a complex one goes back to the queue.

## Fix here or hand back

A fix is **simple and clear** when the reviewer can state, before editing, exactly what changes and why it is correct, and the proof in "How a fix is proved" is available. Repetition does not make it complex: the same one-line correction in twenty files, a rename across the module, a helper extracted from three copies, are all fixes here.

| Fix here | Hand back |
|---|---|
| A simplify or refactor finding whose fix changes no test assertion, at any file count | A Definition of done line not met: **missing functionality** is the builder's |
| A correctness or security defect whose mechanism the reviewer can name and whose fix follows from it | A defect whose mechanism is not clear after tracing, or whose fix needs a design the card does not describe |
| A suppression removable by fixing the cause in place; a decision the card leaves open, taken the way the repo's nearest convention takes it and recorded in the review | A fix with no clear answer: two behaviours would both satisfy the card and nothing in the card, the code or the conventions favours one |
| A red CI check with a clear cause (a missing import, a stale snapshot, a fixture the change invalidated) | CI red whose cause is not clear after reading the log and the code |
| A rebase conflict with a clear resolution (`merging.md` → "Conflicts") | A fix that changes a Contract item, a wire name, an enum value or a user-visible number: the card's contract is the author's; a conflict whose sides want different behaviour |

Any hand-back finding hands the whole card back. Fixable findings are still fixed and pushed first, so the rework starts from the better tree; the hand-back comment says which findings were fixed and which remain, and why each remaining one is complex.

A security or data-loss defect that predates the card is fixed here when it fits the fix-here column; any other pre-existing defect is reported in the PR review and left.

## How a fix is proved

- **Behavioural defect**: write the regression test, run it, **confirm it fails for the intended reason** and keep the red output; make the smallest structural fix; run to green. A test green on first run tested nothing.
- **Refactor or simplify**: the affected fast suite green before the first edit and after the last, no test assertion changed. A refactor that needs an assertion changed altered behaviour: revert it.
- **Non-runnable defect** (dead import, wrong log field, stale comment): the gate or linter that catches it stands in for the red run; name it. Nothing catches it → cite the standard and label the fix **unverified** in the report.
- **Suppression**: the underlying rule passes on the file after the marker is gone.

Whole-file quality debt the repo's gate raises on a file the fix touches is cleared in the same fix. Never widen an ignore, lower a threshold or add a marker to get a gate green.

## Commits

One commit per pass that changed code, with the prefix the branch uses: `fix(<scope>): …` for correctness and security, `refactor(<scope>): …` for simplify, `test(<scope>): …` when only tests changed. Stage explicit paths from `git status --short`, including new files; confirm each shows `A` or `M`. Any trailer the repository's standards require goes in at commit time.

## The per-fix verdict

After the last fix commit, one fresh validator (not a reviewer from the passes) reads `git -C <wt> diff <synced head>..HEAD` and the claim each fix makes. Per fix: **SOUND**, or the specific thing the fix gave up: a type guarantee, a test's coverage, a line now dead, a behaviour the card wanted. A non-SOUND fix is reverted (`git revert` of its commit, or the hunk dropped before the push) and its finding moves to the hand-back list with the verdict quoted.
