# Implementation Plan Template

The attached `implementation-plan.md` is a standalone markdown document the downstream agent implementing the task (a separate Claude session, another tool, or a human) reads to execute the task with minimal user interaction. It owns the **scope, context, and decisions** - files to touch, patterns to follow, models and function signatures, acceptance criteria, edge cases, how to verify.

The plan does **not** contain implementation code. The downstream agent has full codebase access and a single-task focus; it is better positioned than refine-tasks to derive exact syntax, types, and naming from the live codebase at execution time. refine-tasks removes ambiguity about *what* and *why*; the downstream agent writes the code.

The task description still owns the high-level **what** and **why** (Purpose, Description, Out of scope, Acceptance Criteria, References). The plan deepens it with concrete file paths, models, signatures, exemplar patterns, and a step ordering - without prescribing the code itself.

## Plan Header

Every plan starts with:

```markdown
# <Task title>

- **Task:** <url>
- **Milestone:** <milestone name as it appears in the task manager, e.g., "M1 :: Core Data Layer">
- **Purpose:** <one sentence, verbatim from the task description's Purpose>
```

**Never use T-labels (`T1`, `T2`, ...) in the plan.** T-labels are an internal identifier scheme from an upstream decomposition document - they have no meaning once tasks are in the task manager. Reference sibling tasks by title or task URL; reference earlier steps in this plan by `Step N`.

## Resolved Decisions (optional)

When the Phase 3a ambiguity batch surfaced questions and the user answered them, record each as a one-line decision. Skip the section if no ambiguities were resolved.

```markdown
## Resolved decisions

- **Pagination:** the list endpoint paginates with `?limit` / `?offset`, default `limit=50`, max `limit=200`. (User decision, refinement session 2026-05-27.)
- **Empty state UX:** render a "No employees yet" placeholder; do not hide the list.
- **Soft-delete visibility:** soft-deleted employees are excluded from list/get by default.
```

## Files

A focused list grouped by action. Every path must be real (or a new file based on a clearly-named convention discovered during codebase exploration).

```markdown
## Files

- **Create:**
  - `src/core/employees/domain/model.py` - Employee entity + Pydantic schemas
  - `src/core/employees/infrastructure/repository.py` - SQLAlchemy implementation
  - `src/api/routers/employees.py` - CRUD endpoints
  - `tests/core/employees/test_employees_api.py` - endpoint tests

- **Modify:**
  - `src/api/main.py` - register the employees router
  - `src/core/database/models.py` - add Employee SQLAlchemy model

- **Reference (read, don't modify):**
  - `src/core/users/` - analogous module; mirror its layout
  - `src/api/routers/users.py` - CRUD router pattern
  - `tests/core/users/test_users_api.py` - endpoint test pattern
```

## Models / Schemas

For each new data structure the task introduces: name, fields with types and constraints, relationships. **Describe - don't write the class.** Omit the section if the task doesn't introduce new data structures.

```markdown
## Models

- **Employee** - domain entity for the `employees` table
  - `id`: int, primary key, auto-generated
  - `name`: str, required, max length 100
  - `role`: str, required, max length 100
  - `department`: str, required, max length 100
  - `is_active`: bool, default `true` (soft-delete flag - DELETE sets to false rather than removing the row)

- **EmployeeCreate** - POST request body
  - All Employee fields except `id` and `is_active`

- **EmployeeRead** - response shape for GET endpoints
  - All Employee fields including `id`
```

## Functions and Endpoints

For each new endpoint, public function, or method: name, parameters with types, return shape, behavior. **Describe behavior - don't write the body.** Omit the section if the task is e.g. config-only or refactoring without new public surfaces.

```markdown
## Endpoints

- `GET /employees` - `list_employees(limit, offset, repo) -> list[EmployeeRead]`
  Returns active employees (`is_active=true`), ordered by `name` ascending. `limit` defaults to 50, max 200. `offset` defaults to 0.

- `POST /employees` - `create_employee(payload: EmployeeCreate, repo) -> EmployeeRead`
  Creates a new employee. Returns the created entity with generated `id`. 201 on success, 422 on validation error.

- `GET /employees/{id}` - `get_employee(id: int, repo) -> EmployeeRead`
  Returns the employee. 404 with `{"error": "not_found"}` if `id` doesn't exist or `is_active=false`.

- `PUT /employees/{id}` - `update_employee(id, payload: EmployeeUpdate, repo) -> EmployeeRead`
  Updates fields present in the payload. 404 if id unknown, 422 on validation error.

- `DELETE /employees/{id}` - `delete_employee(id, repo) -> None`
  Soft-delete: sets `is_active=false`. Returns 204. 404 if id unknown or already inactive.
```

