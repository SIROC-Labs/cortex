# Unattended answers

Plugin-wide reference for skills invoked with `unattended: true`. Nobody is present to answer a prompt, so every blocking gate in this plugin resolves from the table below. A gate the table does not cover is returned to the invoker as a stop with the question written out; it is never asked.

The invoker is whatever workflow passed `unattended: true`. This file does not name it.

| Gate | Answer |
|---|---|
| Worktree or current directory | worktree |
| Base branch | the branch the card names; none named → `main`; a named branch absent on `origin` → stop (`clarification`) |
| Task assigned to someone else | reassign to the current user, silently |
| Existing branch or PR for the task | reuse it; never open a second PR for one card |
| Sprint-readiness fields (Product Status, Estimate, Sizing) | not applicable; never set or demanded |
| `implement-feature` entry when no plan is present | `workflow_choice` default `feature-dev` where the runtime binds it, else `EXECUTE_INLINE` |
| `implement-feature` entry when a plan is present | `EXECUTE_PLAN` with the first binding listed in the bindings cell |
| A bound skill asks a design or scope question | answer from the card; unanswerable from the card → stop (`clarification`) with the question and a proposed default |
| Run QA verification (non-bug) | yes |
| `QA: Investigate Bug` cannot reproduce | stop (`clarification`) quoting what was tried |
| QA or the test ladder found gaps; close which | all, in this run; never list them for someone to pick |
| Start containers to test against | yes, the repo's own, under an isolated compose project name, torn down on every exit path |
| Run against staging, production or a real third-party account | no; hand it over as a named live check |
| Mock a dependency the repo ships a container for | no |
| A touched file fails a whole-file quality gate on lines this run did not write | fix them in this run |
| Suppress a rule (`noqa`, `eslint-disable`, `--no-verify`, widening an ignore file) | no; fix it or stop (`failed`) naming the file and rule |
| `pre-ship-check` confirm inferred commands | run them as inferred |
| `pre-ship-check` run the slow test suite | yes |
| `pre-ship-check` blocking finding | stop (`failed`); there is no "ship anyway" |
| `pre-ship-check` advisory warnings | proceed; list them in the verification report |
| `create-pr` reviewers | the project `CLAUDE.md` `## PR Defaults`, else none |
| `create-pr` a non-draft PR already exists | update it |
| `ship-it` task status move and ship comment | skipped; the invoker routes the card and writes its comment |
| Merge or enable auto-merge | never |
| Commit and push | yes, on the card's branch only; never to the base branch |

**Verdict vocabulary.** A stop is one of `clarification` (the card lacks an answer; carries numbered questions each with a proposed default and where it comes from) or `failed` (the run cannot proceed; carries the failing command, its last output and what a human must decide or fix). The invoker owns the wording it posts.
