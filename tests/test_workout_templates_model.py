from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet, WorkoutTemplate, WorkoutTemplateExercise


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def create_template(session, name="Push", exercises=()):
    template = WorkoutTemplate(name=name)
    for position, exercise in enumerate(exercises, start=1):
        template.template_exercises.append(WorkoutTemplateExercise(exercise=exercise, position=position))
    session.add(template)
    session.commit()
    return template


# WorkoutTemplate


def test_template_name_is_trimmed(session):
    template = create_template(session, "  Push  ")

    assert template.id is not None
    assert template.name == "Push"


@pytest.mark.parametrize("name", ["", "   "])
def test_template_name_is_required(name):
    with pytest.raises(ValueError, match="name cannot be empty"):
        WorkoutTemplate(name=name)


def test_template_name_is_unique_case_insensitively(session):
    create_template(session, "Push")
    session.add(WorkoutTemplate(name=" PUSH "))

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_template_keeps_exercises_in_position_order(session):
    bench = create_exercise(session, "Supino")
    fly = create_exercise(session, "Crucifixo")
    raise_ = create_exercise(session, "Elevação lateral")
    template = WorkoutTemplate(name="Push")
    session.add_all(
        [
            template,
            WorkoutTemplateExercise(template=template, exercise=raise_, position=3),
            WorkoutTemplateExercise(template=template, exercise=bench, position=1),
            WorkoutTemplateExercise(template=template, exercise=fly, position=2),
        ]
    )
    session.commit()
    session.expire_all()

    stored = session.get(WorkoutTemplate, template.id)
    assert [item.exercise.name for item in stored.template_exercises] == ["Supino", "Crucifixo", "Elevação lateral"]


def test_template_rejects_duplicate_exercise(session):
    bench = create_exercise(session, "Supino")
    template = create_template(session, "Push", [bench])
    session.add(WorkoutTemplateExercise(template=template, exercise=bench, position=2))

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_template_rejects_duplicate_position(session):
    bench = create_exercise(session, "Supino")
    fly = create_exercise(session, "Crucifixo")
    template = create_template(session, "Push", [bench])
    session.add(WorkoutTemplateExercise(template=template, exercise=fly, position=1))

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("position", [0, -1])
def test_template_exercise_position_must_be_positive(position):
    with pytest.raises(ValueError, match="position must be a positive integer"):
        WorkoutTemplateExercise(position=position)


def test_deleting_template_removes_only_its_items(session):
    bench = create_exercise(session, "Supino")
    template = create_template(session, "Push", [bench])
    other = create_template(session, "Upper", [bench])

    session.delete(template)
    session.commit()

    assert session.query(WorkoutTemplateExercise).count() == 1
    assert session.get(WorkoutTemplate, other.id) is not None
    assert session.get(Exercise, bench.id) is not None


def test_exercise_used_by_template_cannot_be_deleted(session):
    bench = create_exercise(session, "Supino")
    create_template(session, "Push", [bench])

    session.delete(bench)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_template_and_session_are_independent(session):
    bench = create_exercise(session, "Supino")
    template = create_template(session, "Push", [bench])
    workout = Workout(date=date(2026, 10, 9), name="Push")
    workout_exercise = WorkoutExercise(workout=workout, exercise=bench, position=1)
    session.add_all(
        [
            workout,
            workout_exercise,
            WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=10, weight_kg=Decimal("20")),
        ]
    )
    session.commit()

    # Deleting the session keeps the template and the library exercise.
    session.delete(workout)
    session.commit()
    assert session.get(WorkoutTemplate, template.id) is not None
    assert session.get(Exercise, bench.id) is not None

    # Deleting the template keeps other sessions untouched.
    other_workout = Workout(date=date(2026, 10, 10), name="Push")
    session.add_all([other_workout, WorkoutExercise(workout=other_workout, exercise=bench, position=1)])
    session.commit()
    session.delete(template)
    session.commit()
    assert session.get(Workout, other_workout.id).name == "Push"
    assert session.query(WorkoutExercise).filter_by(workout_id=other_workout.id).count() == 1


# Workout completion state


def test_new_workout_starts_in_progress(session):
    workout = Workout(date=date(2026, 10, 9), name="Push")
    session.add(workout)
    session.commit()

    assert workout.completed_at is None
    assert workout.is_completed is False


def test_completed_workout_keeps_completion_time(session):
    completed_at = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
    workout = Workout(date=date(2026, 10, 9), name="Push", completed_at=completed_at)
    session.add(workout)
    session.commit()
    session.expire_all()

    stored = session.get(Workout, workout.id)
    assert stored.is_completed is True
    assert stored.completed_at.replace(tzinfo=timezone.utc) == completed_at
