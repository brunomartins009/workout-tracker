from datetime import date

import pytest

from app.models import Exercise, Workout, WorkoutExercise


def create_exercise(session, name="Supino reto"):
    exercise = Exercise(name=name)
    session.add(exercise)
    session.commit()
    return exercise


def test_list_exercises_is_empty(client):
    response = client.get("/exercises")

    assert response.status_code == 200
    assert b"Nenhum exerc\xc3\xadcio cadastrado." in response.data


def test_list_exercises_shows_registered_exercises(client, session):
    create_exercise(session, "Remada curvada")
    create_exercise(session, "Supino reto")

    response = client.get("/exercises")

    assert response.status_code == 200
    assert b"Remada curvada" in response.data
    assert b"Supino reto" in response.data


def test_new_exercise_form_is_displayed(client):
    response = client.get("/exercises/new")

    assert response.status_code == 200
    assert b"Nome do exerc\xc3\xadcio" in response.data


def test_creates_exercise(client, session):
    response = client.post("/exercises", data={"name": "Supino reto"})

    exercise = session.query(Exercise).one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/exercises")
    assert exercise.name == "Supino reto"


def test_creation_removes_surrounding_whitespace(client, session):
    response = client.post("/exercises", data={"name": "  Supino reto  "})

    assert response.status_code == 302
    assert session.query(Exercise).one().name == "Supino reto"


@pytest.mark.parametrize("name", ["", "   "])
def test_creation_rejects_empty_name(client, session, name):
    response = client.post("/exercises", data={"name": name})

    assert response.status_code == 200
    assert b"Informe um nome de exerc\xc3\xadcio." in response.data
    assert session.query(Exercise).count() == 0


@pytest.mark.parametrize("duplicate_name", ["supino inclinado", " SUPINO INCLINADO "])
def test_creation_rejects_case_insensitive_duplicate(client, session, duplicate_name):
    create_exercise(session, "Supino Inclinado")

    response = client.post("/exercises", data={"name": duplicate_name})

    assert response.status_code == 200
    assert b"J\xc3\xa1 existe um exerc\xc3\xadcio com esse nome." in response.data
    assert session.query(Exercise).count() == 1


def test_edits_exercise(client, session):
    exercise = create_exercise(session)

    response = client.post(f"/exercises/{exercise.id}/edit", data={"name": "Supino inclinado"})

    assert response.status_code == 302
    assert session.get(Exercise, exercise.id).name == "Supino inclinado"


def test_edit_normalizes_name(client, session):
    exercise = create_exercise(session)

    response = client.post(f"/exercises/{exercise.id}/edit", data={"name": "  Supino inclinado  "})

    assert response.status_code == 302
    assert session.get(Exercise, exercise.id).name == "Supino inclinado"


def test_editing_nonexistent_exercise_returns_404(client):
    response = client.get("/exercises/999/edit")

    assert response.status_code == 404


def test_updating_nonexistent_exercise_returns_404(client):
    response = client.post("/exercises/999/edit", data={"name": "Supino reto"})

    assert response.status_code == 404


def test_edit_rejects_duplicate_name(client, session):
    existing_exercise = create_exercise(session, "Supino reto")
    exercise = create_exercise(session, "Remada curvada")

    response = client.post(f"/exercises/{exercise.id}/edit", data={"name": " SUPINO RETO "})

    assert response.status_code == 200
    assert b"J\xc3\xa1 existe um exerc\xc3\xadcio com esse nome." in response.data
    assert session.get(Exercise, existing_exercise.id).name == "Supino reto"
    assert session.get(Exercise, exercise.id).name == "Remada curvada"


def test_deletes_unused_exercise(client, session):
    exercise = create_exercise(session)

    response = client.post(f"/exercises/{exercise.id}/delete")

    assert response.status_code == 302
    assert session.get(Exercise, exercise.id) is None


def test_delete_exercise_with_history_shows_message(client, session):
    exercise = create_exercise(session)
    workout = Workout(date=date(2026, 10, 2), name="Treino A")
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=1)
    session.add_all([workout, workout_exercise])
    session.commit()

    response = client.post(f"/exercises/{exercise.id}/delete", follow_redirects=True)

    assert response.status_code == 200
    assert b"n\xc3\xa3o pode ser exclu\xc3\xaddo porque possui hist\xc3\xb3rico de treino" in response.data
    assert session.get(Exercise, exercise.id) is not None


def test_deleting_nonexistent_exercise_returns_404(client):
    response = client.post("/exercises/999/delete")

    assert response.status_code == 404
