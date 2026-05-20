# Task Description Template

Each task description must stand alone — a separate session with codebase access but no prior conversation context must be able to execute from it.

## Description Structure

Every task description uses these sections in order. Use Asana HTML formatting (see Formatting Rules below).

### 1. Purpose

One sentence: why this task exists and what it unlocks.

> Implements the employee CRUD API so the frontend can list, create, and edit employees.

### 2. Scope — New Files to Create

Exact file paths with what each should contain or export. Be specific about the file's responsibility.

> - *src/core/employees/domain/model.py* — Employee entity, EmployeeCreate/EmployeeUpdate schemas
> - *src/core/employees/domain/datasource.py* — EmployeeDatasource abstract class
> - *src/core/employees/infrastructure/repository.py* — SQLAlchemy implementation of EmployeeDatasource
> - *src/api/routers/employees.py* — CRUD endpoints: GET /employees, GET /employees/{id}, POST /employees, PUT /employees/{id}, DELETE /employees/{id}

### 3. Scope — Existing Files to Modify

What to change in each file. Be specific about what to add or modify.

> - *src/api/main.py* — register the employees router
> - *src/core/database/models.py* — add Employee SQLAlchemy model

### 4. Files to Reference (Read, Don't Modify)

Files the implementer should read for patterns, conventions, or context. These must be files that actually exist in the codebase.

> - *src/core/users/domain/model.py* — follow this pattern for entity + schema definitions
> - *src/core/users/infrastructure/repository.py* — follow this pattern for SQLAlchemy repository
> - *src/api/routers/users.py* — follow this pattern for CRUD router structure

### 5. API Contract

Point to backend source files rather than inlining request/response shapes. The implementer will read those files directly.

> Read *src/core/employees/domain/model.py* for the EmployeeCreate and EmployeeUpdate schemas (this task creates them).
> Read *src/core/users/domain/model.py* for the pattern to follow.

If the task is frontend and depends on a backend API, point to the backend files:

> Read *backend/src/api/routers/employees.py* for endpoint signatures and *backend/src/core/employees/domain/model.py* for response shapes.

### 6. Traceability to Prior Tasks

When this task depends on work from a previous task, state where to find that work using factual file path references based on architecture conventions.

> The employees core module (entity, datasource, repository) is at *src/core/employees/*. Follow the same structure for the projects module.

Only state things that can be known — file paths based on project conventions. Don't predict component props, function signatures, or implementation details of unbuilt tasks.

### 7. Out of Scope

Explicit "Do NOT" restrictions. Each restriction states what not to do but does NOT reference future tasks by name — just says "that is a separate task."

> - Do NOT implement pagination or filtering — that is a separate task.
> - Do NOT add role-based access control to these endpoints — that is a separate task.
> - Do NOT create the frontend employee list page — that is a separate task.

### 8. Acceptance Criteria

Observable behaviors that confirm the task is done. These should be checkable by looking at the running system or code.

> - GET /employees returns a list of all employees with name, role, and department
> - POST /employees creates an employee and returns the created entity with a generated ID
> - GET /employees/{id} returns 404 with error message when ID doesn't exist
> - DELETE /employees/{id} soft-deletes (sets is_active=false) rather than hard-deletes

---

## Content Rules

These rules determine what goes into a description and how to phrase it.

### Reference, don't replicate
Point to source files by path and let the implementer read them directly. Don't paste code snippets, full schemas, or API response shapes into descriptions.

### Extract, don't include
Don't copy the full spec into descriptions. Extract only what's relevant to this specific task.

### Reference existing patterns by pointing to files
Instead of describing a pattern in prose, name the file that demonstrates it. The implementer can open and read it.

### Point to backend source files for API contracts
Never hardcode request/response shapes in task descriptions. They'll drift from the actual code. Always reference the source files.

### Be opinionated
When there's a clear default or codebase convention, pick it. Don't say "either a modal or inline confirm." Pick one based on existing patterns, or ask the user during Phase 2b if there's no convention.

### State technical facts, not predictions
Reference file paths based on architecture conventions ("the users module is at src/core/users/"). Don't predict component props, function signatures, or implementation details of code that doesn't exist yet.

### Resolve cross-task design decisions once
If a pattern (e.g., confirmation dialog style, form component library, error handling approach) is established in one task and reused in later tasks, state that explicitly: "Reuse the form components from *src/app/components/forms/*." Don't re-explain the same decision in every task.

### State CLAUDE.md conventions only when non-obvious
If the project CLAUDE.md has a convention that directly affects this task's implementation and isn't obvious from reading the code, mention it. Don't restate basic conventions that the implementer will discover on their own.

---

## Formatting Rules (Asana HTML)

Asana renders a subset of HTML. These rules produce clean, compact descriptions.

### Tags to use:
- `<strong>` for section titles (Purpose, Scope, Out of Scope, etc.)
- `<em>` for file paths, function names, types, and technical terms
- `<ul><li>` for bullet lists
- `<a href="...">` for links (Figma URLs, external docs)

### Tags to avoid:
- Never use `<h1>`, `<h2>`, or any heading tags — they add excessive whitespace in Asana
- Never use `<code>` or `<pre>` — Asana renders them poorly
- Never use `<br>` between sections — use `\n` only

### Spacing:
- One `\n` between `</ul>` and the next `<strong>`
- Body text starts immediately after the `<strong>` title line
- No extra blank lines anywhere — keep it compact

### Example:

```html
<strong>Purpose</strong>
Implements the employee CRUD API so the frontend can list, create, and edit employees.
<strong>Scope — New files</strong>
<ul><li><em>src/core/employees/domain/model.py</em> — Employee entity, EmployeeCreate/EmployeeUpdate schemas</li><li><em>src/core/employees/infrastructure/repository.py</em> — SQLAlchemy implementation</li><li><em>src/api/routers/employees.py</em> — CRUD endpoints</li></ul>
<strong>Scope — Existing files to modify</strong>
<ul><li><em>src/api/main.py</em> — register the employees router</li></ul>
<strong>Files to reference</strong>
<ul><li><em>src/core/users/domain/model.py</em> — follow this pattern for entity definitions</li><li><em>src/api/routers/users.py</em> — follow this pattern for router structure</li></ul>
<strong>API contract</strong>
Read <em>src/core/employees/domain/model.py</em> for schema definitions. Follow the pattern in <em>src/core/users/domain/model.py</em>.
<strong>Traceability</strong>
The database migration adding the employees table is created by this task. The users module at <em>src/core/users/</em> demonstrates the expected structure.
<strong>Out of scope</strong>
<ul><li>Do NOT implement pagination or filtering — that is a separate task.</li><li>Do NOT add role-based access control — that is a separate task.</li></ul>
<strong>Acceptance criteria</strong>
<ul><li>GET /employees returns all employees with name, role, department</li><li>POST /employees creates and returns entity with generated ID</li><li>GET /employees/{id} returns 404 with error message for nonexistent IDs</li><li>DELETE soft-deletes (sets is_active=false)</li></ul>
```
