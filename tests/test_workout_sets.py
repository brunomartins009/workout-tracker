from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_workout(session, name="Treino A"):
    workout = Workout(date=date(2026, 10, 6), name=name)
    session.add(workout)
    session.commit()
    return workout


def create_workout_exercise(session, workout, name="Supino"):
    exercise = Exercise(name=name)
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=1)
    session.add_all([exercise, workout_exercise])
    session.commit()
    return exercise, workout_exercise


def create_set(session, workout_exercise, position, repetitions=10, weight_kg="20.00"):
    workout_set = WorkoutSet(
        workout_exercise=workout_exercise,
        position=position,
        repetitions=repetitions,
        weight_kg=Decimal(weight_kg),
    )
    session.add(workout_set)
    session.commit()
    return workout_set


def ordered_sets(session, workout_exercise):
    return (
        session.query(WorkoutSet)
        .filter_by(workout_exercise_id=workout_exercise.id)
        .order_by(WorkoutSet.position)
        .all()
    )


def test_detail_displays_sets_in_position_order(client, session):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)
    create_set(session, workout_exercise, 2, repetitions=8, weight_kg="22.00")
    create_set(session, workout_exercise, 1, repetitions=10, weight_kg="20.00")

    response = client.get(f"/workouts/{workout.id}")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert page.index("Série 1: 10 reps, 20.00 kg") < page.index(
        "Série 2: 8 reps, 22.00 kg"
    )
    assert exercise.name in page


def test_detail_shows_empty_state_for_exercise_without_sets(client, session):
    workout = create_workout(session)
    _, workout_exercise = create_workout_exercise(session, workout)

    response = client.get(f"/workouts/{workout.id}")

    assert response.status_code == 200
    assert b"Nenhuma s\xc3\xa9rie registrada." in response.data
    assert f"repetitions-{workout_exercise.id}".encode() in response.data


def test_detail_for_nonexistent_workout_returns_404(client):
    response = client.get("/workouts/999")

    assert response.status_code == 404


def test_adds_first_set_at_position_one(client, session):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets",
        data={"repetitions": "12", "weight_kg": "20"},
    )

    workout_set = ordered_sets(session, workout_exercise)[0]
    assert response.status_code == 302
    assert workout_set.position == 1
    assert workout_set.repetitions == 12
    assert workout_set.weight_kg == Decimal("20.00")


@pytest.mark.parametrize(
    ("repetitions", "weight_kg"),
    [("10", "0"), ("8", "22.50")],
)
def test_adds_valid_set_weights(client, session, repetitions, weight_kg):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets",
        data={"repetitions": repetitions, "weight_kg": weight_kg},
    )

    workout_set = ordered_sets(session, workout_exercise)[0]
    assert response.status_code == 302
    assert workout_set.weight_kg == Decimal(weight_kg).quantize(Decimal("0.01"))


def test_new_sets_receive_sequential_positions(client, session):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)
    create_set(session, workout_exercise, 1)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets",
        data={"repetitions": "8", "weight_kg": "22.50"},
    )

    assert response.status_code == 302
    assert [workout_set.position for workout_set in ordered_sets(session, workout_exercise)] == [1, 2]


@pytest.mark.parametrize(
    ("repetitions", "weight_kg"),
    [("0", "20"), ("-1", "20"), ("10", "-0.01"), ("10", "20.123")],
)
def test_rejects_invalid_set_values(client, session, repetitions, weight_kg):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets",
        data={"repetitions": repetitions, "weight_kg": weight_kg},
    )

    assert response.status_code == 200
    assert b"Informe repeti\xc3\xa7\xc3\xb5es positivas" in response.data
    assert ordered_sets(session, workout_exercise) == []


def test_adding_set_to_nonexistent_exercise_or_relation_returns_404(client, session):
    workout = create_workout(session)
    another_workout = create_workout(session, "Treino B")
    exercise, _ = create_workout_exercise(session, another_workout)

    nonexistent_exercise_response = client.post(
        f"/workouts/{workout.id}/exercises/999/sets",
        data={"repetitions": "10", "weight_kg": "20"},
    )
    unrelated_exercise_response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets",
        data={"repetitions": "10", "weight_kg": "20"},
    )

    assert nonexistent_exercise_response.status_code == 404
    assert unrelated_exercise_response.status_code == 404


