# Workout Tracker — Architecture

## 1. Overview

Workout Tracker is a personal web application for recording and reviewing strength-training workouts.

The application is used in a browser, mainly on desktop. Pages also adapt to narrow screens (a single `max-width: 640px` breakpoint), and reordering by drag and drop works with touch.

The application allows the user to record:

* workout date;
* workout name/type;
* exercises performed;
* sets for each exercise;
* repetitions per set;
* weight used per set.

Workouts are started from reusable templates, which may set target sets and repetitions per exercise.

Recorded workouts are reviewed in a monthly calendar and on each session's page. Each exercise has a history (the exercise modal): a table of its recent occurrences and a chart with:

* X-axis: workout date;
* line 1: total repetitions across all sets of the exercise in that workout;
* line 2: heaviest weight used in that workout.

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
* **Chart.js** for the exercise-history chart, vendored in `app/static/vendor/` (no CDN, no build step)
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

Current structure (`.gitkeep` placeholders omitted):

```text
workout-tracker/
├── app/
│   ├── __init__.py              create_app(): configuration, database, backup and schema upgrade, blueprints
│   ├── database.py              Base, engine, scoped db.session, SQLite foreign keys
│   ├── database_backup.py       verified backup made before a pending schema upgrade
│   ├── exercise_library.py      fixed exercise library (EXERCISES), sync command, grouping
│   ├── models.py                the six models and their validation
│   ├── schema.py                additive schema upgrades and detection of pending ones
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── exercises.py         /exercises: categories, category page, exercise history (JSON)
│   │   ├── workout_templates.py /templates: overview, builder (create and edit), delete, start a session
│   │   └── workouts.py          /workouts: calendar, session page, completion, exercises, sets
│   ├── templates/
│   │   ├── base.html
│   │   ├── exercises/
│   │   │   ├── list.html        library categories
│   │   │   └── category.html    exercises of one category
│   │   ├── workout_templates/
│   │   │   ├── form.html        template builder, used to create and to edit
│   │   │   └── overview.html    template overview: start, edit, delete
│   │   ├── workouts/
│   │   │   ├── list.html        monthly calendar and template cards
│   │   │   ├── detail.html      session page (in progress or completed)
│   │   │   ├── form.html        name and date edit page, for use without JavaScript
│   │   │   └── set_form.html    set edit page, for use without JavaScript
│   │   └── partials/
│   │       ├── exercise_modal.html         exercise details, history table and chart
│   │       ├── exercise_progress.html      recorded sets against the target sets
│   │       ├── icons.html                  inline SVG icon macros
│   │       ├── library_cards.html          category and exercise card macros
│   │       ├── workout_exercise_list.html  exercise cards of a session (also returned to fetch())
│   │       └── workout_exercise_sets.html  sets area of one exercise (also returned to fetch())
│   └── static/
│       ├── css/
│       │   └── main.css
│       ├── js/
│       │   ├── exercise_history.js   exercise modal: history table and chart
│       │   ├── sortable_list.js      drag-and-drop reordering (pointer and keyboard)
│       │   ├── template_builder.js   template builder
│       │   └── workouts.js           calendar dialog, session page, confirmations of the template overview
│       └── vendor/
│           └── chart.umd.min.js      Chart.js
│
├── tests/
│   ├── conftest.py              app, session and client fixtures on a temporary database
│   └── test_*.py                one file per area (see Testing Strategy)
│
├── instance/                    local data, not versioned
│   ├── workout_tracker.db       the real database
│   └── backups/                 created by startup before a schema upgrade
│
├── .gitignore
├── ARCHITECTURE.md
├── CLAUDE.md
├── LICENSE
├── README.md
├── requirements.txt
└── run.py                       app = create_app(), used by `flask --app run`
```

`instance/` may also hold older backups made by hand before earlier upgrades (`workout_tracker.backup-before-*.db`).

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
7. when an existing database has a schema upgrade pending, making a verified backup of it first (`app/database_backup.py`); if the backup fails, the application does not start;
8. creating the local database schema;
9. adding columns that are missing from an existing database (`app/schema.py`);
10. registering the `sync-exercise-library` CLI command;
11. returning the configured Flask application.

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

