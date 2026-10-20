"""Targets of sets and repetitions per exercise, and their copy into sessions."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import (
    TARGET_REPETITIONS_MAX,
    TARGET_SETS_MAX,
    Exercise,
    Workout,
    WorkoutExercise,
    WorkoutSet,
    WorkoutTemplate,
    WorkoutTemplateExercise,
)


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def create_template(session, name, items):
    """items: [(exercise, target_sets, target_repetitions), ...] in order."""
    template = WorkoutTemplate(name=name)
    for position, (exercise, target_sets, target_repetitions) in enumerate(items, start=1):
        template.template_exercises.append(
            WorkoutTemplateExercise(
                exercise=exercise,
                position=position,
                target_sets=target_sets,
                target_repetitions=target_repetitions,
            )
        )
    session.add(template)
    session.commit()
    return template


def session_targets(session, workout_id):
    session.expire_all()
    items = sorted(session.get(Workout, workout_id).workout_exercises, key=lambda item: item.position)
    return [(item.exercise.name, item.position, item.target_sets, item.target_repetitions) for item in items]


def template_targets(session, template_id):
    session.expire_all()
    template = session.get(WorkoutTemplate, template_id)
    return [
        (item.exercise.name, item.position, item.target_sets, item.target_repetitions)
        for item in template.template_exercises
    ]


@pytest.fixture
def exercises(session):
    return [create_exercise(session, name) for name in ("Supino inclinado", "Crucifixo", "Elevação lateral")]


# Model rules


@pytest.mark.parametrize("model", [WorkoutTemplateExercise, WorkoutExercise])
def test_targets_are_optional(model):
    item = model(position=1)

    assert item.target_sets is None
    assert item.target_repetitions is None


@pytest.mark.parametrize("model", [WorkoutTemplateExercise, WorkoutExercise])
@pytest.mark.parametrize(
    ("target_sets", "target_repetitions"),
    [(1, 1), (4, 10), (TARGET_SETS_MAX, TARGET_REPETITIONS_MAX), (None, None)],
)
def test_targets_within_range_are_accepted(model, target_sets, target_repetitions):
    item = model(position=1, target_sets=target_sets, target_repetitions=target_repetitions)

    assert (item.target_sets, item.target_repetitions) == (target_sets, target_repetitions)


@pytest.mark.parametrize("model", [WorkoutTemplateExercise, WorkoutExercise])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_sets", 0),
        ("target_sets", -1),
        ("target_sets", TARGET_SETS_MAX + 1),
        ("target_sets", True),
        ("target_sets", "4"),
        ("target_sets", 2.5),
        ("target_repetitions", 0),
        ("target_repetitions", TARGET_REPETITIONS_MAX + 1),
        ("target_repetitions", False),
        ("target_repetitions", "10"),
    ],
)
def test_targets_out_of_range_or_not_whole_numbers_are_rejected(model, field, value):
    with pytest.raises(ValueError, match=f"{field} must be a whole number from 1 to"):
        model(position=1, **{field: value})


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("workout_template_exercises", "target_sets", 0),
        ("workout_template_exercises", "target_sets", TARGET_SETS_MAX + 1),
        ("workout_template_exercises", "target_repetitions", TARGET_REPETITIONS_MAX + 1),
        ("workout_exercises", "target_sets", 0),
        ("workout_exercises", "target_repetitions", 0),
        ("workout_exercises", "target_repetitions", TARGET_REPETITIONS_MAX + 1),
    ],
)
def test_database_rejects_targets_out_of_range(session, exercises, table, column, value):
    # Bypasses the model validation: the CHECK constraint is the final guard.
    template = create_template(session, "Push", [(exercises[0], 4, 10)])
    workout = Workout(date=date(2026, 10, 8), name="Push")
    session.add_all([workout, WorkoutExercise(workout=workout, exercise=exercises[0], position=1)])
    session.commit()

    with pytest.raises(IntegrityError, match=f"ck_.*_{column}_range"):
        session.execute(text(f"UPDATE {table} SET {column} = :value"), {"value": value})
    session.rollback()

    # NULL (no target) is always accepted.
    session.execute(text(f"UPDATE {table} SET {column} = NULL"))
    session.commit()
    assert template_targets(session, template.id)[0][0] == "Supino inclinado"


# Sets and repetitions go together


def item_of(session, model, exercise, target_sets, target_repetitions):
    """A template exercise or a session exercise, added to the session in a new template or session."""
    item = model(exercise=exercise, position=1, target_sets=target_sets, target_repetitions=target_repetitions)
    if model is WorkoutTemplateExercise:
        parent = WorkoutTemplate(name="Push")
        parent.template_exercises.append(item)
    else:
        parent = Workout(date=date(2026, 10, 8), name="Push")
        parent.workout_exercises.append(item)
    session.add(parent)
    return item


def stored_pairs(session, model):
    session.expire_all()
    return [(item.target_sets, item.target_repetitions) for item in session.query(model).all()]


@pytest.mark.parametrize("model", [WorkoutTemplateExercise, WorkoutExercise])
@pytest.mark.parametrize(("target_sets", "target_repetitions"), [(None, None), (4, 10), (1, 1)])
def test_targets_set_together_or_not_at_all_are_saved(session, exercises, model, target_sets, target_repetitions):
    item_of(session, model, exercises[0], target_sets, target_repetitions)
    session.commit()

    assert stored_pairs(session, model) == [(target_sets, target_repetitions)]


@pytest.mark.parametrize("model", [WorkoutTemplateExercise, WorkoutExercise])
@pytest.mark.parametrize(("target_sets", "target_repetitions"), [(4, None), (None, 10)])
def test_only_one_target_is_never_saved(session, exercises, model, target_sets, target_repetitions):
    item_of(session, model, exercises[0], target_sets, target_repetitions)

    with pytest.raises(ValueError, match="target_sets and target_repetitions must be set together"):
        session.commit()
    session.rollback()

    assert stored_pairs(session, model) == []


@pytest.mark.parametrize("model", [WorkoutTemplateExercise, WorkoutExercise])
@pytest.mark.parametrize("cleared", ["target_sets", "target_repetitions"])
def test_clearing_only_one_target_of_a_saved_item_is_refused(session, exercises, model, cleared):
    item = item_of(session, model, exercises[0], 4, 10)
    session.commit()

    setattr(item, cleared, None)
    with pytest.raises(ValueError, match="must be set together"):
        session.commit()
    session.rollback()

    assert stored_pairs(session, model) == [(4, 10)]
    # Both together are still accepted.
    item.target_sets = None
    item.target_repetitions = None
    session.commit()
    assert stored_pairs(session, model) == [(None, None)]


@pytest.mark.parametrize(("table", "model"), [("workout_template_exercises", WorkoutTemplateExercise), ("workout_exercises", WorkoutExercise)])
def test_rows_saved_before_the_rule_can_still_change_other_fields(session, exercises, table, model):
    # A row with only one target, written without the model (as before the rule).
    item = item_of(session, model, exercises[0], 4, 10)
    session.commit()
    session.execute(text(f"UPDATE {table} SET target_repetitions = NULL"))
    session.commit()
    session.expire_all()

    item = session.query(model).one()
    item.position = 2
    session.commit()

    session.expire_all()
    assert (item.position, item.target_sets, item.target_repetitions) == (2, 4, None)


def test_template_with_only_one_target_is_not_started_and_can_be_fixed(client, session, exercises):
    bench, fly, _ = exercises
    template = create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12)])
    # Only the builder writes templates, and it always sends both targets; a
    # template changed outside it could still have only one.
    session.execute(
        text("UPDATE workout_template_exercises SET target_repetitions = NULL WHERE exercise_id = :id"),
        {"id": fly.id},
    )
    session.commit()
    session.expire_all()

    response = client.post(f"/templates/{template.id}/start")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/templates/{template.id}")
    page = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Este modelo tem metas incompletas. Edite o modelo e informe as séries e as repetições de cada exercício." in page
    assert session.query(Workout).count() == 0

    # Editing the template with both targets fixes it.
    assert client.get(f"/templates/{template.id}/edit").status_code == 200
    client.post(
        f"/templates/{template.id}/edit",
        data={
            "name": "Push",
            "exercise_ids": [str(bench.id), str(fly.id)],
            "target_sets": ["4", "3"],
            "target_repetitions": ["10", "12"],
        },
    )
    started = client.post(f"/templates/{template.id}/start")

    assert "/workouts/" in started.headers["Location"]
    workout = session.query(Workout).one()
    assert session_targets(session, workout.id) == [("Supino inclinado", 1, 4, 10), ("Crucifixo", 2, 3, 12)]


# Copy into the session


def test_starting_copies_targets_in_template_order(client, session, exercises):
    bench, fly, raise_ = exercises
    template = create_template(session, "Push", [(raise_, 3, 15), (bench, 4, 10), (fly, 3, 12)])

    client.post(f"/templates/{template.id}/start")

    workout = session.query(Workout).one()
    assert session_targets(session, workout.id) == [
        ("Elevação lateral", 1, 3, 15),
        ("Supino inclinado", 2, 4, 10),
        ("Crucifixo", 3, 3, 12),
    ]
    # The session starts without sets.
    assert session.query(WorkoutSet).count() == 0


def test_template_exercises_without_targets_start_without_targets(client, session, exercises):
    # A template created before targets existed (or partly without them).
    bench, fly, _ = exercises
    template = create_template(session, "Antigo", [(bench, None, None), (fly, 3, 12)])

    response = client.post(f"/templates/{template.id}/start", follow_redirects=True)

    workout = session.query(Workout).one()
    assert response.status_code == 200
    assert session_targets(session, workout.id) == [
        ("Supino inclinado", 1, None, None),
        ("Crucifixo", 2, 3, 12),
    ]


def test_changing_the_template_later_does_not_change_started_sessions(client, session, exercises):
    bench, fly, raise_ = exercises
    template = create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12)])
    client.post(f"/templates/{template.id}/start")
    workout = session.query(Workout).one()
    before = session_targets(session, workout.id)

    # Template changed afterwards: targets, order and exercises.
    stored = session.get(WorkoutTemplate, template.id)
    stored.template_exercises[0].target_sets = 5
    stored.template_exercises[0].target_repetitions = 8
    # Targets are removed together: only one of them cannot be saved.
    stored.template_exercises[1].target_sets = None
    stored.template_exercises[1].target_repetitions = None
    stored.template_exercises.append(WorkoutTemplateExercise(exercise=raise_, position=3, target_sets=2, target_repetitions=20))
    session.commit()

    assert session_targets(session, workout.id) == before


def test_changing_session_targets_does_not_change_the_template(client, session, exercises):
    bench, _, _ = exercises
    template = create_template(session, "Push", [(bench, 4, 10)])
    client.post(f"/templates/{template.id}/start")
    workout = session.query(Workout).one()

    item = session.get(Workout, workout.id).workout_exercises[0]
    item.target_sets = 2
    item.target_repetitions = 5
    session.commit()

    assert template_targets(session, template.id) == [("Supino inclinado", 1, 4, 10)]


def test_each_session_gets_its_own_copy(client, session, exercises):
    template = create_template(session, "Push", [(exercises[0], 4, 10)])
    client.post(f"/templates/{template.id}/start")
    client.post(f"/templates/{template.id}/start")
    first, second = session.query(Workout).order_by(Workout.id).all()

    session.get(Workout, first.id).workout_exercises[0].target_sets = 1
    session.commit()

    assert session_targets(session, second.id) == [("Supino inclinado", 1, 4, 10)]


def test_deleting_the_template_keeps_session_targets(client, session, exercises):
    template = create_template(session, "Push", [(exercises[0], 4, 10)])
    client.post(f"/templates/{template.id}/start")
    workout = session.query(Workout).one()

    client.post(f"/templates/{template.id}/delete")

    assert session_targets(session, workout.id) == [("Supino inclinado", 1, 4, 10)]


def test_session_can_be_completed_without_reaching_its_targets(client, session, exercises):
    bench, fly, _ = exercises
    template = create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12)])
    client.post(f"/templates/{template.id}/start")
    workout = session.query(Workout).one()

    # One set of one exercise, below the target repetitions.
    client.post(f"/workouts/{workout.id}/exercises/{bench.id}/sets", data={"repetitions": "6", "weight_kg": "20"})
    client.post(f"/workouts/{workout.id}/complete")

    session.expire_all()
    assert session.get(Workout, workout.id).is_completed
    assert [(s.repetitions, s.weight_kg) for s in session.query(WorkoutSet).all()] == [(6, Decimal("20.00"))]


def test_exercise_added_to_a_session_by_hand_has_no_targets(client, session, exercises):
    bench, fly, _ = exercises
    template = create_template(session, "Push", [(bench, 4, 10)])
    client.post(f"/templates/{template.id}/start")
    workout = session.query(Workout).one()

    client.post(f"/workouts/{workout.id}/exercises", data={"exercise_id": fly.id})

    assert session_targets(session, workout.id) == [
        ("Supino inclinado", 1, 4, 10),
        ("Crucifixo", 2, None, None),
    ]
