---
name: git-check
version: 0.1.0
description: >
  This skill should be used when the user says "check git status", "is my branch clean",
  "git check", "any uncommitted changes", "check before commit", or when another skill needs
  to validate git state before proceeding. Validates branch, conflicts, uncommitted changes,
  untracked files, debug artifacts, and push status. Used by pre-ship-check and create-pr
  as a foundational git state validation step.
---

# Git Check

Validate the current git state: branch safety, working tree cleanliness, and diff quality. This skill is the single source of truth for git state validation — other skills delegate here instead of reimplementing git checks.

## Checks and Severity

### BLOCKING (must fix before proceeding)

Stop and report if any blocking issue is found. The user can override with explicit confirmation, but warn clearly.

| # | Check | How to detect |
|---|---|---|
| 1 | On main/master branch | `git branch --show-current` returns `main` or `master` |
| 2 | Merge conflicts | `git diff` contains `<<<<<<<`, `=======`, `>>>>>>>` markers |
| 3 | Uncommitted changes | `git status` shows staged or unstaged modifications |

### ADVISORY (warn but don't block)

Flag these and ask "Continue anyway?" after listing all of them.

| # | Check | How to detect |
|---|---|---|
| 4 | Untracked source files | `git status` shows untracked `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.py`, `.rb`, `.rs`, `.java`, `.kt`, `.swift` files |
| 5 | Debug artifacts in diff | Scan added lines (`+`) in `git diff` for language-specific debug statements (see below) |
| 6 | TODO/FIXME/HACK in diff | Scan added lines (`+`) in `git diff` for `TODO`, `FIXME`, `HACK` |
| 7 | Branch not pushed to remote | `git rev-parse @{u}` fails or `git status` shows "ahead of" |

## Execution Order

Run checks in this order to fail fast on cheap checks:

1. Branch check (on main/master?)
2. Merge conflict check
3. Uncommitted changes check
4. Untracked source files check
5. Debug artifact scan on diff
6. TODO/FIXME/HACK scan on diff
7. Branch pushed to remote check

Stop at the first blocking finding and report all findings discovered so far. Advisory warnings accumulate and are reported together at the end.

## Debug Artifact Detection

Scan only **added lines** in `git diff` (lines starting with `+`). Match by file extension:

| Language | File extensions | Patterns to flag |
|---|---|---|
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` | `console.log`, `debugger` |
| Python | `.py` | `print(`, `breakpoint()`, `pdb.set_trace()` |
| Go | `.go` (non-test files only) | `fmt.Println`, `fmt.Printf` |
| Ruby | `.rb` | `puts`, `binding.pry` |

Do not flag debug statements in test files (files matching `*_test.go`, `*.test.ts`, `*.spec.ts`, etc.) — those are expected.

## Output Format

Present findings in three sections:

```
BLOCKING
  - Uncommitted changes: 3 modified files (src/foo.ts, src/bar.ts, lib/baz.ts)

WARNINGS
  - Debug artifact: console.log found in src/utils/helper.ts (line 42)
  - TODO found in src/api/handler.ts: "TODO: handle edge case"
  - Branch not pushed to remote

PASSED
  - On feature branch (feat/my-feature)
  - No merge conflicts
```

Omit any section that has no findings. If everything passes:

```
PASSED
  - All git checks passed.
```

## Behavior Rules

1. **Blocking findings** — Stop and report. The user can override with explicit confirmation ("yes, continue anyway"), but make the risk clear. Do not silently proceed.

2. **Advisory warnings only** — List them and ask: "These are non-blocking warnings. Continue anyway?"

3. **All checks pass** — Say so and proceed. No unnecessary friction.

4. **Uncommitted changes** — Delegate to the `commit-commands:commit` skill rather than implementing commit logic inline. Say: "You have uncommitted changes. Want me to help commit them?"

5. **Error handling** — Never silently skip a check. If a git command fails unexpectedly, report the failure explicitly and note that the check could not be completed.
