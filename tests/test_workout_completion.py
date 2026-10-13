"""Completing a workout session and keeping completed sessions read-only."""

from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


JSON_HEADERS = {"Accept": "application/json"}
COMPLETED_ERROR = "Este treino já foi concluído e não pode mais ser alterado."
REQUIREMENT_ERROR = "Registre pelo menos uma série em algum exercício antes de concluir o treino."


def create_workout(session, name="Push"):
    workout = Workout(date=date(2026, 10, 8), name=name)
    session.add(workout)
    session.commit()
    return workout


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def add_exercise(session, workout, exercise, position, sets=()):
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=position)
    session.add(workout_exercise)
    for set_position, (repetitions, weight_kg) in enumerate(sets, start=1):
        session.add(
            WorkoutSet(
                workout_exercise=workout_exercise,
                position=set_position,
                repetitions=repetitions,
                weight_kg=Decimal(weight_kg),
            )
        )
    session.commit()
    return workout_exercise


def stored_state(session, workout_id):
    """Everything a change to the session could touch, as stored."""
    session.expire_all()
    workout = session.get(Workout, workout_id)
    return {
        "workout": (workout.name, workout.date, workout.completed_at, workout.updated_at),
        "exercises": [
            (item.id, item.exercise_id, item.position) for item in workout.workout_exercises
        ],
        "sets": sorted(
            (set_.id, set_.workout_exercise_id, set_.position, set_.repetitions, set_.weight_kg)
            for item in workout.workout_exercises
            for set_ in item.sets
        ),
    }


@pytest.fixture
def completed(client, session):
    """A session completed through the route, plus a library exercise not used in it."""
    workout = create_workout(session)
    bench = create_exercise(session, "Supino")
    fly = create_exercise(session, "Crucifixo")
    row = create_exercise(session, "Remada")
    bench_item = add_exercise(session, workout, bench, 1, sets=[(10, "20"), (8, "22.5")])
    add_exercise(session, workout, fly, 2, sets=[(12, "10")])

    response = client.post(f"/workouts/{workout.id}/complete")
    assert response.status_code == 302
    # Pages then read the values as stored by the database (e.g. 22.5 -> 22.50).
    session.expire_all()

    return {
        "workout_id": workout.id,
        "bench_id": bench.id,
        "fly_id": fly.id,
        "row_id": row.id,
        "set_id": bench_item.sets[0].id,
    }


# Completion


def test_completing_workout_with_sets_marks_it_completed(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, create_exercise(session, "Supino"), 1, sets=[(10, "20")])

    response = client.post(f"/workouts/{workout.id}/complete", follow_redirects=True)

    assert response.status_code == 200
    assert response.request.path == f"/workouts/{workout.id}"
    assert "Treino concluído." in response.get_data(as_text=True)
    session.expire_all()
    assert session.get(Workout, workout.id).completed_at is not None


def test_completion_accepts_exercises_without_sets_if_one_exercise_has_sets(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, create_exercise(session, "Supino"), 1)
    add_exercise(session, workout, create_exercise(session, "Crucifixo"), 2, sets=[(12, "10")])
    add_exercise(session, workout, create_exercise(session, "Remada"), 3)

    client.post(f"/workouts/{workout.id}/complete")

    session.expire_all()
    assert session.get(Workout, workout.id).is_completed is True


def test_completion_requires_at_least_one_exercise(client, session):
    workout = create_workout(session)
    before = stored_state(session, workout.id)

    response = client.post(f"/workouts/{workout.id}/complete", follow_redirects=True)

    assert response.request.path == f"/workouts/{workout.id}"
    assert REQUIREMENT_ERROR in response.get_data(as_text=True)
    assert stored_state(session, workout.id) == before


def test_completion_requires_at_least_one_set(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, create_exercise(session, "Supino"), 1)
    add_exercise(session, workout, create_exercise(session, "Crucifixo"), 2)
    before = stored_state(session, workout.id)

    response = client.post(f"/workouts/{workout.id}/complete", follow_redirects=True)

    assert REQUIREMENT_ERROR in response.get_data(as_text=True)
    # The session stays in progress and untouched, so it can still be edited.
    assert stored_state(session, workout.id) == before
    assert before["workout"][2] is None


def test_completion_is_not_repeated_and_keeps_the_first_completion_time(client, session, completed):
    before = stored_state(session, completed["workout_id"])

    response = client.post(f"/workouts/{completed['workout_id']}/complete", follow_redirects=True)

    assert COMPLETED_ERROR in response.get_data(as_text=True)
    assert stored_state(session, completed["workout_id"]) == before


def test_completing_nonexistent_workout_returns_404(client):
    assert client.post("/workouts/999/complete").status_code == 404


def test_completing_one_workout_does_not_complete_another(client, session):
    workout = create_workout(session, "Push")
    other = create_workout(session, "Pull")
    supino = create_exercise(session, "Supino")
    add_exercise(session, workout, supino, 1, sets=[(10, "20")])
    add_exercise(session, other, supino, 1, sets=[(10, "20")])

    client.post(f"/workouts/{workout.id}/complete")

    session.expire_all()
    assert session.get(Workout, other.id).completed_at is None


# A completed session rejects every change made by calling the routes directly.


