# Implementation Plan Template

The attached `implementation-plan.md` is a standalone markdown document a separate Claude session (running `start-task`) can read to execute the task with minimal user interaction. It owns the **how** — file paths, patterns to follow, step-by-step implementation, edge cases.

The Asana task description still owns the **what** and **why** — Purpose, Scope, Acceptance Criteria, References. The plan complements it; do not duplicate the description verbatim.

## Structure

Use standard markdown (not Asana HTML — this is a file, not a notes field). Sections in this order:

### Title

```markdown
# T<n> — <Task title>
```

### Source

A bullet list with the Asana task URL and the task's milestone:

```markdown
- **Asana task:** <url>
- **Milestone:** M<n> :: <name>
```

### Purpose

One sentence from the Asana task description's Purpose. Do not paraphrase — keep the exact wording.

### Scope

Two subsections:

- **New files to create** — exact file paths and what each contains / exports
- **Existing files to modify** — exact file paths and the specific changes to make

Example:

```markdown
## Scope

### New files to create
- `src/core/employees/domain/model.py` — Employee entity, EmployeeCreate/EmployeeUpdate schemas
- `src/core/employees/domain/datasource.py` — EmployeeDatasource abstract class
- `src/core/employees/infrastructure/repository.py` — SQLAlchemy implementation of EmployeeDatasource
- `src/api/routers/employees.py` — CRUD endpoints

### Existing files to modify
- `src/api/main.py` — register the employees router (1-line change)
- `src/core/database/models.py` — add Employee SQLAlchemy model
```

Every path must exist (or be a new file based on a clearly-named convention). If a path doesn't exist, the codebase-discovery phase in `refine-tasks` failed and the plan should not be finalized.

### Patterns to Follow

Real exemplar files the implementer should read for conventions. Each entry: path + what to follow.

```markdown
## Patterns to follow

- `src/core/users/domain/model.py` — entity + schema pattern
- `src/core/users/infrastructure/repository.py` — SQLAlchemy repository pattern
- `src/api/routers/users.py` — CRUD router structure
```

### Step-by-Step Plan

A numbered list of concrete steps. Each step is one action, small enough that a session can execute it and verify before moving on.

```markdown
## Steps

1. Create `src/core/employees/domain/model.py` mirroring `src/core/users/domain/model.py`. Replace User-specific fields with Employee fields (name, role, department, is_active).
2. Create `src/core/employees/domain/datasource.py` with `EmployeeDatasource` abstract class, methods: `list`, `get`, `create`, `update`, `soft_delete`.
3. Create `src/core/employees/infrastructure/repository.py` implementing `EmployeeDatasource` against SQLAlchemy. Follow `src/core/users/infrastructure/repository.py`.
4. Add `Employee` SQLAlchemy model to `src/core/database/models.py`.
5. Create `src/api/routers/employees.py` with five endpoints; follow `src/api/routers/users.py`.
6. Register the router in `src/api/main.py`.
7. Run the test suite and verify the CRUD endpoints respond correctly.
```

Keep steps mechanical and verifiable. If a step requires a design decision, that decision should have been resolved in Phase 3a (ambiguity batch) and embedded in the plan as a stated choice.

### Acceptance Criteria Mapping

Show how each acceptance criterion is verified once the steps are done. This grounds the plan in the task's success conditions.

```markdown
## Acceptance criteria mapping

| Acceptance criterion | How verified |
|---|---|
| GET /employees returns all employees with name, role, department | Hit the endpoint with curl after Step 5; assert response shape |
| POST /employees creates and returns entity with generated ID | curl POST with sample body; assert 201 and returned `id` |
| GET /employees/{id} returns 404 for nonexistent IDs | curl GET with bogus ID; assert 404 and error shape |
| DELETE soft-deletes (sets is_active=false) | DELETE then GET /employees/{id}; assert is_active=false |
```

### Edge Cases

List the non-happy-path scenarios the implementation must handle. Each line states the scenario and the expected behavior.

```markdown
## Edge cases

- POST with missing required field — 422 with field-level error
- PUT for nonexistent ID — 404 with error message
- DELETE on already-soft-deleted task — 404 (treat as if it doesn't exist)
- Concurrent updates — last write wins; no optimistic locking required for this task
```

### References

A flat list of every source consulted to write this plan: spec sections, exemplar files, related Asana tasks, external docs. Helps the executing session verify the plan against current state.

```markdown
## References

- Spec: `docs/spec.md` § Employees
- Pattern: `src/core/users/domain/model.py`
- Pattern: `src/api/routers/users.py`
- Asana milestone: <url>
```

---

## Content Rules

- **Reference, don't replicate.** Point to source files by path. Don't paste full code, schemas, or response shapes into the plan.
- **Be opinionated.** Where conventions exist, pick the one to follow. Don't offer alternatives.
- **State technical facts, not predictions.** Only assert file paths and patterns that are real. Don't predict function signatures of code that doesn't exist.
- **Resolve cross-task decisions once.** If the milestone's earlier tasks established a pattern (form components, error handling, confirmation dialog style), state it as the established choice rather than re-litigating.
- **No implementation code in the plan.** The plan describes what to do, not the literal code. The executing session writes the code.
- **Don't duplicate the Asana description.** The plan complements the description, which already has Purpose/Scope/Acceptance Criteria. The plan's job is the implementation path — files, patterns, steps.

---

## Length expectations

A well-written plan is typically 80–200 lines of markdown. Plans much shorter usually mean the task is too small to be its own task (consider merging); plans much longer usually mean the task is too big (consider splitting and rerunning task-breakdown).