## Patterns to Follow

Cross-cutting conventions the executor would otherwise re-discover. Real exemplar files only.

```markdown
## Patterns to follow

- `src/core/users/domain/model.py` - entity + Pydantic schema split
- `src/core/users/infrastructure/repository.py` - async SQLAlchemy session pattern
- `src/api/routers/users.py` - CRUD router structure, dependency injection, error shapes
- `tests/core/users/test_users_api.py` - endpoint test fixtures and assertions
```

## Step-by-Step Plan

Numbered, ordered steps. Each step is one action describable in a single sentence plus brief context (file, pattern, behavior reference). **No code** - the downstream session writes code by reading the patterns and applying the descriptions in this plan.

Optional `- [ ]` checkbox prefix for execution-tracking tools.

For tasks with testable behavior, **prefer TDD-style ordering:** write a failing test that asserts the acceptance criterion -> verify it fails for the expected reason -> implement -> verify the test passes -> commit. State the assertion *intent*, not the test code.

```markdown
## Steps

- [ ] **Step 1: Write a failing test for `GET /employees`**
  File: `tests/core/employees/test_employees_api.py`
  Pattern: `tests/core/users/test_users_api.py`
  Asserts: response is 200 and the body contains the seeded employees with `name`, `role`, `department`. Use the same fixture pattern as users tests.

- [ ] **Step 2: Run the test - expect failure**
  Expected: the route is not yet registered (404 or "no such route").

- [ ] **Step 3: Implement the Employee SQLAlchemy model**
  File: `src/core/employees/domain/model.py`
  Pattern: `src/core/users/domain/model.py`
  Defines: the `Employee` entity per the Models section.

- [ ] **Step 4: Implement the repository**
  File: `src/core/employees/infrastructure/repository.py`
  Pattern: `src/core/users/infrastructure/repository.py`
  Provides: `list(limit, offset)`, `get(id)`, `create(payload)`, `update(id, payload)`, `soft_delete(id)` on `EmployeeRepo`.

- [ ] **Step 5: Implement the router with the list endpoint**
  File: `src/api/routers/employees.py`
  Pattern: `src/api/routers/users.py`
  Provides: `GET /employees` per the Endpoints section.

- [ ] **Step 6: Register the router**
  File: `src/api/main.py`
  Action: include the employees router alongside the existing users registration.

- [ ] **Step 7: Run the test - expect pass**

- [ ] **Step 8: Commit**
  Conventional commit: `feat(employees): list endpoint`

(Repeat the test -> implement -> verify -> commit cycle for POST, GET by ID, PUT, DELETE.)
```

### When the task isn't easily testable

Config changes, scaffolding, refactors, frontend UI work where visual review is the spec - drop the test-first cadence but keep the bite-sized step structure:

```markdown
## Steps

- [ ] **Step 1: Add the feature flag to `.env.example`**
  Add `EMPLOYEES_ENABLED=true` alongside the existing flags.

- [ ] **Step 2: Verify the flag loads at startup**
  Run the dev server; confirm the new env var is present in the dev console output.

- [ ] **Step 3: Commit**
  Conventional commit: `feat(config): add EMPLOYEES_ENABLED feature flag`
```

## Acceptance Criteria Mapping

Map each acceptance criterion (verbatim from the task description) to the step(s) that verify it.

```markdown
## Acceptance criteria mapping

| Acceptance criterion | Verified by |
|---|---|
| GET /employees returns all employees with name, role, department | Step 7 (list test passes) |
| POST /employees creates and returns entity with generated ID | Step 11 (create test passes) |
| GET /employees/{id} returns 404 for nonexistent IDs | Step 15 (404 test passes) |
| DELETE soft-deletes (sets is_active=false) | Step 19 (soft-delete test passes) |
```

## Edge Cases

Non-happy-path scenarios with expected behavior. The executor must handle these even if no dedicated test is required.

```markdown
## Edge cases

- POST with missing required field - 422 with field-level error
- PUT for nonexistent ID - 404 with `{"error": "not_found"}`
- DELETE on already-soft-deleted task - 404 (treat as if it doesn't exist)
- Concurrent updates - last write wins; no optimistic locking required for this task
```

## How to Test

Concrete commands the executor (or a reviewer) can run end-to-end once the task is complete. Distinct from the per-step "run the test" entries - this is the final verification block that ties everything together.

````markdown
## How to test