An upgrade may carry a one-time data backfill, executed in the same transaction and only when the column is created. `workouts.completed_at` uses it: sessions recorded before completion existed are marked completed (`completed_at = updated_at`), while sessions created afterwards start in progress and are never touched by later startups.

The target columns of `workout_template_exercises` and `workout_exercises` are added without a backfill: existing rows keep NULL (no target). Their `ADD COLUMN` definition carries the same named `CHECK` constraint as the models, so an upgraded database and a new one enforce the same range.

Before any of this changes an existing database, startup protects it. `pending_schema_changes()` in `app/schema.py` lists exactly what `create_all()` and `upgrade_schema()` would add (missing tables, missing upgrade columns). When the list is empty, startup goes on without a backup; a new database without tables has nothing to protect either. Otherwise `backup_database()` in `app/database_backup.py`:

* copies the database with SQLite's online backup API, through the application's engine. Unlike a file copy, it captures one consistent state, including committed changes still in a WAL file;
* writes it to a `backups/` folder next to the database (`instance/backups/`, ignored by Git) with a new timestamped name, created exclusively so an existing backup is never overwritten;
* verifies it: it opens read-only, passes `PRAGMA integrity_check` and has the same tables and row counts as the database.

Only then does the upgrade run. If the backup cannot be made or verified, a `DatabaseBackupError` stops the startup before any schema change. If the upgrade fails afterwards, the error propagates and the backup is kept; it is never restored automatically (README: restoring a backup). Backups are never deleted by the application, and the log names only the pending changes and the backup file, never data.

Only additive changes belong there. If a destructive change becomes necessary (renaming or dropping columns, changing types), a real migration tool such as Alembic should be introduced instead of extending `app/schema.py`.

---

## 7. Data Model

The application currently has six core models.

### Workout

Represents a specific workout session.

Main fields:

```text
id
date
name
completed_at
created_at
updated_at
```

`completed_at` is `NULL` while the session is in progress and is set once when the session is completed. A completed session is read-only.

A workout may contain multiple exercises.

Multiple workouts may have the same date.

Workout names are free text.

Workouts are reached through a monthly calendar (`GET /workouts?month=YYYY-MM`, current month by default), rendered on the server from the workouts of that month. A day with one workout links to it; a day with several opens a dialog with their cards, ordered like workouts on the same date elsewhere (`created_at` desc, then `id` desc).

Sessions are never created empty. Below the calendar, the workouts page shows one card per template (alphabetical); each opens the template's overview (`GET /templates/<id>`): its exercises in order with their targets, and the "Iniciar treino" button (`POST /templates/<id>/start`, today's session), "Editar modelo" and "Excluir modelo" (with confirmation). Viewing the overview never changes anything. "Novo modelo", in the workouts page header and in the empty state of the cards, opens the template builder (`GET /templates/new`). The old addresses keep working: `GET /templates` redirects to the cards (`/workouts#modelos`) and `GET /workouts/new` to the builder. Saving a template leads to its overview; deleting it, to the cards.

The same builder (`templates/workout_templates/form.html` + `static/js/template_builder.js`) creates a template (`GET /templates/new`, `POST /templates`) and edits one (`GET /templates/<id>/edit`, `POST /templates/<id>/edit`). It keeps the name, the exercises, their order and their targets in memory and sends them only when saved; an edit replaces the template's name and exercise list in a single commit and never touches sessions, which keep the copies they made when they started. Exercises are reordered by dragging a handle (`static/js/sortable_list.js`, Pointer Events for mouse and touch, arrow keys on the handle), without any library.

On the workout page, exercises start collapsed. Sets are added, edited and deleted with `fetch()` (`static/js/workouts.js`) using the existing set routes: when the request asks for JSON they return the re-rendered sets area of that exercise (`templates/partials/workout_exercise_sets.html`, the same template used by the full page); regular form submissions keep the redirect behaviour.

