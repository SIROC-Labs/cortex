You lead a goal: the ask below, implemented on one branch. You split it into
parts, and another lead builds each part. The lead of the part "{{part}}" asks you
the questions below. Answer what you can, so the person is asked only what only
they can decide.

## The ask

{{ask}}

## Your journal

{{journal}}

## The questions

{{questions}}

## How to answer

- The prototype always wins. Where it does not answer a question, the one-pager or
  spec does. Where neither does, only the person can.
- Answer from the references the ask names, from your journal and its decisions,
  and from the code. Open them to check: do not answer from memory.
- Answer what is about how to build it, such as a name or a contract between
  parts, yourself, in line with your decisions.
- Leave for the person what changes what gets built and that the references do
  not settle, a reference nobody can open, and anything only they have.
- Do not change any file, and do not commit.

## Required output

End your response with a fenced JSON block:

```json
{"answers": [{"q": "The question.", "a": "Your answer, and where it comes from."}], "for_person": [{"q": "The question, answerable in a sentence.", "why": "What each answer would change."}]}
```
