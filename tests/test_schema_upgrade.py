"""Upgrade of a database created before workout templates and session completion."""

import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect

from app import create_app
from app.database import Base, db
from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet, WorkoutTemplate


# The workouts table exactly as it exists before completed_at was added.
PREVIOUS_WORKOUTS_TABLE = """
CREATE TABLE workouts (
    id INTEGER NOT NULL,
    date DATE NOT NULL,
    name VARCHAR(150) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)
"""

TABLES = ("workouts", "exercises", "workout_exercises", "workout_sets")


@pytest.fixture
def previous_database(tmp_path):
    """A database in the previous schema, with sessions, exercises and sets."""
    database_path = tmp_path / "previous_workout_tracker.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    connection = sqlite3.connect(database_path)
    connection.execute(PREVIOUS_WORKOUTS_TABLE)
    connection.commit()
    connection.close()

    # These tables did not change, so they are created from the current models.
    engine = create_engine(database_url)
    Base.metadata.create_all(engine, tables=[Exercise.__table__, WorkoutExercise.__table__, WorkoutSet.__table__])
    engine.dispose()

    connection = sqlite3.connect(database_path)
    connection.executemany(
        "INSERT INTO workouts (id, date, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        [
            (4, "2026-09-28", "Push", "2026-09-28 10:00:00.000000", "2026-09-28 11:30:00.000000"),
            (7, "2026-10-01", "Upper <b>teste</b>", "2026-10-01 09:00:00.000000", "2026-10-01 10:15:00.000000"),
        ],
    )
    connection.executemany(
        "INSERT INTO exercises (id, name, muscle_group, muscle_subgroup, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, '2026-09-01 00:00:00', '2026-09-01 00:00:00')",
        [(1, "Supino 30º", "Peito", "Peitoral clavicular"), (2, "Remada", "Costas", "Latíssimo do dorso")],
    )
    connection.executemany(
        "INSERT INTO workout_exercises (id, workout_id, exercise_id, position, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, '2026-09-28 10:00:00', '2026-09-28 10:00:00')",
        [(10, 4, 1, 1), (11, 4, 2, 2), (12, 7, 1, 1)],
    )
    connection.executemany(
        "INSERT INTO workout_sets (id, workout_exercise_id, position, repetitions, weight_kg, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, '2026-09-28 10:00:00', '2026-09-28 10:00:00')",
        [(100, 10, 1, 10, 22.5), (101, 10, 2, 8, 22.5), (102, 11, 1, 12, 0), (103, 12, 1, 9, 24)],
    )
    connection.commit()
    connection.close()
    return database_path


def snapshot(database_path):
    """Every row of every existing table, as stored."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    rows = {
        table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
        for table in TABLES
    }
    connection.close()
    return rows


def start_app(database_path):
    app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"})
    return app


def stop_app(app):
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def test_upgrade_adds_completed_at_and_template_tables(previous_database):
    app = start_app(previous_database)

    with app.app_context():
        inspector = inspect(db.engine)
        assert "completed_at" in {column["name"] for column in inspector.get_columns("workouts")}
        assert {"workout_templates", "workout_template_exercises"} <= set(inspector.get_table_names())
    stop_app(app)


def test_upgrade_marks_existing_sessions_completed_and_preserves_all_data(previous_database):
    before = snapshot(previous_database)

    stop_app(start_app(previous_database))
    after = snapshot(previous_database)

    # Every existing session is completed, using its last update as completion time.
    assert [workout["completed_at"] for workout in after["workouts"]] == [
        workout["updated_at"] for workout in before["workouts"]
    ]
    # Nothing else changed: same ids, dates, names, timestamps, exercises, order, sets and weights.
    assert [{key: value for key, value in workout.items() if key != "completed_at"} for workout in after["workouts"]] == before["workouts"]
    for table in ("exercises", "workout_exercises", "workout_sets"):
        assert after[table] == before[table]


def test_upgraded_sessions_are_read_as_completed(previous_database):
    app = start_app(previous_database)

    with app.app_context():
        workouts = db.session.query(Workout).order_by(Workout.id).all()
        assert [(workout.id, workout.is_completed) for workout in workouts] == [(4, True), (7, True)]
        assert [set_.weight_kg for set_ in db.session.get(Workout, 4).workout_exercises[0].sets] == [22.5, 22.5]
    stop_app(app)


def test_upgrade_does_not_create_templates_from_old_sessions(previous_database):
    app = start_app(previous_database)

    with app.app_context():
        assert db.session.query(WorkoutTemplate).count() == 0
    stop_app(app)


def test_later_startups_do_not_complete_new_sessions(previous_database):
    app = start_app(previous_database)
    with app.app_context():
        in_progress = Workout(date=date(2026, 10, 9), name="Em andamento")
        db.session.add(in_progress)
        db.session.commit()
        in_progress_id = in_progress.id
    stop_app(app)
    completed_before_restart = snapshot(previous_database)["workouts"]

    # Starting the application again must not run the backfill again.
    app = start_app(previous_database)
    with app.app_context():
        assert db.session.get(Workout, in_progress_id).completed_at is None
        assert db.session.get(Workout, in_progress_id).is_completed is False
    stop_app(app)
    assert snapshot(previous_database)["workouts"] == completed_before_restart


def test_fresh_database_creates_sessions_in_progress(app, session):
    workout = Workout(date=date(2026, 10, 9), name="Push")
    session.add(workout)
    session.commit()

    assert inspect(db.engine).has_table("workout_templates")
    assert workout.completed_at is None


def test_failed_backfill_rolls_back_its_column(previous_database, monkeypatch):
    # If the backfill failed after ALTER TABLE, the column would stay without
    # data and the backfill would never run again; both must roll back.
    import app.schema as schema

    monkeypatch.setattr(
        schema,
        "COLUMN_UPGRADES",
        [("workouts", "completed_at", "DATETIME", "UPDATE workouts SET no_such_column = 1")],
    )
    before = snapshot(previous_database)
    engine = create_engine(f"sqlite:///{previous_database.as_posix()}")

    with pytest.raises(Exception):
        schema.upgrade_schema(engine)

    assert "completed_at" not in {column["name"] for column in inspect(engine).get_columns("workouts")}
    engine.dispose()
    assert snapshot(previous_database) == before

    # The next startup (with the real upgrade) still completes the old sessions.
    monkeypatch.undo()
    stop_app(start_app(previous_database))
    after = snapshot(previous_database)
    assert [workout["completed_at"] for workout in after["workouts"]] == [
        workout["updated_at"] for workout in before["workouts"]
    ]