The name and the date of a session in progress are changed in place: clicking them in the page header shows a small form that sends only that field to `POST /workouts/<id>/edit` with `fetch()` (the route keeps a field that is not sent; the full edit page remains for use without JavaScript). Only that session changes; its template and other sessions do not. Each exercise card shows the targets copied from the template and the recorded sets against the target sets (`2/4 séries`, `templates/partials/exercise_progress.html`), re-rendered by the set routes after a set is added or deleted. Progress counts recorded sets whatever their repetitions, shows extra sets as they are (`5/4`) and shows only the count when there is no target; each set row shows the target repetitions as a reference, and the first set starts with them.

Exercises of a session in progress are added, removed and reordered the same way: when asked for JSON, those routes return the re-rendered exercise list (`templates/partials/workout_exercise_list.html`), which replaces the whole list, since one change renumbers positions. Reordering is drag and drop on a handle (`static/js/sortable_list.js`, also with the arrow keys): the page sends the whole new order to `POST /workouts/<id>/exercises/reorder`, which accepts it only if it lists exactly the session's exercises and rewrites the positions in one commit (first above the current ones, then 1..n, so the unique positions never collide). If the server refuses the order or cannot be reached, the page puts back the saved order. The page keeps the scroll position and reopens the exercises that were open (cards keep their `exercise-<id>`). Click and submit listeners of the workout page and of the exercise modal are delegated to the document, so they keep working on the replaced HTML.

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

The exercise modal (`templates/partials/exercise_modal.html` + `static/js/exercise_history.js`) is shared by the category page, the workout detail page and the template builder (`GET /templates/new` and `GET /templates/<id>/edit`), where it also shows an "Adicionar" button handled by `static/js/template_builder.js`. Its data comes from a single endpoint, `GET /exercises/<id>/history`, which returns the exercise, the 5 most recent occurrences for the table and the complete history for the chart.

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
target_sets
target_repetitions
created_at
updated_at
```

This model exists because an `Exercise` is reusable across multiple workouts.

`target_sets` and `target_repetitions` are the planned sets and repetitions per set, copied from the template when the session starts. They are optional: exercises added to a session by hand and sessions recorded before targets existed have none. Targets are a reference only; any number of sets and repetitions can be recorded, and they never block completion.

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

Positions and repetitions are at most `2^63 - 1`, the largest SQLite INTEGER.

Weight must be zero or greater.

Weight uses decimal precision with a maximum of two decimal places.

Weight must be a finite number of at most `999999.99` kg, the largest value of the `Numeric(8, 2)` column. SQLite does not enforce the declared precision, so larger values (or infinity) would otherwise be stored inexactly instead of being rejected.

Bodyweight/no external load is represented as:

```text
0 kg
```

---

### WorkoutTemplate

Represents a reusable list of exercises (for example "Push") from which sessions are started.

Main fields:

```text
id
name
created_at
updated_at
```

Template names follow the exercise-name rules: trimmed, required and unique case-insensitively.

A template has no date and no sets.

---

### WorkoutTemplateExercise

Represents an exercise of a template, at a given position.

Main fields:

```text
id
template_id
exercise_id
position
target_sets
target_repetitions
created_at
updated_at
```

The same exercise cannot appear twice in a template, and positions are positive and unique within a template.

Targets are whole numbers from 1 to 20 (`target_sets`) and from 1 to 100 (`target_repetitions`, per set), checked by the models and by a `CHECK` constraint. They are optional in the database, so templates created before targets existed keep working without invented values.

Starting a session copies the template's name, exercises and targets (in order, without sets) into a new `Workout` and its `WorkoutExercise` rows. The session keeps no reference to the template, so changing or deleting a template never affects existing sessions.

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

Templates have their own association with the exercise library:

```text
WorkoutTemplate
  └── WorkoutTemplateExercise
          └── Exercise
