Review feedback has come in on the pull request for this task. Apply it.

You are on branch `{{branch}}`, in the worktree the task was implemented in. The PR
is {{pr}}; its base is `{{base}}`.

## Task

```json
{{task}}
```

## Feedback

{{feedback}}

## What to do

1. Read the feedback and the code it refers to. Address every point: change the code
   where the reviewer is right, and say why not where they are not.
2. Keep to the scope of the feedback. Do not start adjacent work.
3. Do not commit, push, or comment on the PR — the runner does all of that.
4. If the branch conflicts with its base and the feedback asks you to resolve it,
   merge `{{base}}` into the branch (`git merge {{base}}`) and resolve the conflicts
   keeping both sides' intent. Never rebase and never force-push.

## Required output

End your response with a fenced JSON block, in one of exactly two shapes.

When you addressed the feedback:

```json
{
  "summary": "What changed, in 1-3 sentences.",
  "reply": "The reply to post on the PR: point by point, what you changed and what you did not, and why.",
  "files_changed": ["path/one.ts"]
}
```

When a decision only a human can make is genuinely blocking you:

```json
{
  "questions": [
    {"q": "The question, answerable in a sentence.", "why": "What is ambiguous and what each answer would change."}
  ]
}
```

Never send both blocks.
