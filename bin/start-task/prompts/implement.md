Implement the following task in this repository. The branch `{{branch}}` is already
created and checked out, and a draft PR is already open — do not create either.

Everything known about the task is below. It was gathered deterministically before you
were called, so treat it as complete: you should not need to search the task tracker,
and you have no access to it.

## Task

```json
{{context}}
```

## Subtasks

These describe what "done" means. An incomplete subtask is work in scope.

```json
{{subtasks}}
```

## Comments

```json
{{comments}}
```

## Attachments

{{attachments}}

## External links

{{links}}

You cannot open these — no browser or MCP servers are available in this session. If one
of them clearly holds information you needed, say so in your `notes` rather than
guessing at its contents.

## What to do

1. Read the relevant parts of the codebase and follow its existing conventions.
2. Implement the task. Write tests where the project has a test suite.
3. Do not commit, push, or touch the PR — the runner handles all of that.
4. Stop when the task is implemented. Do not start adjacent work.

If the task cannot be implemented as specified — it contradicts the code, depends on
something absent, or is ambiguous in a way that changes the outcome — implement what
you confidently can and put the problem in `notes`. Do not invent requirements.

## How to write the text for the PR

The PR gets two texts from you:

- `summary` is the PR description. Keep it short: what the change does and why, in
  1-3 sentences.
- `walkthrough` is posted as the first comment on the PR. A reviewer reads it to
  review the change, which can be large. Start with where to begin reading. Then
  explain each part of the change — what it does, why, and how the parts connect —
  with one heading or list item for each part. Tell the reviewer what to examine
  carefully: risky changes, behaviour that changes for users, and decisions you made
  where the task did not say. End with what you tested.

Write both, and `notes`, in ASD-STE100 Simplified Technical English:

- Write one topic in each sentence. Keep a sentence to 20 words or fewer when it tells
  the reader to do something, and to 25 words or fewer when it describes something.
- Use the active voice and the simple tenses: "This change adds a retry", not "A retry
  has been added".
- Use common words with one meaning. Do not use idioms, slang, or vague words such as
  "various", "some cleanup" or "tweaks".
- Use the same term for the same thing every time. Put code names, file paths and
  commands in backticks, exactly as they are in the code.
- Do not leave out "the", "a" or "is" to make a sentence shorter.
- Do not put more than three nouns together. Write "the timeout for the push", not
  "the push retry timeout setting".
- Use a vertical list for steps or for more than two items. Keep a paragraph to six
  sentences or fewer.
- Write instructions to the reviewer as commands: "Examine `engine.py` first."

## Required output

End your response with a fenced JSON block, in one of exactly two shapes.

When you implemented the task:

```json
{
  "summary": "What changed and why, in 1-3 sentences. Used verbatim as the PR description.",
  "walkthrough": "The explanation of the change for the reviewer, in Markdown. Posted as a PR comment.",
  "files_changed": ["path/one.ts", "path/two.ts"],
  "notes": "Anything the reviewer must know: assumptions, gaps, follow-ups. Empty string if none."
}
```

When a decision only a human can make is genuinely blocking you — the task is
ambiguous in a way that changes what gets built, and picking wrong means doing the
work twice — stop and ask instead:

```json
{
  "questions": [
    {"q": "The question, answerable in a sentence.", "why": "What is ambiguous and what each answer would change."}
  ]
}
```

Your questions are posted to the task, a human answers there, and you are called
again with their answer and whatever you already changed. Use this sparingly: it
costs a human's attention, and the guidance above still applies — if you can
implement what you confidently can and record the problem in `notes`, do that
instead. Never send both blocks.
