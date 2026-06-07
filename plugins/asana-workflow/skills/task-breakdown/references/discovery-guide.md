# Discovery Guide

Before proposing any task structure, build a complete picture of what exists, what needs to be built, and across which platforms. This guide covers the input sources, the repo walk, the off-limits-paths rule, the seam-check heuristic, and the questioning strategy.

## Source Detection

Inspect each argument (or the current working directory if no argument was given) and ingest accordingly:

| Source type | How to detect | How to ingest |
|---|---|---|
| Asana task or project | `app.asana.com` in URL | Use the `asana-api` skill to fetch the task / project, all subtasks, comments, and attachments |
| Jira issue | `atlassian.net/browse/` or `atlassian.net/jira/` in URL | Use Atlassian MCP to fetch the issue and linked items |
| Linear issue | `linear.app/` in URL | Use Linear MCP to fetch the issue |
| GitHub issue or PR | `github.com/.../issues/` or `/pull/` in URL | Use `gh issue view` / `gh pr view` |
| Notion page | `notion.so` or `notion.site` in URL | Use Notion MCP |
| Confluence page | `atlassian.net/wiki/` in URL | Use Atlassian MCP |
| Google Drive doc | `drive.google.com` or `docs.google.com` in URL | Use Google Drive MCP |
| Figma file or frame | `figma.com` in URL | Use Figma MCP (`get_design_context`, `get_metadata`, `get_screenshot`) |
| Loom video | `loom.com` in URL | WebFetch the page and extract transcript / summary. If nothing usable, ask the user to paste the transcript |
| Other URL | `http://` or `https://` | WebFetch |
| Local file path | path resolves to a regular file | Read directly (PDF, Markdown, HTML, code) |
| Local folder path | path resolves to a directory | Walk the directory and read all relevant files |
| Free-text seed | non-empty text not matching any rule above | Treat as a problem-statement seed. Ask the user whether to also inspect the current working directory |
| No argument given | — | Inspect the current working directory and read what looks relevant |

When multiple inputs are given (e.g., spec path + Figma URL + Asana milestone URL), ingest all of them before continuing.

## Repository Walk

Read `CLAUDE.md` / `AGENTS.md` at repo root and in all affected directories. Read source for plausibly-touched modules so you understand the current architecture in the areas the work will change. Start at repo root, then check each directory the work is likely to touch. Architecture decision records (ADRs) or similar dated, current-state decision logs are reliable to read if the repo has them.

## Off-Limits Paths

Do not read prior specs, prior PRDs, prior task breakdowns, prior milestone breakdowns, or other planning documents found anywhere under `docs/*/specs/`, `docs/*/product-requirements/`, `docs/*/task-breakdowns/`, `docs/*/milestone-breakdown/`, `specs/`, `prds/`, or sibling planning directories. Prior planning documents are frequently stale, superseded, or aspirational. Reading them risks importing outdated assumptions or dropped scope into the new breakdown without you being able to tell which is which. Source code reflects current reality; old planning docs do not.

The one exception is the explicit input provided by the user for this run (a spec path passed as an argument, an Asana milestone task description, etc.). That is the input — not a "prior planning doc" — and must be read in full.

## Seam Check

After ingesting input and the repo walk, run the seam-check heuristic before proposing tasks. The skill subdivides **one coherent scope** into tasks. If the scope is genuinely multi-milestone, redirect the user to `milestone-breakdown` instead.

Run through each signal as a concrete checklist:

- [ ] **Multiple independent feature surfaces.** The scope spans 2+ unrelated user flows (e.g., "billing + chat + analytics" — three independent product surfaces).
- [ ] **Heavy multi-platform scope.** Each platform's slice is independently meaningful (a full backend + iOS + Android effort with non-trivial work on each, not a small cross-platform tweak).
- [ ] **Named phases or sub-projects.** The input describes "Phase 1 / Phase 2", "Track A / Track B", explicit sub-projects, or a sequenced rollout.
- [ ] **User language references "milestones / phases / tracks / roadmap".** The user spontaneously used multi-milestone vocabulary when describing the scope.

If **zero** signals fire → proceed with task-breakdown. If **one or more** signals fire → surface what you detected and offer the switch:

> "What you described looks like a multi-milestone effort (signals: …). `milestone-breakdown` is the right entry point for that — it produces milestone blocks and per-milestone specs that I can then expand into tasks one milestone at a time. Want to switch, or proceed here anyway?"

The user always has final say. If the user chooses to proceed, do so without re-litigating — but record their explicit confirmation so later phases know the scope was reviewed.

## Questioning Strategy

Don't interrogate the user with a rigid question sequence. Instead:

- **Batch related questions** — e.g., if scope edges, naming, and pattern selection for the same task area are all open, ask about them in one message rather than three sequential questions.
- **Skip the obvious** — if the input is clearly a CLI tool, don't ask about Figma or mobile.
- **Infer from context** — if the user dropped a repo URL, explore it (`CLAUDE.md`, file structure, current source) before asking what's already built.
- **One round of questions at a time** — ask what you need, wait for the answer, then ask follow-ups based on what you learned.

The structured back-and-forth lives in Phase 2 (`superpowers:brainstorming`). Phase 1's questioning is only about filling gaps in source-detection and codebase context — enough to enter the interview prepared, not enough to skip it.

Never propose a task list until you have enough context to make informed decomposition decisions. What "enough" looks like varies by project.

## Discovery Checklist

Use this as a memory aid for what to collect in Phase 1.

### 1. Input Sources

Every source named by the user (Asana URL, spec path, Figma link, free text). Read all of them. Note any conflicts. Source code + convention files only — no prior breakdowns / PRDs / planning docs.

### 2. Existing Project State

- `CLAUDE.md` / `AGENTS.md` at every relevant level
- Current source in directories the work will touch
- For existing Asana projects: which milestone (if any) is the natural parent — captured as a candidate `**Target milestone:**`

### 3. Platform Inventory

For each platform involved (Backend / Frontend / iOS / Android / Design): what exists now, what's about to change, what tooling and conventions are in play.

### 4. Design Dependency Assessment

- Designs exist and are complete → tasks can reference specific screens
- Designs exist but are incomplete → identify what's missing
- No designs → confirm with the user whether design tasks belong in this bundle or in a separate scope

### 5. External Dependencies

Third-party APIs, infrastructure setup, accounts / keys, other teams. Surface these — they shape ordering and may signal that the scope is bigger than one task-breakdown.

### 6. Team Context

Solo developer, small team, or cross-functional. Affects task granularity.
