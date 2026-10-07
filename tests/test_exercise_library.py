import sqlite3
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect

from app import create_app
from app.database import Base, db
from app.exercise_library import EXERCISES, group_exercises, normalize_exercise_name, sync_exercise_library
from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


# The exercises table exactly as it existed before muscle groups were added.
OLD_EXERCISES_TABLE = """
CREATE TABLE exercises (
    id INTEGER NOT NULL,
    name VARCHAR(150) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)
"""


@pytest.fixture
def old_database_url(tmp_path):
    """A database in the previous schema that already contains real-looking data."""
    database_path = tmp_path / "old_workout_tracker.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    connection = sqlite3.connect(database_path)
    connection.execute(OLD_EXERCISES_TABLE)
    connection.execute("CREATE UNIQUE INDEX uq_exercises_normalized_name ON exercises (lower(trim(name)))")
    connection.commit()
    connection.close()

    # The other tables did not change, so they are created from the current models.
    engine = create_engine(database_url)
    Base.metadata.create_all(
        engine,
        tables=[Workout.__table__, WorkoutExercise.__table__, WorkoutSet.__table__],
    )
    engine.dispose()

    connection = sqlite3.connect(database_path)
    timestamp = "2026-10-01 10:00:00"
    connection.executemany(
        "INSERT INTO exercises (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        [(7, "Supino 30º", timestamp, timestamp), (12, "Exercício antigo", timestamp, timestamp)],
    )
    connection.execute(
        "INSERT INTO workouts (id, date, name, created_at, updated_at) VALUES (1, '2026-10-01', 'Push', ?, ?)",
        (timestamp, timestamp),
    )
    connection.executemany(
        "INSERT INTO workout_exercises (id, workout_id, exercise_id, position, created_at, updated_at)"
        " VALUES (?, 1, ?, ?, ?, ?)",
        [(3, 7, 1, timestamp, timestamp), (4, 12, 2, timestamp, timestamp)],
    )
    connection.execute(
        "INSERT INTO workout_sets (id, workout_exercise_id, position, repetitions, weight_kg, created_at, updated_at)"
        " VALUES (9, 3, 1, 10, 42.5, ?, ?)",
        (timestamp, timestamp),
    )
    connection.commit()
    connection.close()
    return database_url


@pytest.fixture
def old_database_app(old_database_url):
    app = create_app({"TESTING": True, "DATABASE_URL": old_database_url})
    with app.app_context():
        yield app
        db.session.remove()
        db.engine.dispose()


# Schema upgrade of an existing database


def test_startup_adds_muscle_columns_to_existing_database(old_database_app):
    columns = {column["name"] for column in inspect(db.engine).get_columns("exercises")}

    assert {"muscle_group", "muscle_subgroup"} <= columns


def test_startup_preserves_existing_exercises_ids_and_marks_them_unclassified(old_database_app):
    exercises = db.session.query(Exercise).order_by(Exercise.id).all()

    assert [(exercise.id, exercise.name) for exercise in exercises] == [(7, "Supino 30º"), (12, "Exercício antigo")]
    assert all(exercise.muscle_group == "XXXXX" for exercise in exercises)
    assert all(exercise.muscle_subgroup == "XXXXX" for exercise in exercises)


def test_startup_preserves_workouts_relations_and_sets(old_database_app):
    workout = db.session.get(Workout, 1)

    assert [workout_exercise.exercise.id for workout_exercise in workout.workout_exercises] == [7, 12]
    workout_set = db.session.get(WorkoutSet, 9)
    assert workout_set.workout_exercise.exercise.name == "Supino 30º"
    assert workout_set.weight_kg == Decimal("42.50")


def test_schema_upgrade_is_idempotent(old_database_url):
    for _ in range(2):
        app = create_app({"TESTING": True, "DATABASE_URL": old_database_url})
        with app.app_context():
            assert db.session.query(Exercise).count() == 2
            db.session.remove()
            db.engine.dispose()


def test_existing_database_app_still_renders_history_and_detail(old_database_app):
    client = old_database_app.test_client()

    assert client.get("/workouts").status_code == 200
    detail = client.get("/workouts/1").get_data(as_text=True)
    assert "Supino 30º" in detail
    assert "Exercício antigo" in detail


# Library sync


