# CLAUDE.md

## Project Context

Workout Tracker is a personal workout-tracking web application.

The project is intentionally being developed as a simple, maintainable Flask application.

Before making architectural changes, read `ARCHITECTURE.md`.

---

## Development Principles

Follow this workflow:

```text
define
  ↓
discuss
  ↓
implement
  ↓
read/review
  ↓
test
  ↓
understand
  ↓
commit
```

Do not treat implementation as complete merely because the code was generated successfully.

After implementing a feature:

1. explain what was changed;
2. identify important architectural decisions;
3. run the relevant tests;
4. report the actual test result;
5. do not claim tests passed unless they were actually executed.

The developer should understand the important parts of the implementation. Prefer clear explanations over unnecessary abstraction.

---

## Technology Constraints

Use the existing stack:

* Python
* Flask
* SQLAlchemy
* SQLite
* Jinja
* HTML
* CSS
* JavaScript
* pytest
* Chart.js when charts are implemented

Do not introduce the following without explicit discussion:

* React
* Vue
* Angular
* PostgreSQL
* Docker
* Redis
* Kubernetes
* microservices
* JWT authentication
* Tailwind CSS
* unnecessary third-party frameworks or libraries

The simplest solution that correctly satisfies the requirement is preferred.

---

## Architecture Rules

Keep the application as a Flask monolith.

Respect the responsibilities already defined in `ARCHITECTURE.md`.

Do not introduce:

* unnecessary service layers;
* repositories;
* factories;
* abstractions;
* generic CRUD frameworks;
* unnecessary design patterns.

A `services/` directory should only be introduced when there is a concrete requirement that justifies it.

Do not change the data model or relationship structure without discussing the impact first.

---

## Database Rules

Use SQLAlchemy for database access.

Use the configured `db.session`.

Do not create unrelated independent database connections or sessions.

SQLite is the current database and should remain the database during the initial development stages.

Remember:

* `Workout` represents a workout session;
* `Exercise` represents a reusable exercise;
* `WorkoutExercise` represents an exercise occurrence within a workout;
* `WorkoutSet` represents an individual set.

Preserve the existing foreign-key and deletion rules.

Do not replace `create_all()` with a migration system unless schema evolution actually requires it.

---

## Validation Rules

Respect the existing domain rules:

* names must not be empty after trimming;
* exercise names are unique case-insensitively after trimming;
* exercise positions are positive;
* set positions are positive;
* repetitions are positive;
* weight cannot be negative;
* weight has at most two decimal places;
* bodyweight/no external load is represented by `0 kg`;
* the same exercise cannot appear twice in one workout;
* set positions must be unique within an exercise occurrence.

Do not silently change these rules.

---

## Testing Requirements

Every new feature that introduces behavior or business rules should include appropriate tests.

Run tests after implementation:

```bash
python -m pytest -v
```

For focused development, specific tests may be executed, for example:

```bash
python -m pytest -v tests/test_models.py
```

Do not delete or weaken existing tests simply to make a new implementation pass.

If an existing test conflicts with a deliberate requirement change, explain the conflict before changing the test.

Tests should verify behavior, not implementation details unnecessarily.

---

## Flask Rules

Use the existing application factory:

```python
create_app()
```

Routes should be organized according to feature responsibility.

Keep HTTP concerns in routes and application/domain behavior in appropriate layers.

Use Jinja for server-rendered HTML during the initial implementation.

Do not introduce a frontend framework.

---

## Git Rules

The project uses a simple Git workflow:

```text
main
  ↑
feature/<feature-name>
```

Examples:

```text
feature/project-setup
feature/exercises
feature/workouts
feature/history
feature/charts
```

Do not create commits automatically unless explicitly requested.

Do not rewrite history, force-push, rebase, reset, or delete branches without explicit approval.

Before suggesting a commit:

1. verify the implementation;
2. verify tests;
3. check the Git diff;
4. identify files that will be committed.

Use clear commit messages following the general Conventional Commits style:

```text
feat: ...
fix: ...
test: ...
refactor: ...
docs: ...
```

---

## Code Style

Prefer readable, explicit Python.

Do not optimize prematurely.

Do not compress code merely to reduce line count.

Use descriptive names.

Avoid comments that simply restate obvious code.

Comments should explain important reasoning or non-obvious behavior.

Follow the existing style of the project instead of introducing a different style in individual files.

---

## AI Behavior

When asked to implement a feature:

1. inspect the existing relevant code first;
2. identify the affected architecture;
3. explain the proposed approach briefly;
4. implement the smallest appropriate change;
5. add/update tests;
6. run the tests;
7. report the actual result;
8. identify any limitations or follow-up work.

Do not silently redesign unrelated parts of the application.

Do not introduce new technologies or architectural patterns merely because they are common in other projects.

If a requirement is ambiguous and the ambiguity could materially affect the architecture or data model, ask before implementing.

---

## Scope Control

The project is intentionally being developed incrementally.

Do not implement future functionality ahead of the current feature unless explicitly requested.

Current development order:

1. project setup and database;
2. exercise CRUD;
3. workout creation;
4. set entry;
5. history/details;
6. charts;
7. UI refinement.

Keep the implementation focused on the current phase.

---

## Important Principle

The goal is not merely to generate working code.

The goal is to build a maintainable application while the developer understands:

* why the code exists;
* how the components interact;
* how data flows through the application;
* how to test the behavior;
* how to debug problems;
* how to make small changes without relying entirely on AI.

Prefer teaching and explaining important concepts when they are introduced.