```

There is intentionally no relationship between `Workout` and `WorkoutTemplate`.

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

Deleting a template cascades only to its `WorkoutTemplateExercise` rows. It never deletes sessions or library exercises, and deleting a session never deletes templates. A library exercise used by a template cannot be deleted either.

---

## 10. Validation

Validation exists at two levels where appropriate.

### Application/model validation

Python-side validation handles rules such as:

* required names;
* trimming whitespace;
* positive integer values, up to `2^63 - 1`;
* valid weight values (finite, from `0` to `999999.99`);
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

Each test gets an isolated SQLite database in pytest's temporary directory: the `app` fixture of `tests/conftest.py` calls `create_app()` with `TESTING` and a `DATABASE_URL` in `tmp_path`.

Tests must not depend on the real application database, and must never start the application against it.

Tests that need more than one connection (concurrent requests) run a second test client in another thread, on the same temporary file. Schema upgrade and backup tests build databases with the schema of an earlier version in `tmp_path`.

The suite is organised by area:

| Area | Files |
|---|---|
| Models and validation | `test_models.py`, `test_workout_templates_model.py`, `test_out_of_range_input.py` |
| Exercise library and history | `test_exercise_library.py`, `test_exercises.py`, `test_exercise_history.py` |
| Templates | `test_workout_templates.py`, `test_template_builder.py`, `test_template_editing.py`, `test_template_overview.py`, `test_workout_targets.py` |
| Sessions | `test_workouts.py`, `test_session_flow.py`, `test_session_execution.py`, `test_workout_exercises.py`, `test_workout_exercise_fetch.py`, `test_workout_sets.py`, `test_workout_detail_page.py`, `test_workout_completion.py`, `test_workout_concurrency.py` |
| Calendar and session details | `test_workout_calendar.py`, `test_workout_history.py` |
| Shared layout | `test_ui.py` |
| Database upgrades and backups | `test_schema_upgrade.py`, `test_targets_schema_upgrade.py`, `test_database_backup.py` |

JavaScript is not executed by the suite: tests check the HTML and JSON that the scripts rely on, and the content of the served scripts and CSS.

Tests should be executed with:

```bash
python -m pytest -v
```

A single file can be run while developing (`python -m pytest -v tests/test_models.py`), and `python -m pytest -W default` also shows warnings; the suite currently runs without any.

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
* sessions are started from templates and stay in progress while being recorded;
* a session can be completed when it has at least one exercise with at least one set (other exercises may have no sets);
* completion is permanent and makes the session read-only;
* sessions recorded before completion existed were migrated as completed, without this validation.

`Workout.completed_at` is the completion status.

Completing a session is a single conditional `UPDATE` (still in progress and with at least one set). Every route that changes a session starts its transaction with another conditional `UPDATE` (still in progress, which also records `updated_at`). SQLite allows one writer at a time, so a completion and a change of the same session are serialized: a change never lands on a session completed in the meantime, and a completion always sees the changes saved before it.

Ids in URLs and forms are limited to the SQLite INTEGER range (`2^63 - 1`): the `<int:...>` URL converter does not match larger ids, so they get HTTP 404 like any unknown id; an exercise id beyond it gets 404 when adding an exercise to a session and the invalid exercise list message when creating a template. Positions and repetitions share that limit, and weights are limited to `999999.99` (the `Numeric(8, 2)` column), since SQLite does not enforce declared precision. Excessive repetitions or weights get the usual set validation error (HTTP 400 for fetch requests). In every case nothing is written.

---

## 14. Development Order

The development sequence and its current state:

1. project setup and database — done, including additive schema upgrades with a verified backup;
2. exercise library — done. It started as an exercise CRUD and became a fixed, read-only library synced from `app/exercise_library.py`;
3. workout creation — done, through templates (create, edit, delete, start a session) with optional targets;
4. set entry — done: add, edit and delete sets with `fetch()`, progress against the targets, completion;
5. workout history/details — done: monthly calendar and session page;
6. progress charts — done: history table and chart in the exercise modal;
7. UI and validation refinement — ongoing, as small focused changes.

Editing and deletion should be implemented as part of the corresponding feature rather than being treated as a separate large phase.

---

## 15. Future Evolution

Potential future functionality includes:

* workout history filtering;
* volume calculations;
* CSV import/export;
* further responsive/mobile improvements;
* a real migration tool (such as Alembic), if a destructive schema change becomes necessary;
* additional workout metrics.

These features should not be implemented prematurely.

The architecture should evolve in response to concrete requirements rather than speculative complexity.
