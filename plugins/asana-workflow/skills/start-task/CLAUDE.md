# `start-task` — Development Notes

## Keep FLOW.md in sync with SKILL.md

`FLOW.md` is the canonical human-readable ASCII flow diagram of this skill's lifecycle. It is **not** loaded by the model at runtime (not referenced from SKILL.md, no frontmatter linkage), but it is the visual reference linked from the repo `README.md` for contributors trying to understand the skill.

**When modifying the skill's flow structure, update `FLOW.md` in the same commit.** Sync with `FLOW.md` whenever any of these change:

- Adding, removing, or renumbering a step (e.g., splitting Step 9 into 9a + 9b)
- A step's name, trigger phrasing, or blocking behavior
- A decision point (new routing branches in Step 10, new QA sub-cases)
- The Pause Flow or Resume Flow sequence
- Checkpoint column semantics (`Completed` / `State` vocabulary)
- Checkpoint file location or helper-script path

If `FLOW.md` drifts from `SKILL.md`, the model's runtime behavior is unaffected (it reads `SKILL.md`), but the documentation the `README.md` points at becomes misleading. A PR that changes the flow without updating `FLOW.md` should not land.