LIBRARY = [
    {"name": "Supino 30º", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"},
    {"name": "Cadeira extensora", "muscle_group": "Pernas", "muscle_subgroup": "Quadríceps"},
]


def test_sync_classifies_existing_exercise_without_changing_its_id(old_database_app):
    result = sync_exercise_library(db.session, LIBRARY)

    db.session.expire_all()
    exercise = db.session.get(Exercise, 7)
    assert exercise.name == "Supino 30º"
    assert (exercise.muscle_group, exercise.muscle_subgroup) == ("Peito", "Peitoral clavicular")
    assert result["updated"] == ["Supino 30º"]


def test_sync_creates_missing_library_exercises(old_database_app):
    result = sync_exercise_library(db.session, LIBRARY)

    created = db.session.query(Exercise).filter_by(name="Cadeira extensora").one()
    assert (created.muscle_group, created.muscle_subgroup) == ("Pernas", "Quadríceps")
    assert result["created"] == ["Cadeira extensora"]


def test_sync_never_deletes_exercises_missing_from_library(old_database_app):
    result = sync_exercise_library(db.session, LIBRARY)

    db.session.expire_all()
    untouched = db.session.get(Exercise, 12)
    assert untouched.name == "Exercício antigo"
    assert untouched.muscle_group == "XXXXX"
    assert result["not_in_library"] == ["Exercício antigo"]
    assert db.session.query(WorkoutExercise).count() == 2
    assert db.session.query(WorkoutSet).count() == 1


def test_sync_matches_names_ignoring_case_and_whitespace(session):
    session.add(Exercise(name="supino 30º"))
    session.commit()

    sync_exercise_library(session, [{"name": "  SUPINO 30º ", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"}])

    exercise = session.query(Exercise).one()
    assert exercise.name == "supino 30º"
    assert exercise.muscle_group == "Peito"


def test_sync_is_idempotent(session):
    sync_exercise_library(session, LIBRARY)
    second_result = sync_exercise_library(session, LIBRARY)

    assert second_result == {"created": [], "updated": [], "not_in_library": []}
    assert session.query(Exercise).count() == len(LIBRARY)


def test_sync_command_loads_the_library(app, session):
    result = app.test_cli_runner().invoke(args=["sync-exercise-library"])

    assert result.exit_code == 0
    assert f"Criados: {len(EXERCISES)}" in result.output
    assert session.query(Exercise).count() == len(EXERCISES)


# Library source


def test_library_source_has_unique_names_and_required_fields():
    normalized_names = [normalize_exercise_name(entry["name"]) for entry in EXERCISES]

    assert len(normalized_names) == len(set(normalized_names))
    for entry in EXERCISES:
        assert set(entry) == {"name", "muscle_group", "muscle_subgroup"}
        assert all(value.strip() for value in entry.values())


def test_group_exercises_orders_groups_subgroups_and_names():
    exercises = [
        Exercise(name="Stiff", muscle_group="Pernas", muscle_subgroup="Posteriores de coxa"),
        Exercise(name="Pendente", muscle_group="XXXXX", muscle_subgroup="XXXXX"),
        Exercise(name="Leg press", muscle_group="Pernas", muscle_subgroup="Quadríceps"),
        Exercise(name="Agachamento", muscle_group="Pernas", muscle_subgroup="Quadríceps"),
        Exercise(name="Abdominal curto", muscle_group="Abdômen", muscle_subgroup="Reto abdominal"),
    ]

    grouped = group_exercises(exercises)

    assert [group for group, _ in grouped] == ["Abdômen", "Pernas", "XXXXX"]
    legs = dict(grouped)["Pernas"]
    assert [subgroup for subgroup, _ in legs] == ["Posteriores de coxa", "Quadríceps"]
    assert [exercise.name for exercise in dict(legs)["Quadríceps"]] == ["Agachamento", "Leg press"]


# Adding library exercises to a workout


def create_workout(session):
    workout = Workout(date=date(2026, 10, 6), name="Push")
    session.add(workout)
    session.commit()
    return workout


def test_workout_select_groups_options_by_muscle_group(client, session):
    workout = create_workout(session)
    session.add_all(
        [
            Exercise(name="Supino inclinado", muscle_group="Peito", muscle_subgroup="Peitoral clavicular"),
            Exercise(name="Cadeira extensora", muscle_group="Pernas", muscle_subgroup="Quadríceps"),
        ]
    )
    session.commit()

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)
    chest_group = page.split('<optgroup label="Peito">')[1].split("</optgroup>")[0]
    legs_group = page.split('<optgroup label="Pernas">')[1].split("</optgroup>")[0]

    assert "Supino inclinado — Peitoral clavicular</option>" in chest_group
    assert "Cadeira extensora — Quadríceps</option>" in legs_group
    assert page.index('<optgroup label="Peito">') < page.index('<optgroup label="Pernas">')


def test_library_exercise_can_be_added_to_workout(client, session):
    workout = create_workout(session)
    exercise = Exercise(name="Supino inclinado", muscle_group="Peito", muscle_subgroup="Peitoral clavicular")
    session.add(exercise)
    session.commit()

    response = client.post(f"/workouts/{workout.id}/exercises", data={"exercise_id": exercise.id})

    assert response.status_code == 302
    workout_exercise = session.query(WorkoutExercise).one()
    assert workout_exercise.exercise_id == exercise.id
    assert workout_exercise.position == 1


def test_library_exercise_cannot_be_added_twice_to_same_workout(client, session):
    workout = create_workout(session)
    exercise = Exercise(name="Supino inclinado", muscle_group="Peito", muscle_subgroup="Peitoral clavicular")
    session.add(exercise)
    session.commit()

    client.post(f"/workouts/{workout.id}/exercises", data={"exercise_id": exercise.id})
    response = client.post(
        f"/workouts/{workout.id}/exercises", data={"exercise_id": exercise.id}, follow_redirects=True
    )

    assert "Este exercício já foi adicionado ao treino." in response.get_data(as_text=True)
    assert session.query(WorkoutExercise).count() == 1
