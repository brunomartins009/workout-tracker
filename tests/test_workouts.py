from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_workout(session, workout_date=date(2026, 10, 5), name="Treino A"):
    workout = Workout(date=workout_date, name=name)
    session.add(workout)
    session.commit()
    return workout


def test_list_workouts_is_empty(client):
    response = client.get("/workouts")

    assert response.status_code == 200
    assert b"Nenhum treino cadastrado." in response.data


def test_list_workouts_shows_registered_workouts(client, session):
    create_workout(session, name="Push")
    create_workout(session, name="Pull")

    response = client.get("/workouts")

    assert response.status_code == 200
    assert b"Push" in response.data
    assert b"Pull" in response.data


def test_list_workouts_orders_by_date_descending_then_id_descending(client, session):
    oldest = create_workout(session, date(2026, 10, 3), "Mais antigo")
    same_date_first = create_workout(session, date(2026, 10, 5), "Mesmo dia primeiro")
    same_date_second = create_workout(session, date(2026, 10, 5), "Mesmo dia segundo")
    newest = create_workout(session, date(2026, 10, 6), "Mais recente")

    response = client.get("/workouts")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert page.index(newest.name) < page.index(same_date_second.name)
    assert page.index(same_date_second.name) < page.index(same_date_first.name)
    assert page.index(same_date_first.name) < page.index(oldest.name)


def test_new_workout_form_is_displayed(client):
    response = client.get("/workouts/new")

    assert response.status_code == 200
    assert 'type="date"' in response.get_data(as_text=True)


def test_creates_workout(client, session):
    response = client.post("/workouts", data={"date": "2026-10-05", "name": "Push"})

    workout = session.query(Workout).one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/workouts")
    assert workout.date == date(2026, 10, 5)
    assert workout.name == "Push"


def test_creation_removes_surrounding_whitespace_from_name(client, session):
    response = client.post(
        "/workouts", data={"date": "2026-10-05", "name": "  Push  "}
    )

    assert response.status_code == 302
    assert session.query(Workout).one().name == "Push"


@pytest.mark.parametrize("name", ["", "   "])
def test_creation_rejects_empty_name_and_preserves_form_values(client, session, name):
    response = client.post("/workouts", data={"date": "2026-10-05", "name": name})
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Informe uma data válida e um nome para o treino." in page
    assert 'value="2026-10-05"' in page
    assert session.query(Workout).count() == 0


@pytest.mark.parametrize("workout_date", ["", "not-a-date"])
def test_creation_rejects_invalid_date(client, session, workout_date):
    response = client.post("/workouts", data={"date": workout_date, "name": "Push"})

    assert response.status_code == 200
    assert b"Informe uma data v\xc3\xa1lida e um nome para o treino." in response.data
    assert session.query(Workout).count() == 0


def test_allows_multiple_workouts_with_same_date_and_name(client, session):
    first_response = client.post("/workouts", data={"date": "2026-10-05", "name": "Push"})
    second_response = client.post("/workouts", data={"date": "2026-10-05", "name": "Push"})

    assert first_response.status_code == 302
    assert second_response.status_code == 302
    assert session.query(Workout).count() == 2


def test_edits_workout(client, session):
    workout = create_workout(session)

    response = client.post(
        f"/workouts/{workout.id}/edit",
        data={"date": "2026-10-06", "name": "Pull"},
    )

    updated_workout = session.get(Workout, workout.id)
    assert response.status_code == 302
    assert updated_workout.date == date(2026, 10, 6)
    assert updated_workout.name == "Pull"


def test_edit_normalizes_name(client, session):
    workout = create_workout(session)

    response = client.post(
        f"/workouts/{workout.id}/edit",
        data={"date": "2026-10-05", "name": "  Push  "},
    )

    assert response.status_code == 302
    assert session.get(Workout, workout.id).name == "Push"


def test_edit_rejects_empty_name_and_preserves_form_values(client, session):
    workout = create_workout(session)

    response = client.post(
        f"/workouts/{workout.id}/edit",
        data={"date": "2026-10-06", "name": "   "},
    )
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="2026-10-06"' in page
    assert session.get(Workout, workout.id).name == "Treino A"


def test_editing_nonexistent_workout_returns_404(client):
    response = client.get("/workouts/999/edit")

    assert response.status_code == 404


def test_updating_nonexistent_workout_returns_404(client):
    response = client.post(
        "/workouts/999/edit", data={"date": "2026-10-05", "name": "Push"}
    )

    assert response.status_code == 404


def test_deletes_workout(client, session):
    workout = create_workout(session)

    response = client.post(f"/workouts/{workout.id}/delete")

    assert response.status_code == 302
    assert session.get(Workout, workout.id) is None


def test_deleting_nonexistent_workout_returns_404(client):
    response = client.post("/workouts/999/delete")

    assert response.status_code == 404


def test_deleting_workout_cascades_to_related_records(client, session):
    workout = create_workout(session)
    exercise = Exercise(name="Supino reto")
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=1)
    workout_set = WorkoutSet(
        workout_exercise=workout_exercise,
        position=1,
        repetitions=10,
        weight_kg=Decimal("20.00"),
    )
    session.add_all([exercise, workout_exercise, workout_set])
    session.commit()

    workout_id = workout.id
    workout_exercise_id = workout_exercise.id
    workout_set_id = workout_set.id
    response = client.post(f"/workouts/{workout_id}/delete")

    session.expire_all()
    assert response.status_code == 302
    assert session.get(Workout, workout_id) is None
    assert session.get(WorkoutExercise, workout_exercise_id) is None
    assert session.get(WorkoutSet, workout_set_id) is None
