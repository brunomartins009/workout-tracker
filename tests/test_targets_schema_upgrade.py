"""Upgrade of a database created before targets of sets and repetitions existed.

The two changed tables are created with the exact DDL they have in a database
of the previous version (templates and completion already present, targets
not yet), with templates, sessions and sets in them.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect

from app import create_app
from app.database import Base, db
from app.models import Exercise, Workout, WorkoutSet, WorkoutTemplate


PREVIOUS_WORKOUT_EXERCISES_TABLE = """
CREATE TABLE workout_exercises (
	id INTEGER NOT NULL,
	workout_id INTEGER NOT NULL,
	exercise_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_workout_exercise UNIQUE (workout_id, exercise_id),
	CONSTRAINT uq_workout_exercise_position UNIQUE (workout_id, position),
	CONSTRAINT ck_workout_exercise_position_positive CHECK (position > 0),
	FOREIGN KEY(workout_id) REFERENCES workouts (id) ON DELETE CASCADE,
	FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE RESTRICT
)
"""

PREVIOUS_WORKOUT_TEMPLATE_EXERCISES_TABLE = """
CREATE TABLE workout_template_exercises (
	id INTEGER NOT NULL,
	template_id INTEGER NOT NULL,
	exercise_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_workout_template_exercise UNIQUE (template_id, exercise_id),
	CONSTRAINT uq_workout_template_exercise_position UNIQUE (template_id, position),
	CONSTRAINT ck_workout_template_exercise_position_positive CHECK (position > 0),
	FOREIGN KEY(template_id) REFERENCES workout_templates (id) ON DELETE CASCADE,
	FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE RESTRICT
)
"""

TABLES = ("workouts", "exercises", "workout_exercises", "workout_sets", "workout_templates", "workout_template_exercises")
NEW_COLUMNS = ("target_sets", "target_repetitions")
TIMESTAMP = "'2026-10-01 10:00:00.000000'"


@pytest.fixture
def previous_database(tmp_path):
    database_path = tmp_path / "previous_workout_tracker.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    # Unchanged tables come from the current models; the two changed ones use
    # the previous DDL, without target columns.
    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[Exercise.__table__, Workout.__table__, WorkoutSet.__table__, WorkoutTemplate.__table__],
    )
    engine.dispose()
    connection = sqlite3.connect(database_path)
    connection.execute(PREVIOUS_WORKOUT_EXERCISES_TABLE)
    connection.execute(PREVIOUS_WORKOUT_TEMPLATE_EXERCISES_TABLE)
    # Index of the previous schema (created by the models then).
    connection.execute("CREATE INDEX ix_workout_exercises_workout_id ON workout_exercises (workout_id)")
    connection.execute("CREATE INDEX ix_workout_exercises_exercise_id ON workout_exercises (exercise_id)")
    connection.execute("CREATE INDEX ix_workout_template_exercises_template_id ON workout_template_exercises (template_id)")
    connection.execute("CREATE INDEX ix_workout_template_exercises_exercise_id ON workout_template_exercises (exercise_id)")

    connection.executemany(
        f"INSERT INTO exercises (id, name, muscle_group, muscle_subgroup, created_at, updated_at) VALUES (?, ?, 'Peito', 'Peitoral médio', {TIMESTAMP}, {TIMESTAMP})",
        [(1, "Supino"), (2, "Crucifixo"), (3, "Remada")],
    )
    connection.executemany(
        f"INSERT INTO workouts (id, date, name, completed_at, created_at, updated_at) VALUES (?, ?, ?, ?, {TIMESTAMP}, {TIMESTAMP})",
        [(4, "2026-10-01", "Push", "2026-10-01 11:00:00.000000"), (7, "2026-10-08", "Push", None)],
    )
    connection.executemany(
        f"INSERT INTO workout_exercises (id, workout_id, exercise_id, position, created_at, updated_at) VALUES (?, ?, ?, ?, {TIMESTAMP}, {TIMESTAMP})",
        [(10, 4, 1, 1), (11, 4, 2, 2), (12, 7, 2, 1), (13, 7, 1, 2)],
    )
    connection.executemany(
        f"INSERT INTO workout_sets (id, workout_exercise_id, position, repetitions, weight_kg, created_at, updated_at) VALUES (?, ?, ?, ?, ?, {TIMESTAMP}, {TIMESTAMP})",
        [(100, 10, 1, 10, 22.5), (101, 10, 2, 8, 0), (102, 13, 1, 12, 30)],
    )
    connection.executemany(
        f"INSERT INTO workout_templates (id, name, created_at, updated_at) VALUES (?, ?, {TIMESTAMP}, {TIMESTAMP})",
        [(1, "Push"), (2, "Pull <b>B</b>")],
    )
    connection.executemany(
        f"INSERT INTO workout_template_exercises (id, template_id, exercise_id, position, created_at, updated_at) VALUES (?, ?, ?, ?, {TIMESTAMP}, {TIMESTAMP})",
        [(20, 1, 1, 1), (21, 1, 2, 2), (22, 2, 3, 1)],
    )
    connection.commit()
    connection.close()
    return database_path


def snapshot(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    rows = {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")] for table in TABLES}
    connection.close()
    return rows


def columns(database_path, table):
    connection = sqlite3.connect(database_path)
    result = [tuple(row) for row in connection.execute(f"PRAGMA table_info({table})")]
    connection.close()
    return result


def table_sql(database_path, table):
    connection = sqlite3.connect(database_path)
    result = connection.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
    connection.close()
    return result


def start_and_stop(database_path):
    app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"})
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def test_upgrade_adds_nullable_target_columns_and_keeps_every_row(previous_database):
    before = snapshot(previous_database)

    start_and_stop(previous_database)
    after = snapshot(previous_database)

    for table in ("workout_exercises", "workout_template_exercises"):
        assert [column[1] for column in columns(previous_database, table)][-2:] == list(NEW_COLUMNS)
        # Existing rows get no invented target.
        assert all(row["target_sets"] is None and row["target_repetitions"] is None for row in after[table])
        # Every other column of every row is unchanged.
        assert [{k: v for k, v in row.items() if k not in NEW_COLUMNS} for row in after[table]] == before[table]
    for table in ("workouts", "exercises", "workout_sets", "workout_templates"):
        assert after[table] == before[table]


def test_upgraded_tables_enforce_the_same_rule_as_a_new_database(previous_database, tmp_path):
    start_and_stop(previous_database)
    fresh = tmp_path / "fresh.db"
    start_and_stop(fresh)

    for table in ("workout_exercises", "workout_template_exercises"):
        # Same type, nullability and default; only the physical column order
        # differs (ADD COLUMN appends, a new table follows the model).
        def by_name(database_path):
            return {column[1]: column[2:] for column in columns(database_path, table)}

        assert by_name(previous_database) == by_name(fresh)
        upgraded_sql = table_sql(previous_database, table)
        fresh_sql = table_sql(fresh, table)
        for column, maximum in (("target_sets", 20), ("target_repetitions", 100)):
            rule = f"CHECK ({column} BETWEEN 1 AND {maximum})"
            assert rule in upgraded_sql
            assert rule in fresh_sql

    connection = sqlite3.connect(previous_database)
    with pytest.raises(sqlite3.IntegrityError, match="ck_workout_template_exercise_target_sets_range"):
        connection.execute("UPDATE workout_template_exercises SET target_sets = 21 WHERE id = 20")
    with pytest.raises(sqlite3.IntegrityError, match="ck_workout_exercise_target_repetitions_range"):
        connection.execute("UPDATE workout_exercises SET target_repetitions = 0 WHERE id = 10")
    connection.execute("UPDATE workout_template_exercises SET target_sets = 4, target_repetitions = 10 WHERE id = 20")
    connection.commit()
    connection.close()


def test_upgraded_database_keeps_working_with_old_templates_and_sessions(previous_database):
    start_and_stop(previous_database)
    app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{previous_database.as_posix()}"})
    client = app.test_client()

    with app.app_context():
        assert client.get("/workouts/4").status_code == 200
        assert client.get("/workouts/7").status_code == 200
        # The cards and the overview of a template without targets.
        assert 'href="/templates/2"' in client.get("/workouts").get_data(as_text=True)
        overview = client.get("/templates/1").get_data(as_text=True)
        assert overview.count("Sem meta definida") == 2
        # An old template (no targets) still starts a session, without targets.
        response = client.post("/templates/1/start")
        assert response.status_code == 302
        started = db.session.query(Workout).order_by(Workout.id.desc()).first()
        assert [(item.exercise_id, item.target_sets, item.target_repetitions) for item in sorted(started.workout_exercises, key=lambda item: item.position)] == [
            (1, None, None),
            (2, None, None),
        ]
        # Integrity of the whole database after use.
        connection = db.engine.raw_connection()
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.close()
        db.session.remove()
        db.engine.dispose()


def test_later_startups_change_nothing(previous_database):
    start_and_stop(previous_database)
    after_first = snapshot(previous_database)
    sql_after_first = {table: table_sql(previous_database, table) for table in TABLES}

    start_and_stop(previous_database)

    assert snapshot(previous_database) == after_first
    assert {table: table_sql(previous_database, table) for table in TABLES} == sql_after_first


def test_fresh_database_has_target_columns(tmp_path):
    database_path = tmp_path / "fresh.db"
    start_and_stop(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    for table in ("workout_exercises", "workout_template_exercises"):
        names = {column["name"]: column for column in inspect(engine).get_columns(table)}
        assert names["target_sets"]["nullable"] is True
        assert names["target_repetitions"]["nullable"] is True
    engine.dispose()
