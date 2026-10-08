# Workout Tracker — Architecture

## 1. Overview

Workout Tracker is a personal web application for recording and reviewing strength-training workouts.

The initial application is designed for desktop/browser use. Mobile and responsive improvements may be addressed in a later phase.

The application allows the user to record:

* workout date;
* workout name/type;
* exercises performed;
* sets for each exercise;
* repetitions per set;
* weight used per set.

Future functionality will include workout history and exercise-progress charts.

The initial chart concept is:

* X-axis: workout date;
* line 1: total repetitions across all sets of an exercise;
* line 2: weight used.

Volume and other metrics may be added later.

---

## 2. Current Technology Stack

The initial stack is intentionally simple:

* **Python**
* **Flask**
* **SQLAlchemy**
* **SQLite**
* **HTML**
* **CSS**
* **JavaScript**
* **Jinja**
* **Chart.js** for future charts
* **pytest** for automated tests

The application is a server-rendered Flask application.

### Technologies intentionally excluded from the initial architecture

The project does not currently require:

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

These technologies may only be introduced if a concrete requirement appears and the architectural decision is discussed first.

---

## 3. Architectural Style

The application uses a **monolithic Flask architecture** with clear separation between:

* application setup;
* database configuration;
* domain models;
* HTTP routes;
* templates;
* static assets;
* tests.

The application is not intended to be a distributed system.

The architecture should remain as simple as possible while maintaining clear responsibilities.

---

## 4. Project Structure

Current and planned structure:

```text
workout-tracker/
├── app/
│   ├── __init__.py
│   ├── database.py
│   ├── exercise_library.py
│   ├── models.py
│   ├── schema.py
│   ├── routes/
│   │   ├── workouts.py
│   │   └── exercises.py
│   ├── templates/
│   └── static/
│
├── tests/
│   ├── conftest.py
│   └── test_models.py
│
├── instance/
│   └── workout_tracker.db
│
├── .gitignore
├── ARCHITECTURE.md
├── CLAUDE.md
├── README.md
├── requirements.txt
└── run.py
```

The `services/` directory should **not** be created preemptively.

A service layer should only be introduced when there is a concrete need that cannot be handled cleanly by routes and models.

---

## 5. Application Initialization

`app/__init__.py` uses the Flask Application Factory pattern.

The main entry point is:

```python
create_app(test_config=None)
```

The factory is responsible for:

1. creating the Flask application;
2. configuring the SQLite database URL;
3. applying test configuration when provided;
4. creating the `instance/` directory;
5. initializing the database extension;
6. importing the models so they are registered in `Base.metadata`;
7. creating the local database schema;
8. adding columns that are missing from an existing database (`app/schema.py`);
9. registering the `sync-exercise-library` CLI command;
10. returning the configured Flask application.

The application factory also allows tests to use an isolated database.

---

## 6. Database Architecture

SQLAlchemy is responsible for ORM functionality and communication with SQLite.

The database layer contains:

* SQLAlchemy `Base`;
* engine creation;
* session management;
* SQLite foreign-key configuration;
* application lifecycle cleanup.

The conceptual flow is:

```text
Flask application
       ↓
SQLAlchemy Session
       ↓
SQLAlchemy Engine
       ↓
SQLite database
```

SQLite foreign-key enforcement is explicitly enabled.

The application currently uses `Base.metadata.create_all()` to create the local schema.

This is sufficient during the initial development stage.

`create_all()` is not considered a migration system: it creates missing tables but never changes existing ones.

The local database already contains real workout data, so it must never be deleted or recreated to pick up a schema change.

`app/schema.py` handles the additive changes made so far. On startup, right after `create_all()`, it adds model columns that are missing from an existing table using `ALTER TABLE ... ADD COLUMN` with a default value. This keeps every existing row, id and relationship, and does nothing when the column already exists.

Only additive changes belong there. If a destructive change becomes necessary (renaming or dropping columns, changing types), a real migration tool such as Alembic should be introduced instead of extending `app/schema.py`.

---

## 7. Data Model

The application currently has four core models.

### Workout

Represents a specific workout session.

Main fields:

```text
id
date
name
created_at
updated_at
```

A workout may contain multiple exercises.

Multiple workouts may have the same date.

Workout names are free text.

---

### Exercise

Represents a reusable exercise in the application's fixed exercise library.

Main fields:

```text
id
name
muscle_group
muscle_subgroup
created_at
updated_at
```

`muscle_group` and `muscle_subgroup` are plain text attributes. There are intentionally no separate tables for groups or subgroups.

`XXXXX` marks a group or subgroup that has not been classified with confidence yet. It is stored as a real value so it remains visible in the library and can be corrected later.

The library is controlled by the application, not by the user:

* `app/exercise_library.py` contains the `EXERCISES` list, which is the source of truth;
* `flask --app run sync-exercise-library` creates missing library exercises and updates the classification of existing ones;
* the sync matches exercises by normalized name, never deletes exercises and never changes their ids;
* the sync is not executed automatically on startup;
* the UI is read-only: users browse the library and pick exercises when building a workout. There are no routes to create, edit or delete exercises.

The library is browsed in three levels:

