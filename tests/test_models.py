from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_workout(session, name="Treino A"):
    workout = Workout(date=date(2026, 9, 30), name=name)
    session.add(workout)
    session.commit()
    return workout


def create_exercise(session, name="Supino reto"):
    exercise = Exercise(name=name)
    session.add(exercise)
    session.commit()
    return exercise


def create_workout_exercise(session, workout, exercise, position=1):
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=position)
    session.add(workout_exercise)
    session.commit()
    return workout_exercise


def test_creates_workout(session):
    workout = create_workout(session, "  Treino A  ")
    assert workout.id is not None
    assert workout.name == "Treino A"
    assert workout.date == date(2026, 9, 30)
    assert workout.created_at is not None
    assert workout.updated_at is not None


def test_creates_exercise_and_normalizes_its_name(session):
    exercise = create_exercise(session, "  Supino reto  ")
    assert exercise.id is not None
    assert exercise.name == "Supino reto"


def test_exercise_name_is_unique_case_insensitively(session):
    create_exercise(session, "Supino reto")
    session.add(Exercise(name=" supino reto "))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_creates_workout_exercise_and_set_relationships(session):
    workout = create_workout(session)
    exercise = create_exercise(session)
    workout_exercise = create_workout_exercise(session, workout, exercise)
    workout_set = WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=10, weight_kg=Decimal("22.50"))
    session.add(workout_set)
    session.commit()
    assert workout.workout_exercises == [workout_exercise]
    assert exercise.workout_exercises == [workout_exercise]
    assert workout_exercise.workout is workout
    assert workout_exercise.exercise is exercise
    assert workout_exercise.sets == [workout_set]
    assert workout_set.workout_exercise is workout_exercise
    assert workout_set.weight_kg == Decimal("22.50")


def test_rejects_duplicate_exercise_in_same_workout(session):
    workout = create_workout(session)
    exercise = create_exercise(session)
    create_workout_exercise(session, workout, exercise, position=1)
    session.add(WorkoutExercise(workout=workout, exercise=exercise, position=2))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_rejects_duplicate_exercise_position_in_same_workout(session):
    workout = create_workout(session)
    first_exercise = create_exercise(session, "Supino reto")
    second_exercise = create_exercise(session, "Remada curvada")
    create_workout_exercise(session, workout, first_exercise, position=1)
    session.add(WorkoutExercise(workout=workout, exercise=second_exercise, position=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_rejects_duplicate_set_position(session):
    workout = create_workout(session)
    exercise = create_exercise(session)
    workout_exercise = create_workout_exercise(session, workout, exercise)
    session.add_all([
        WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=10, weight_kg=Decimal("20.00")),
        WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=8, weight_kg=Decimal("22.50")),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("value", [0, -1])
def test_rejects_invalid_workout_exercise_position(value):
    with pytest.raises(ValueError):
        WorkoutExercise(position=value)


@pytest.mark.parametrize(("field", "value"), [
    ("position", 0), ("position", -1), ("repetitions", 0), ("repetitions", -1),
    ("weight_kg", Decimal("-0.01")), ("weight_kg", Decimal("12.345")),
])
def test_rejects_invalid_workout_set_values(field, value):
    with pytest.raises(ValueError):
        WorkoutSet(**{field: value})


def test_deleting_workout_cascades_to_workout_exercises_and_sets(session):
    workout = create_workout(session)
    exercise = create_exercise(session)
    workout_exercise = create_workout_exercise(session, workout, exercise)
    workout_set = WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=10, weight_kg=Decimal("20.00"))
    session.add(workout_set)
    session.commit()
    workout_id = workout.id
    workout_exercise_id = workout_exercise.id
    workout_set_id = workout_set.id
    exercise_id = exercise.id
    session.delete(workout)
    session.commit()
    session.expire_all()
    assert session.get(Workout, workout_id) is None
    assert session.get(WorkoutExercise, workout_exercise_id) is None
    assert session.get(WorkoutSet, workout_set_id) is None
    assert session.get(Exercise, exercise_id) is not None


def test_deleting_exercise_with_history_is_restricted(session):
    workout = create_workout(session)
    exercise = create_exercise(session)
    create_workout_exercise(session, workout, exercise)
    session.delete(exercise)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