MUTATING_REQUESTS = {
    "edit form": ("get", "/workouts/{workout_id}/edit", None),
    "edit name and date": ("post", "/workouts/{workout_id}/edit", {"date": "2026-10-20", "name": "Outro nome"}),
    "add exercise": ("post", "/workouts/{workout_id}/exercises", {"exercise_id": "{row_id}"}),
    "remove exercise": ("post", "/workouts/{workout_id}/exercises/{bench_id}/delete", None),
    "move exercise up": ("post", "/workouts/{workout_id}/exercises/{fly_id}/move-up", None),
    "move exercise down": ("post", "/workouts/{workout_id}/exercises/{bench_id}/move-down", None),
    "add set": ("post", "/workouts/{workout_id}/exercises/{bench_id}/sets", {"repetitions": "5", "weight_kg": "30"}),
    "set edit form": ("get", "/workouts/{workout_id}/exercises/{bench_id}/sets/{set_id}/edit", None),
    "edit set": ("post", "/workouts/{workout_id}/exercises/{bench_id}/sets/{set_id}/edit", {"repetitions": "1", "weight_kg": "99"}),
    "delete set": ("post", "/workouts/{workout_id}/exercises/{bench_id}/sets/{set_id}/delete", None),
}


def send(client, completed, request_name, headers=None):
    method, url, data = MUTATING_REQUESTS[request_name]
    if data is not None:
        data = {key: value.format(**completed) for key, value in data.items()}
    return getattr(client, method)(url.format(**completed), data=data, headers=headers)


@pytest.mark.parametrize("request_name", MUTATING_REQUESTS)
def test_completed_workout_rejects_changes_from_forms(client, session, completed, request_name):
    before = stored_state(session, completed["workout_id"])

    response = send(client, completed, request_name)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/workouts/{completed['workout_id']}")
    assert stored_state(session, completed["workout_id"]) == before
    page = client.get(response.headers["Location"]).get_data(as_text=True)
    assert COMPLETED_ERROR in page


@pytest.mark.parametrize(
    "request_name",
    [name for name, (method, _, _) in MUTATING_REQUESTS.items() if method == "post"],
)
def test_completed_workout_rejects_changes_from_fetch(client, session, completed, request_name):
    before = stored_state(session, completed["workout_id"])

    response = send(client, completed, request_name, headers=JSON_HEADERS)

    assert response.status_code == 409
    assert response.get_json() == {"error": COMPLETED_ERROR}
    assert stored_state(session, completed["workout_id"]) == before


def test_in_progress_workout_still_accepts_changes(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, create_exercise(session, "Supino"), 1)

    response = client.post(
        f"/workouts/{workout.id}/edit", data={"date": "2026-10-20", "name": "Outro nome"}
    )

    assert response.status_code == 302
    session.expire_all()
    assert session.get(Workout, workout.id).name == "Outro nome"


def test_completed_workout_can_still_be_deleted(client, session, completed):
    response = client.post(f"/workouts/{completed['workout_id']}/delete")

    assert response.status_code == 302
    session.expire_all()
    assert session.get(Workout, completed["workout_id"]) is None
    assert session.query(WorkoutSet).count() == 0
    # Only the session is removed, never the library exercises.
    assert session.query(Exercise).count() == 3


def test_completed_workout_stays_in_exercise_history(client, session, completed):
    response = client.get(f"/exercises/{completed['bench_id']}/history")

    assert response.status_code == 200
    history = response.get_json()["history"]
    assert [(item["workout_id"], item["sets"], item["max_weight_kg"]) for item in history] == [
        (completed["workout_id"], 2, 22.5)
    ]


# Workout page


def test_in_progress_page_offers_completion_with_confirmation(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, create_exercise(session, "Supino"), 1, sets=[(10, "20")])

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "Em andamento" in page
    assert f'action="/workouts/{workout.id}/complete"' in page
    assert 'data-confirm-dialog="complete-workout-dialog"' in page
    assert 'id="complete-workout-dialog"' in page
    assert 'data-confirm-dialog="delete-workout-dialog"' in page
    assert 'id="delete-workout-dialog"' in page


def test_completed_page_is_read_only(client, session, completed):
    workout_id = completed["workout_id"]

    page = client.get(f"/workouts/{workout_id}").get_data(as_text=True)

    assert '<span class="status-badge status-badge-completed">Concluído</span>' in page
    assert "Treino concluído. Ele não pode mais ser alterado" in page
    # No control that changes the session is offered.
    for hidden in (
        f"/workouts/{workout_id}/complete",
        f"/workouts/{workout_id}/edit",
        f'action="/workouts/{workout_id}/exercises"',
        "/move-up",
        "/move-down",
        f"/exercises/{completed['bench_id']}/delete",
        "/sets/",
        'action="/workouts/{}/exercises/{}/sets"'.format(workout_id, completed["bench_id"]),
        'id="add-exercise"',
        "complete-workout-dialog",
        "Em andamento",
    ):
        assert hidden not in page, hidden
    # Sets, the exercise history and deletion are still available.
    assert "22.50 kg" in page
    assert f'data-history-url="/exercises/{completed["bench_id"]}/history"' in page
    assert f'action="/workouts/{workout_id}/delete"' in page
    assert 'id="delete-workout-dialog"' in page


def test_completed_page_without_exercises_shows_read_only_empty_state(client, session):
    # Sessions migrated as completed were not validated and may be empty.
    workout = create_workout(session)
    workout.completed_at = workout.updated_at
    session.commit()

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "Nenhum exercício registrado neste treino." in page
    assert "Escolha um exercício abaixo" not in page
