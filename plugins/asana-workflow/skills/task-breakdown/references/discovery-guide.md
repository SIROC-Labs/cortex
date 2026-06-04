# Discovery Guide

Before proposing any breakdown structure, build a complete picture of what exists, what needs to be built, and across which platforms. This checklist ensures nothing gets missed.

## Questioning Strategy

Don't interrogate the user with a rigid 5-question sequence. Instead:

- **Batch related questions** — if you know the project involves frontend and backend, ask about both in one message.
- **Skip the obvious** — if the spec is clearly a CLI tool, don't ask about mobile or Figma.
- **Infer from context** — if the user dropped a repo URL, explore it (CLAUDE.md, file structure, git log) before asking what's already built.
- **One round of questions at a time** — ask what you need, wait for the answer, then ask follow-ups based on what you learned.

The constraint is: **never propose a breakdown until you have enough context to make informed decomposition decisions.** What "enough" looks like varies by project.

## Discovery Checklist

### 1. Specification Sources

Where is the spec? Collect every source:

- Markdown files in the repo (check `docs/`, `specs/`, project root)
- Asana task or project URLs — read the full description, subtasks, and comments
- PDFs, Google Docs, or other documents
- Figma links (for design specs)
- Verbal description from the user

**Read all of them.** Extract requirements, constraints, acceptance criteria. Note any conflicts between sources.

**Collect every URL and file path** — these must appear in the output's References section. The downstream skill depends on them for full context.

### 2. Existing Project State

Is this greenfield or work on an existing project?

**If existing:**
- Read CLAUDE.md files for project conventions and architecture
- Check what's already implemented: `git log --oneline -20`, file structure exploration
- Check for existing milestones — in Asana (sections in a project board) or in docs (previous task-breakdowns)
- Understand what's built vs. what's new vs. what needs to change
- New tasks may slot into existing milestones rather than creating new ones

**If greenfield:**
- Is there a repo already, or does it need scaffolding?
- What's the tech stack?
- Are there boilerplate/template decisions to make?

### 3. Platform Inventory

Which platforms are involved? For each, understand the current state:

**Backend:**
- Does the API exist? What framework?
- Are there endpoints already? What's the data model state?
- Database: what's set up, what needs migration?

**Frontend:**
- Is there a web app? What framework (React, Next.js, Vue, etc.)?
- What pages/routes exist vs. what needs to be built?
- Component library or design system in use?

**Mobile:**
- iOS? Android? Both? React Native / Flutter / native?
- What's the current state of the app?

**Design:**
- Is there a Figma file? Can you see it?
- Is there a design system or component library?
- Do designs need to be created before implementation can start?
- If designs don't exist: is the project design-heavy (lots of new UI) or design-light (mostly backend/logic)?

### 4. Design Dependency Assessment

This is critical for decomposition decisions:

- **Designs exist and are complete** — implementation tasks can reference specific screens/components
- **Designs exist but are incomplete** — identify what's missing, design tasks go first for those areas
- **No designs, project is design-heavy** — consider a design-first milestone, or parallelizing design + backend while deferring frontend
- **No designs, project is design-light** — standard backend-first ordering, rough wireframes may suffice

### 5. External Dependencies

- Third-party APIs that need integration (payment providers, auth services, etc.)
- Infrastructure that needs setup (databases, queues, caches, CDN)
- Services that need accounts or API keys
- Other teams or systems that need to deliver something first

### 6. Team Context

- Solo developer, small team, or cross-functional?
- Are different people handling different platforms?
- Any constraints on who can do what?

This affects task granularity: a solo dev might want larger tasks to reduce overhead, while a team benefits from smaller, parallelizable tasks.

## Effort Assessment Signals

After discovery, the skill proposes one of three sub-modes (Phase 2 of PLAN mode). The proposal is a judgment call informed by discovery — there is no hard cutoff. Use these signals:

**Slot into existing milestone(s)** — choose when:
- The project has existing milestones (Asana sections with milestone tasks) and the new work plainly belongs in one.
- Work spans only 1–3 small tasks all addressing the same product area as an existing milestone.
- No new milestone-level acceptance criteria emerge; the new tasks slot under an existing milestone's existing acceptance set.

**Direct task breakdown (one new milestone)** — choose when:
- The work is a coherent, small product increment (likely 3–6 tasks).
- One milestone fully captures what gets shipped. No natural seam splits it further.
- No part of the work is so large or uncertain that deferring task expansion would be valuable.

**Milestone-first reasoning** — choose when:
- The work spans clearly distinct product increments — e.g., "auth + user management + dashboards" — that ship independently.
- 2+ milestones are likely, and reasoning about their boundaries before naming tasks would change the decomposition.
- Some milestones are well-understood while others are uncertain — the user benefits from authoring milestones now and expanding individual ones later, possibly in separate sessions.
- The breakdown will produce 10+ tasks total across milestones.

Present the proposed mode with a one-sentence rationale and ask the user to confirm or override. The user always has the final say.
