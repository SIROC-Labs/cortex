# Reporting mechanics

How to write the GitHub side of an unattended run. What belongs on the task versus on the PR is the invoking workflow's routing contract; this file is the API detail.

## One review, many inline comments

Batch every line-anchored comment into a single review, so the operator gets one notification and one
readable thread list instead of N:

```bash
gh api --method POST "repos/<org>/<repo>/pulls/<n>/reviews" \
  --input - <<'EOF'
{
  "commit_id": "<head sha>",
  "event": "COMMENT",
  "body": "Notes on the parts worth a second look.",
  "comments": [
    { "path": "apps/web/src/components/x/Totals.tsx", "line": 42, "side": "RIGHT",
      "body": "Rounds before summing, matching `matrix.ts` — summing first drifts by up to 1pp against the table above." },
    { "path": "packages/core/keywords/mapper.ts", "start_line": 88, "line": 94, "side": "RIGHT",
      "body": "The backend sends this as a ratio; converted here so every surface reads the same number." }
  ]
}
EOF
```

Constraints that bite:

- **`event` must be `COMMENT`.** The PR is authored under the operator's own account, and GitHub
  rejects `APPROVE` and `REQUEST_CHANGES` on your own pull request with a 422.
- **`line` must be a line in the diff**, numbered in the file as of `commit_id`, with `side: "RIGHT"`
  for added or context lines and `"LEFT"` for removed ones. A line outside the diff is a 422 that
  fails the whole review — no comment lands.
- **`commit_id` is the head SHA you just pushed** (`git -C "$WT" rev-parse HEAD`). Anchor to an older
  commit and the comment attaches to stale line numbers.
- Multi-line spans use `start_line` + `line`; both must be in the diff.
- To comment on a file rather than a line — a whole new file, or a point about the file's shape — use
  the single-comment endpoint with `subject_type: "file"` and no `line`:

  ```bash
  gh api --method POST "repos/<org>/<repo>/pulls/<n>/comments" \
    -f path="<file>" -f commit_id="<sha>" -f subject_type=file -f body="<...>"
  ```

- If a review call 422s, do not drop the content: fall back to one `gh pr comment` carrying the same
  notes with `file:line` references in the text. Losing the note is worse than losing the anchor.

A note about a file **outside the diff** — most often a defect you found and deliberately left — cannot
be anchored at all: both the line and the `subject_type: "file"` forms 422 on a path GitHub does not see
in this PR. It goes in the **review's top-level `body`**, with the `file:line` written out. Pick that one
place and use it: the same note split between the PR body, a loose PR comment and the review reads as
three findings, and the reviewer has to work out that it is one.

## Replying to the reviewer's review threads (rework mode)

Read the threads first, including their `id` and the line they sit on:

```bash
gh api "repos/<org>/<repo>/pulls/<n>/comments" \
  --jq '.[] | {id, path, line, user: .user.login, body: .body[0:200]}'
```

Reply **in the thread**, so the answer sits next to the code they asked about:

```bash
gh api --method POST "repos/<org>/<repo>/pulls/<n>/comments/<comment-id>/replies" \
  -f body="Done in <sha> — <what changed, one line>."
```

Every thread you addressed gets a reply naming the commit. A thread you did not address gets a reply
saying so and why — silence reads as "handled".

Never resolve a thread you did not actually act on. Resolving requires the GraphQL
`resolveReviewThread` mutation; leaving threads open for the reviewer to resolve is fine and is the
safer default.

## The PR body

Rewritten on every push so it always describes what the branch currently contains:

```markdown
## Task
<task url>

## What changed
- <one bullet per change, in the order a reviewer would read the diff>

## Why
<the mechanism, 1-3 lines — the constraint that forced this shape, not a restatement of the task>

## Decisions taken
- <call made> — <the alternative rejected and why>
```

`gh pr edit <url> --body-file -` takes it on stdin, which avoids a temp file.

## The verification report

One PR comment, posted after the last push so it describes the shipped state:

```markdown
## Verification

| Rung | Result |
|---|---|
| Quality gate (whole-file, touched set) | `<declared command>` → 7 files clean, MANIFEST OK |
| Static (typecheck, lint) | `<declared command>` → clean |
| Unit | `<declared command>` → 41 passed |
| Integration (containers) | `<declared command>` → 12 passed, real Postgres + Redis |
| In-process API | `<declared command>` → 6 passed |
| Element harness | 4 states rendered at 3 breakpoints, console clean |
| Whole-app local | n/a — flow needs the staging search index |
| Live | not run — the operator's, see below |

**What was actually exercised**
<the behaviour driven and what was observed — the numbers, the states, the assertions>

**Gaps found and closed**
<each gap → what was written to close it, or "none found">

**Left for you (live)**
<one line per live check, with the command>

**Harness**
<the .qa/ files, fenced, plus the command that serves them>
```

A rung marked `n/a` states the fact about the change that puts it out of reach. "No time" and "seemed
unnecessary" are not facts about the change.
