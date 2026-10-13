from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_workout(session, workout_date=date(2026, 10, 5), name="Treino A"):
    workout = Workout(date=workout_date, name=name)
    session.add(workout)
    session.commit()
    return workout


# Sessions are created only from templates (see test_workout_templates.py):
# the old empty-session form now leads to the template builder and the old
# create route no longer exists.


def test_old_new_workout_address_redirects_to_template_builder(client, session):
    response = client.get("/workouts/new")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/templates/new")
    assert session.query(Workout).count() == 0


def test_empty_session_can_no_longer_be_created(client, session):
    response = client.post("/workouts", data={"date": "2026-10-05", "name": "Push"})

    assert response.status_code == 405
    assert session.query(Workout).count() == 0


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


@pytest.mark.parametrize("name", ["", "   "])
def test_edit_rejects_empty_name_and_preserves_form_values(client, session, name):
    workout = create_workout(session)

    response = client.post(
        f"/workouts/{workout.id}/edit",
        data={"date": "2026-10-06", "name": name},
    )
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Informe uma data válida e um nome para o treino." in page
    assert 'value="2026-10-06"' in page
    session.expire_all()
    stored = session.get(Workout, workout.id)
    assert (stored.name, stored.date) == ("Treino A", date(2026, 10, 5))


@pytest.mark.parametrize("workout_date", ["", "not-a-date"])
def test_edit_rejects_invalid_date(client, session, workout_date):
    workout = create_workout(session)

    response = client.post(
        f"/workouts/{workout.id}/edit",
        data={"date": workout_date, "name": "Push"},
    )

    assert response.status_code == 200
    assert "Informe uma data válida e um nome para o treino." in response.get_data(as_text=True)
    session.expire_all()
    assert session.get(Workout, workout.id).date == date(2026, 10, 5)


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
