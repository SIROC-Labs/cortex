Rewrite a goal's journal so it is small. A lead agent reads the whole journal at the
start of every session, so every line costs on every round.

Read `{{source}}`, and write the new journal to `{{target}}`. Change no other file.

Keep, in this order:

1. `## Status`: at most ten lines. Where the work is now, and what is next.
2. Every section that holds the person's answers, word for word, with its heading.
3. `## References`: each reference in one line: what it is, where, what it decides.
4. `## Acceptance criteria`: word for word. Every line, every tick, every `###` heading.
5. `## Plan`: word for word. Every line and every tick.
6. `## Decisions`: one line each: the decision and its reason. Drop a decision that
   a later one replaces.

Drop everything else: build logs, batch and round notes, designs (the technical plan
holds them), an explorer's findings, review notes that were dealt with. Where a
dropped section holds something a later step still needs, keep it as one line under
`## Decisions`.

End with:

```json
{"status": "done"}
```
