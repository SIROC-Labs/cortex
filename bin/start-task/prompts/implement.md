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

## Required output

End your response with a fenced JSON block, exactly this shape:

```json
{
  "summary": "What changed and why, in 1-3 sentences. Used verbatim as the PR description.",
  "files_changed": ["path/one.ts", "path/two.ts"],
  "notes": "Anything the reviewer must know: assumptions, gaps, follow-ups. Empty string if none."
}
```
