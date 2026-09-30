# Reviewing

Each pass is one reviewer agent. Its prompt gives the repository path, the range `origin/<base>...HEAD`, the PR number, the full card, and the brief below verbatim; never the diff itself. All three run at once; none edits anything.

## Shared frame

> You are reviewing one change end to end for **one concern only**. Report findings only; make no edits. The project's `CLAUDE.md` is already in your context. Read the diff in file batches (`git diff <range> -- <paths>`), source first, tests last; use `git grep` for callers and "does this exist elsewhere" questions rather than reading whole modules. Skip lockfiles, generated code and snapshots unless they are the point of the change. **Verify before reporting:** re-open each cited `file:line` in the current tree and confirm the line says what you claim, the diff direction is right, nothing upstream or downstream already handles it, and a "removed" thing was not merely moved. Drop what fails; merge findings sharing a root cause. Return one line per finding, `- [<Concern>] **<title>** — \`file:line\` — <consequence>`, then a "Checked and clean" list naming what you verified. Describe findings; suggest no fixes.

## Completeness

The card is the contract; the PR body's claims are hypotheses.

- *Definition of done*: for every line, name the code and the test that deliver it. A line with no test asserting the outcome is a finding. A line with no code is a finding of kind **missing functionality**.
- *Verification row*: the non-live proof the card names exists, runs, and asserts the stated outcome rather than the absence of an exception. Fixtures or seed data the card names are present.
- *Scope boundary*: every touched file is inside the card's boundary, or is whole-file quality debt the repo's gate raised on an in-scope file. Anything else is a finding.
- *Contract*: every name, value, threshold and error behaviour the card states appears in code exactly as stated.
- *Preservation*: no existing field, filter, join, handler, retry, log line, middleware or auth check removed unless the card asks for it; a removed thing not merely moved.
- *PR body claims*: every "Decisions taken" bullet and every explanatory PR comment by the run is checked against code. A claim that fails is a finding quoting the claim.
- *Tests*: new business logic without a test; tests asserting on a mock's arguments where the repo requires an integration test; a test that passes with the change reverted.

## Security

Report only exploitable, high-confidence issues introduced by this diff; skip DoS, rate limiting, missing hardening and theoretical races.

- *Authorization*: a route over user data without a bound current-user dependency, or one that binds it and discards the identity; a user-owned document resolved by id without an owner filter; a 403 that confirms another user's document exists; an identity or ownership value (user id, owner id, shop id) taken from a query param, path or body instead of the authenticated user.
- *Injection*: user input reaching SQL by string formatting instead of bound parameters; document-store filters built from raw user dicts (`$where`, operator injection); shell commands, file paths (traversal) or templates built from input.
- *Secrets and exposure*: hardcoded keys, tokens or DSNs; secrets, tokens or PII in logs, error messages or responses; a domain model reused as a response model leaking internal fields.
- *Auth flows*: token or signature checks skipped or fail-open, OAuth `redirect_uri`/`state` not validated, CORS widened, SSRF through a user-supplied URL, unsafe deserialization.
- *LLM surfaces*: tool or prompt inputs that let one user's content read another user's data, or model output trusted as an authorization decision.

## Simplify

Do not flag style preferences or complexity the card needs.

- *Reuse*: new code duplicating a helper, datasource, query type, DTO or enum that already exists (`git grep` before claiming); a parallel entity differing from an existing one by a couple of fields.
- *Quality*: redundant or derived state stored twice; parameter sprawl where an existing object fits; copy-pasted blocks; stringly-typed closed sets; single-use wrappers; speculative flags or extension points; dead code, unused imports, leftover scaffolding; names inconsistent with the module; comments that restate the code or narrate history.
- *Efficiency*: per-item database calls in a loop where one bulk operation fits; N+1 reads; repeated work computable once; independent sequential awaits; an existence check before a write that races where an upsert fits; unbounded reads on a hot path.
- *Altitude*: logic at the wrong layer, or a fix patched at a call site when the gap is structural.

## The validator

One agent, after all three passes return, given the repository path, the range and the merged finding list. Brief:

> Knock each finding down. For each, re-derive from the code and return **CONFIRMED** with the concrete failing input → output, **PLAUSIBLE** when real but overstated (state the true consequence), or **REFUTED** with the evidence that kills it. Take no reviewer's word. Then add findings the reviewers missed within their three concerns. A finding with no statable failure scenario is an opinion: REFUTED.

Only CONFIRMED and PLAUSIBLE survive. A finding of kind **missing functionality** keeps that kind through validation; it decides the route.

## Suppression scan

Mechanical, over `git diff origin/<base>...HEAD`. Every hit is a CONFIRMED finding with no validator; the fix is to remove the cause, never the marker alone.

| Pattern in added lines | Also |
|---|---|
| `noqa`, `type: ignore`, `pragma: no cover`, `pylint: disable` | |
| `eslint-disable`, `@ts-ignore`, `@ts-expect-error`, `istanbul ignore` | |
| `.skip(`, `.only(`, `xit(`, `xdescribe(`, `@pytest.mark.skip`, `@unittest.skip` | a deleted or renamed test (`git diff --diff-filter=D --stat` on test paths) |
| `--no-verify`, `SKIP=` in hooks, scripts or CI files | a lowered coverage, lint or type threshold in any config |
| a widened ignore or exclude list (`.eslintignore`, `pyproject` `exclude`, `tsconfig` `exclude`, `.gitignore` for source paths) | a new `allow_failure` / `continue-on-error` in CI |

A pre-existing marker on a line the diff did not add is not this scan's finding.