```bash
# Run the module's test suite
pytest tests/core/employees/ -v

# Smoke-test the endpoints against a running dev server (use your HTTP client of choice)
GET    http://localhost:8000/employees
POST   http://localhost:8000/employees   {"name":"Alice","role":"Engineer","department":"Backend"}
GET    http://localhost:8000/employees/1
DELETE http://localhost:8000/employees/1
GET    http://localhost:8000/employees/1   # expect 404 after delete
```

Expected: all happy-path calls return 2xx; the GET after DELETE returns 404 with the standard not-found body.
````

For frontend / UI tasks, replace the HTTP smoke test with a step-through of the user flow (e.g., "navigate to /employees, click New, fill the form, click Save, confirm the new row appears in the list").

## References

Every source consulted to write this plan.

```markdown
## References

- Spec: `docs/spec.md` Section "Employees"
- Pattern: `src/core/users/`
- Pattern: `src/api/routers/users.py`
- Task milestone: <url>
```

---

## Content Rules

- **ASCII characters only.** The plan is uploaded to the task manager as an attachment, and the in-app file preview may render it without declaring a UTF-8 charset; non-ASCII bytes are then decoded as Latin-1 / Windows-1252 and become visible mojibake. Replace every typographic character with its ASCII equivalent: em dash and en dash become `-`, right arrow becomes `->`, smart quotes become straight `'` and `"`, ellipsis becomes `...`, the section sign becomes the word `Section`. This rule covers prose, examples, tables, and step descriptions equally.
- **Reference patterns, don't predict code.** Point to exemplar files. The downstream session has the codebase open at execution time and is better positioned than `refine-tasks` to derive exact syntax, types, and naming.
- **Describe models and signatures in structured form, not as class/function declarations.** Field name + type + constraint is all that's needed; the syntax follows from the pattern.
- **Be opinionated.** Where conventions exist, pick the one to follow. Don't offer alternatives.
- **State technical facts, not predictions.** Only assert file paths and patterns that are real in the current codebase. Describing what a new function/endpoint should do is fine; predicting its body is not.
- **Resolve cross-task decisions once.** If a sibling task established a pattern, state it as the established choice rather than re-litigating in every plan.
- **Don't duplicate the task description.** Purpose / Description / Out of scope / Acceptance Criteria already live there. The plan's job is to deepen them with files, patterns, models, signatures, and step ordering.
- **No T-labels.** `T1`, `T2`, ... are breakdown-internal identifiers. Reference sibling tasks by title or task URL; reference earlier steps in this plan by `Step N`.
- **No placeholders.** These are plan failures:
  - `TBD`, `TODO`, `fill in details`, `implement later`
  - `add appropriate error handling`, `handle edge cases`, `add validation` - without specifics
  - `similar to Step N` - repeat the brief description, the executor may be reading out of order
  - Steps that describe a code change without naming the file and a pattern to follow
  - References to types/functions not defined in this plan's Models / Endpoints sections or pointed at via Reference files
- **No code blocks in step bodies.** The only legitimate code in the plan is shell commands inside the "How to test" section. Models and signatures live as structured prose, not as `class Foo:` or `def foo():` declarations.

## Self-Review

Before saving the plan as the task attachment:

1. **ASCII-only** - no em dashes, arrows, smart quotes, ellipses, or section signs anywhere in the plan. `LC_ALL=C grep -P "[^\x00-\x7F]"` on the draft must return nothing.
2. **Acceptance coverage** - every acceptance criterion maps to at least one step in Acceptance Criteria Mapping.
3. **Placeholder scan** - none of the forbidden patterns above remain.
4. **No code blocks outside "How to test"** - models are structured prose, endpoints are described behaviorally, steps describe actions not implementations.
5. **Path validity** - every Create / Modify / Reference path either exists or is a clearly-named new file matching a discovered pattern.
6. **Identifier consistency** - same model / field / function names used the same way throughout.
7. **Step granularity** - each step is one action, executable and verifiable before moving to the next.
8. **Decisions captured** - every choice made during the ambiguity batch landed somewhere in the plan (Resolved Decisions, or embedded in Models / Endpoints / Steps).

Fix issues inline.

---

## Length expectations

Plan length follows from task complexity - there is no fixed cap. A trivial task may need ~30 lines; a complex task with many endpoints, edge cases, and models can be several hundred. Two soft signals:

- **Very short plans (<30 lines)** sometimes mean the task is too small to be its own task - consider whether it should be merged with a sibling.
- **Very long plans (>500 lines)** sometimes mean the task is too big - consider whether it should have been split during decomposition.

Neither is a hard rule; let the task drive the length.
