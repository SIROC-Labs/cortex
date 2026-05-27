# Implementation Plan Template

The attached `implementation-plan.md` is a standalone markdown document a separate Claude session (running `start-task` → `feature-dev` / `fix-bug`) reads to execute the task with minimal user interaction. It owns the **how** — files, patterns, concrete steps, code snippets, commands, verifications.

The Asana task description still owns the **what** and **why** — Purpose, Scope, Acceptance Criteria, References. The plan complements it; do not duplicate the description verbatim.

This template is heavily inspired by the `superpowers:writing-plans` skill. Plans are structured for **checkbox-tracked, code-explicit, TDD-where-applicable execution**.

## Plan Header

Every plan starts with:

```markdown
# T<n> — <Task title>

> **For executors:** Steps use checkbox (`- [ ]`) syntax. Mark each as complete as you go. Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` if you want structured execution.

- **Asana task:** <url>
- **Milestone:** M<n> :: <name>
- **Purpose:** <one sentence, verbatim from the Asana task description's Purpose>
```

## Files

A focused list grouped by action. Every path must be real (or be a new file based on a clearly-named convention discovered during codebase exploration). If a path can't be confirmed, the refine-tasks Phase 2c codebase discovery wasn't deep enough — go back and finish it before finalizing the plan.

```markdown
## Files

- **Create:**
  - `src/core/employees/domain/model.py` — Employee entity + EmployeeCreate/EmployeeUpdate schemas
  - `src/core/employees/infrastructure/repository.py` — SQLAlchemy implementation
  - `src/api/routers/employees.py` — CRUD endpoints
  - `tests/core/employees/test_employees_api.py` — endpoint tests

- **Modify:**
  - `src/api/main.py` — register the employees router (1-line change)
  - `src/core/database/models.py` — add Employee SQLAlchemy model

