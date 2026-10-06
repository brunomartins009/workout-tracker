from datetime import date

from app.models import Exercise, Workout, WorkoutExercise


def create_workout(session, name="Treino A"):
    workout = Workout(date=date(2026, 10, 6), name=name)
    session.add(workout)
    session.commit()
    return workout


def create_exercise(session, name):
    exercise = Exercise(name=name)
    session.add(exercise)
    session.commit()
    return exercise


def add_exercise(session, workout, exercise, position):
    workout_exercise = WorkoutExercise(
        workout=workout,
        exercise=exercise,
        position=position,
    )
    session.add(workout_exercise)
    session.commit()
    return workout_exercise


def workout_exercises(session, workout):
    return (
        session.query(WorkoutExercise)
        .filter_by(workout_id=workout.id)
        .order_by(WorkoutExercise.position)
        .all()
    )


def test_detail_for_existing_workout_returns_200(client, session):
    workout = create_workout(session, "Push")

    response = client.get(f"/workouts/{workout.id}")

    assert response.status_code == 200
    assert b"Push" in response.data


def test_detail_for_nonexistent_workout_returns_404(client):
    response = client.get("/workouts/999")

    assert response.status_code == 404


def test_detail_shows_exercises_in_position_order(client, session):
    workout = create_workout(session)
    first = create_exercise(session, "Supino")
    second = create_exercise(session, "Crucifixo")
    add_exercise(session, workout, second, 2)
    add_exercise(session, workout, first, 1)

    response = client.get(f"/workouts/{workout.id}")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert page.index("Supino") < page.index("Crucifixo")


def test_detail_for_workout_without_exercises_shows_empty_state(client, session):
    workout = create_workout(session)

    response = client.get(f"/workouts/{workout.id}")

    assert response.status_code == 200
    assert b"Nenhum exerc\xc3\xadcio adicionado a este treino." in response.data


def test_adds_existing_exercise_at_next_position(client, session):
    workout = create_workout(session)
    first = create_exercise(session, "Supino")
    second = create_exercise(session, "Crucifixo")
    add_exercise(session, workout, first, 1)

    response = client.post(
        f"/workouts/{workout.id}/exercises", data={"exercise_id": second.id}
    )

    added = session.query(WorkoutExercise).filter_by(
        workout_id=workout.id, exercise_id=second.id
    ).one()
    assert response.status_code == 302
    assert added.position == 2


def test_adding_nonexistent_exercise_returns_404(client, session):
    workout = create_workout(session)

    response = client.post(f"/workouts/{workout.id}/exercises", data={"exercise_id": 999})

    assert response.status_code == 404


def test_adding_exercise_to_nonexistent_workout_returns_404(client, session):
    exercise = create_exercise(session, "Supino")

    response = client.post("/workouts/999/exercises", data={"exercise_id": exercise.id})

    assert response.status_code == 404


def test_prevents_duplicate_exercise_in_workout(client, session):
    workout = create_workout(session)
    exercise = create_exercise(session, "Supino")
    add_exercise(session, workout, exercise, 1)

    response = client.post(
        f"/workouts/{workout.id}/exercises",
        data={"exercise_id": exercise.id},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Este exerc\xc3\xadcio j\xc3\xa1 foi adicionado ao treino." in response.data
    assert len(workout_exercises(session, workout)) == 1


def test_adding_exercise_to_one_workout_does_not_change_another(client, session):
    workout_a = create_workout(session, "Treino A")
    workout_b = create_workout(session, "Treino B")
    exercise = create_exercise(session, "Supino")

    response = client.post(
        f"/workouts/{workout_a.id}/exercises", data={"exercise_id": exercise.id}
    )

    assert response.status_code == 302
    assert len(workout_exercises(session, workout_a)) == 1
    assert workout_exercises(session, workout_b) == []


def test_removes_workout_exercise_without_removing_exercise(client, session):
    workout = create_workout(session)
    exercise = create_exercise(session, "Supino")
    add_exercise(session, workout, exercise, 1)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{exercise.id}/delete"
    )

    assert response.status_code == 302
    assert workout_exercises(session, workout) == []
    assert session.get(Exercise, exercise.id) is not None


def test_removing_workout_exercise_reorganizes_positions(client, session):
    workout = create_workout(session)
    first = create_exercise(session, "Supino")
    second = create_exercise(session, "Crucifixo")
    third = create_exercise(session, "Desenvolvimento")
    add_exercise(session, workout, first, 1)
    add_exercise(session, workout, second, 2)
    add_exercise(session, workout, third, 3)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{second.id}/delete"
    )

    assert response.status_code == 302
    assert [(item.exercise_id, item.position) for item in workout_exercises(session, workout)] == [
        (first.id, 1),
        (third.id, 2),
    ]


def test_removing_exercise_from_one_workout_does_not_affect_another(client, session):
    workout_a = create_workout(session, "Treino A")
    workout_b = create_workout(session, "Treino B")
    exercise = create_exercise(session, "Supino")
    add_exercise(session, workout_a, exercise, 1)
    add_exercise(session, workout_b, exercise, 1)

    response = client.post(
        f"/workouts/{workout_a.id}/exercises/{exercise.id}/delete"
    )

    assert response.status_code == 302
    assert workout_exercises(session, workout_a) == []
    assert [(item.exercise_id, item.position) for item in workout_exercises(session, workout_b)] == [
        (exercise.id, 1)
    ]


def test_moving_exercise_up_swaps_positions(client, session):
    workout = create_workout(session)
    first = create_exercise(session, "Supino")
    second = create_exercise(session, "Crucifixo")
    add_exercise(session, workout, first, 1)
    add_exercise(session, workout, second, 2)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{second.id}/move-up"
    )

    assert response.status_code == 302
    assert [(item.exercise_id, item.position) for item in workout_exercises(session, workout)] == [
        (second.id, 1),
        (first.id, 2),
    ]


def test_moving_exercise_down_swaps_positions(client, session):
    workout = create_workout(session)
    first = create_exercise(session, "Supino")
    second = create_exercise(session, "Crucifixo")
    add_exercise(session, workout, first, 1)
    add_exercise(session, workout, second, 2)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{first.id}/move-down"
    )

    assert response.status_code == 302
    assert [(item.exercise_id, item.position) for item in workout_exercises(session, workout)] == [
        (second.id, 1),
        (first.id, 2),
    ]


def test_first_and_last_exercises_do_not_offer_invalid_move_actions(client, session):
    workout = create_workout(session)
    first = create_exercise(session, "Supino")
    last = create_exercise(session, "Crucifixo")
    add_exercise(session, workout, first, 1)
    add_exercise(session, workout, last, 2)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert f"/exercises/{first.id}/move-up" not in page
    assert f"/exercises/{last.id}/move-down" not in page


def test_reordering_one_workout_does_not_affect_another(client, session):
    workout_a = create_workout(session, "Treino A")
    workout_b = create_workout(session, "Treino B")
    first = create_exercise(session, "Supino")
    second = create_exercise(session, "Crucifixo")
    add_exercise(session, workout_a, first, 1)
    add_exercise(session, workout_a, second, 2)
    add_exercise(session, workout_b, first, 1)

    response = client.post(
        f"/workouts/{workout_a.id}/exercises/{second.id}/move-up"
    )

    assert response.status_code == 302
    assert [(item.exercise_id, item.position) for item in workout_exercises(session, workout_a)] == [
        (second.id, 1),
        (first.id, 2),
    ]
    assert [(item.exercise_id, item.position) for item in workout_exercises(session, workout_b)] == [
        (first.id, 1)
    ]