```text
GET /exercises                  categories (derived from Exercise.muscle_group) with exercise counts
GET /exercises/<muscle_group>   exercises of one category, ordered by subgroup and then by name
exercise modal                  name, muscle group/subgroup, recent history table and history chart
```

The exercise modal (`templates/partials/exercise_modal.html` + `static/js/exercise_history.js`) is shared by the category page and the workout detail page. Its data comes from a single endpoint, `GET /exercises/<id>/history`, which returns the exercise, the 5 most recent occurrences for the table and the complete history for the chart.

Exercise names are normalized by trimming surrounding whitespace.

Exercise names are unique case-insensitively after trimming.

For example:

```text
"Supino reto"
" supino reto "
"SUPINO RETO"
```

represent the same exercise name for uniqueness purposes.

---

### WorkoutExercise

Represents an occurrence of an exercise inside a specific workout.

Main fields:

```text
id
workout_id
exercise_id
position
created_at
updated_at
```

This model exists because an `Exercise` is reusable across multiple workouts.

It also stores the exercise's position within the workout.

The same exercise cannot appear more than once in the same workout.

Exercise positions must be positive and unique within a workout.

---

### WorkoutSet

Represents one set performed for a workout exercise.

Main fields:

```text
id
workout_exercise_id
position
repetitions
weight_kg
created_at
updated_at
```

A `WorkoutExercise` can contain multiple sets.

Set positions must be positive and unique within the exercise occurrence.

Repetitions must be positive.

Weight must be zero or greater.

Weight uses decimal precision with a maximum of two decimal places.

Bodyweight/no external load is represented as:

```text
0 kg
```

---

## 8. Relationships

The relationship structure is:

```text
Workout
   │
   │ 1:N
   ↓
WorkoutExercise
   │
   │ N:1
   ↓
Exercise

WorkoutExercise
   │
   │ 1:N
   ↓
WorkoutSet
```

More explicitly:

```text
Workout
  └── WorkoutExercise
          ├── Exercise
          └── WorkoutSet
```

`WorkoutExercise` is the association between a workout and an exercise.

---

## 9. Deletion Rules

Deleting a workout cascades to its workout exercises and sets.

```text
Workout
   ↓ delete
WorkoutExercise
   ↓ delete
WorkoutSet
```

Deleting an exercise that already has workout history is restricted.

The exercise must not be deleted while it is referenced by a `WorkoutExercise`.

This protects historical workout data.

The reusable `Exercise` record is therefore treated as catalog data, while `WorkoutExercise` and `WorkoutSet` represent historical occurrences.

---

## 10. Validation

Validation exists at two levels where appropriate.

### Application/model validation

Python-side validation handles rules such as:

* required names;
* trimming whitespace;
* positive integer values;
* valid weight values;
* maximum decimal precision.

### Database constraints

Database-level constraints protect data integrity against invalid operations reaching the database.

Examples include:

* unique exercise names;
* unique exercise position within a workout;
* unique set position within an exercise occurrence;
* positive positions;
* positive repetitions;
* non-negative weight.

The database remains the final integrity boundary.

---

## 11. Session Management

SQLAlchemy uses a `scoped_session`.

The session is removed when the Flask application context is torn down.

Application code should use the configured database session rather than creating independent SQLAlchemy sessions unnecessarily.

A database operation should normally follow the pattern:

```text
request
  ↓
route
  ↓
db.session
  ↓
model operations
  ↓
commit / rollback
  ↓
response
```

---

## 12. Testing Strategy

Tests use pytest.

The test suite uses an isolated SQLite database created through pytest's temporary directory support.

Tests must not depend on the real application database.

The current test suite verifies:

* model creation;
* name normalization;
* exercise-name uniqueness;
* model relationships;
* duplicate exercise prevention;
* duplicate exercise positions;
* duplicate set positions;
* validation rules;
* workout deletion cascades;
* exercise deletion restrictions.

Tests should be executed with:

```bash
python -m pytest -v
```

A feature should not be considered complete solely because an AI agent reports that tests passed. Tests must be executed locally and their results verified.

---

## 13. Domain Decisions

The initial application intentionally has a limited domain model.

Current decisions:

* single user;
* no authentication;
* workout name/type is free text;
* multiple workouts may occur on the same date;
* exercise names are reusable;
* no duplicate exercise within a workout;
* exercise and set order are preserved;
* weight is stored in kilograms;
* maximum two decimal places for weight;
* bodyweight is represented by `0 kg`;
* no special warm-up set model;
* no failure-set model;
* no drop-set model;
* no special unilateral-set model;
* incomplete workouts may exist while being edited;
* a completed workout must contain at least one exercise;
* each exercise in a completed workout must contain at least one set.

There is currently no separate draft/completed status field.

---

## 14. Development Order

The initial development sequence is:

1. project setup and database;
2. exercise CRUD;
3. workout creation;
4. set entry;
5. workout history/details;
6. progress charts;
7. UI and validation refinement.

Editing and deletion should be implemented as part of the corresponding feature rather than being treated as a separate large phase.

---

## 15. Future Evolution

Potential future functionality includes:

* workout history filtering;
* exercise-progress charts;
* volume calculations;
* CSV import/export;
* improved responsive/mobile UI;
* database migrations;
* additional workout metrics.

These features should not be implemented prematurely.

The architecture should evolve in response to concrete requirements rather than speculative complexity.