def test_editing_set_updates_repetitions_and_weight(client, session):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)
    workout_set = create_set(session, workout_exercise, 1)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets/{workout_set.id}/edit",
        data={"repetitions": "12", "weight_kg": "25.50"},
    )

    updated_set = session.get(WorkoutSet, workout_set.id)
    assert response.status_code == 302
    assert updated_set.repetitions == 12
    assert updated_set.weight_kg == Decimal("25.50")


def test_invalid_set_edit_does_not_persist_changes(client, session):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)
    workout_set = create_set(session, workout_exercise, 1)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets/{workout_set.id}/edit",
        data={"repetitions": "0", "weight_kg": "30"},
    )

    unchanged_set = session.get(WorkoutSet, workout_set.id)
    assert response.status_code == 200
    assert unchanged_set.repetitions == 10
    assert unchanged_set.weight_kg == Decimal("20.00")


def test_nonexistent_or_unrelated_set_returns_404(client, session):
    workout = create_workout(session)
    first_exercise, first_workout_exercise = create_workout_exercise(session, workout, "Supino")
    second_exercise = Exercise(name="Crucifixo")
    second_workout_exercise = WorkoutExercise(
        workout=workout,
        exercise=second_exercise,
        position=2,
    )
    session.add_all([second_exercise, second_workout_exercise])
    session.commit()
    second_set = create_set(session, second_workout_exercise, 1)

    nonexistent_response = client.get(
        f"/workouts/{workout.id}/exercises/{first_exercise.id}/sets/999/edit"
    )
    unrelated_response = client.get(
        f"/workouts/{workout.id}/exercises/{first_exercise.id}/sets/{second_set.id}/edit"
    )

    assert nonexistent_response.status_code == 404
    assert unrelated_response.status_code == 404
    assert first_workout_exercise.id != second_workout_exercise.id


def test_deleting_set_reorganizes_positions_without_affecting_other_sets(client, session):
    workout = create_workout(session)
    exercise, workout_exercise = create_workout_exercise(session, workout)
    first_set = create_set(session, workout_exercise, 1)
    second_set = create_set(session, workout_exercise, 2)
    third_set = create_set(session, workout_exercise, 3)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/sets/{second_set.id}/delete"
    )

    assert response.status_code == 302
    assert session.get(WorkoutSet, second_set.id) is None
    assert [(item.id, item.position) for item in ordered_sets(session, workout_exercise)] == [
        (first_set.id, 1),
        (third_set.id, 2),
    ]


def test_deleting_unrelated_or_nonexistent_set_returns_404(client, session):
    workout = create_workout(session)
    first_exercise, first_workout_exercise = create_workout_exercise(session, workout, "Supino")
    second_exercise = Exercise(name="Crucifixo")
    second_workout_exercise = WorkoutExercise(
        workout=workout,
        exercise=second_exercise,
        position=2,
    )
    session.add_all([second_exercise, second_workout_exercise])
    session.commit()
    second_set = create_set(session, second_workout_exercise, 1)

    nonexistent_response = client.post(
        f"/workouts/{workout.id}/exercises/{first_exercise.id}/sets/999/delete"
    )
    unrelated_response = client.post(
        f"/workouts/{workout.id}/exercises/{first_exercise.id}/sets/{second_set.id}/delete"
    )

    assert nonexistent_response.status_code == 404
    assert unrelated_response.status_code == 404
    assert session.get(WorkoutSet, second_set.id) is not None
    assert first_workout_exercise.id != second_workout_exercise.id


def test_set_operations_do_not_affect_another_workout_exercise(client, session):
    workout_a = create_workout(session, "Treino A")
    workout_b = create_workout(session, "Treino B")
    exercise_a, workout_exercise_a = create_workout_exercise(session, workout_a, "Supino")
    _, workout_exercise_b = create_workout_exercise(session, workout_b, "Crucifixo")
    set_a = create_set(session, workout_exercise_a, 1, repetitions=10, weight_kg="20.00")
    set_b = create_set(session, workout_exercise_b, 1, repetitions=8, weight_kg="15.00")

    response = client.post(
        f"/workouts/{workout_a.id}/exercises/{exercise_a.id}/sets/{set_a.id}/delete"
    )

    assert response.status_code == 302
    assert session.get(WorkoutSet, set_a.id) is None
    preserved_set = session.get(WorkoutSet, set_b.id)
    assert preserved_set.repetitions == 8
    assert preserved_set.weight_kg == Decimal("15.00")