- **Reference (read, don't modify):**
  - `src/core/users/domain/model.py` — entity+schema pattern
  - `src/core/users/infrastructure/repository.py` — SQLAlchemy repo pattern
  - `src/api/routers/users.py` — CRUD router structure
  - `tests/core/users/test_users_api.py` — test fixture conventions
```

## Step-by-Step Plan

Each step is one action — small enough to execute and verify before moving on (typically 2–5 minutes). Use `- [ ]` checkbox so an executor can track progress.

### When the task has testable behavior — prefer TDD order

```markdown
- [ ] **Step 1: Write failing test for GET /employees**

  Create `tests/core/employees/test_employees_api.py`:

  ```python
  def test_get_employees_returns_list(client, sample_employees):
      response = client.get("/employees")
      assert response.status_code == 200
      assert len(response.json()) == 3
  ```

- [ ] **Step 2: Run the test — verify it fails**

  ```bash
  pytest tests/core/employees/test_employees_api.py::test_get_employees_returns_list -v
  ```

  Expected: FAIL with route not found / 404.

- [ ] **Step 3: Implement the Employee model**

  Create `src/core/employees/domain/model.py`. Mirror the structure of `src/core/users/domain/model.py`:

  ```python
  class Employee(Base):
      __tablename__ = "employees"
      id: Mapped[int] = mapped_column(primary_key=True)
      name: Mapped[str]
      role: Mapped[str]
      department: Mapped[str]
      is_active: Mapped[bool] = mapped_column(default=True)
  ```

- [ ] **Step 4: Implement the router with the list endpoint**

  Create `src/api/routers/employees.py`. Follow `src/api/routers/users.py`. The list endpoint:

  ```python
  @router.get("/employees", response_model=list[EmployeeRead])
  async def list_employees(repo: EmployeeRepo = Depends(get_employee_repo)):
      return await repo.list()
  ```

- [ ] **Step 5: Register the router in `src/api/main.py`**

  Add after the existing users-router include:

  ```python
  app.include_router(employees_router)
  ```

- [ ] **Step 6: Run the test — verify it passes**

  ```bash
  pytest tests/core/employees/test_employees_api.py::test_get_employees_returns_list -v
  ```

  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add src/core/employees/ src/api/routers/employees.py src/api/main.py tests/core/employees/test_employees_api.py
  git commit -m "feat(employees): list endpoint"
  ```

(Repeat the test → implement → verify → commit cycle for each remaining acceptance criterion: POST, GET by ID, PUT, DELETE.)
```

### When the task isn't easily testable

Config changes, scaffolding, refactors, frontend UI work where visual review is the spec — drop the test-first cadence but keep the bite-sized step-and-verify structure:

```markdown
- [ ] **Step 1: Add the feature flag to `.env.example`**

  Append:
  ```
  EMPLOYEES_ENABLED=true
  ```

- [ ] **Step 2: Verify the value is loaded at startup**

  ```bash
  pnpm dev
  ```

  Expected: dev console logs `EMPLOYEES_ENABLED=true`.

- [ ] **Step 3: Commit**

  ```bash
  git add .env.example
  git commit -m "feat(config): add EMPLOYEES_ENABLED feature flag"
  ```
```

### Step quality

- Every step that changes code shows the **actual code** to write or modify (signature + key body), not a description of what code should do.
- Every step that runs a command shows the **exact command** and the **expected outcome** (pass/fail/output shape).
- Every commit step shows the **exact git commands** including a conventional commit message.
- A step that requires a design decision is a planning bug — that decision should have been resolved in `refine-tasks` Phase 3a (ambiguity batch) and embedded as a stated choice in this plan.

## Patterns to Follow

Cross-cutting conventions the executor would otherwise re-discover. Use this when a pattern spans multiple steps and is too broad to inline into one step.

```markdown
## Patterns to follow

- `src/core/users/domain/model.py` — entity + Pydantic schema split
- `src/core/users/infrastructure/repository.py` — async SQLAlchemy session pattern
- `src/api/routers/users.py` — CRUD router structure, dependency injection
- `tests/core/users/test_users_api.py` — endpoint test fixtures and assertions
```

## Acceptance Criteria Mapping

Map each acceptance criterion (verbatim from the Asana task description) to the step(s) that verify it. This grounds the plan in the task's success conditions and prevents "implementation done but criteria not checked."

```markdown
## Acceptance criteria mapping

| Acceptance criterion | Verified by |
|---|---|
| GET /employees returns all employees with name, role, department | Step 6 (test passes) |
| POST /employees creates and returns entity with generated ID | Step 10 (POST test passes) |
| GET /employees/{id} returns 404 for nonexistent IDs | Step 14 (404 test passes) |
| DELETE soft-deletes (sets is_active=false) | Step 18 (soft-delete test passes) |
```

## Edge Cases

Non-happy-path scenarios with expected behavior. Distinct from acceptance criteria (the success path). The executor must handle these even if no dedicated test is required.

```markdown
## Edge cases

- POST with missing required field — 422 with field-level error
- PUT for nonexistent ID — 404 with error message
- DELETE on already-soft-deleted task — 404 (treat as if it doesn't exist)
- Concurrent updates — last write wins; no optimistic locking required for this task
```

## References

Every source consulted to write this plan: spec sections, exemplar files, related Asana tasks, external docs. Helps the executor verify the plan against current state and chase down anything the plan didn't pre-resolve.

```markdown
## References

- Spec: `docs/spec.md` § Employees
- Pattern: `src/core/users/domain/model.py`
- Pattern: `src/api/routers/users.py`
- Asana milestone: <url>
```

---

## Content Rules

- **Show code where it removes ambiguity, reference files where it doesn't.** Step bodies should contain real snippets — function signatures, the actual key line(s) being added, exact text being modified. Full multi-hundred-line file bodies stay as references ("follow `src/core/users/domain/model.py`").
- **Be opinionated.** Where conventions exist, pick the one to follow. Don't offer alternatives.
- **State technical facts, not predictions.** Only assert file paths and patterns that are real in the current codebase. The code snippets in your steps *are* predictions — they should be grounded in the patterns you reference, not invented from scratch.
- **Resolve cross-task decisions once.** If a sibling task established a pattern (form components, error handling, confirmation dialog style), state it as the established choice rather than re-litigating in every plan.
- **Don't duplicate the Asana description.** Purpose / Scope / Acceptance Criteria already live there. The plan's job is the implementation path — files, patterns, concrete code-bearing steps.
- **No placeholders.** These are plan failures:
  - `TBD`, `TODO`, `fill in details`, `implement later`
  - `add appropriate error handling`, `handle edge cases`, `add validation` (without specifics)
  - `similar to Step N` (repeat the snippet — the executor may be reading out of order)
  - Steps that describe what to do without showing how when the step changes code
  - References to types/functions/methods not defined anywhere in the plan or pointed at via Reference files

## Self-Review

Before saving the plan as the Asana attachment, look at it with fresh eyes:

1. **Acceptance coverage** — does every acceptance criterion map to at least one step in Acceptance Criteria Mapping?
2. **Placeholder scan** — search for the forbidden patterns above. Fix any hits.
3. **Path validity** — every Create / Modify / Reference path either exists or is a clearly-named new file matching a discovered pattern.
4. **Identifier consistency** — same names used the same way throughout. `clearLayers()` in Step 3 and `clearFullLayers()` in Step 7 is a planning bug.
5. **Step granularity** — every step doable in 2–5 minutes by a Claude session, and verifiable before moving to the next.
6. **Code snippet plausibility** — the snippets actually fit the referenced patterns; you didn't invent a signature that contradicts the exemplar files.

Fix issues inline. No re-review loop — just fix and save.

---

## Length expectations

Plan length follows from task complexity — there is no fixed cap. A plan as short as ~30 lines may be perfectly sufficient for a trivial task; a plan of several hundred lines can be appropriate when the task touches many files or has many edge cases.

Two soft signals to watch:

- **Very short plans (<30 lines)** sometimes mean the task is too small to be its own task — consider whether it should be merged with a sibling.
- **Very long plans (>500 lines)** sometimes mean the task is too big — consider whether it should have been split during decomposition.

Neither is a hard rule; let the task drive the length.
