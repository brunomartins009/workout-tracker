from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_workout(session, name="Treino A"):
    workout = Workout(date=date(2026, 10, 6), name=name)
    session.add(workout)
    session.commit()
    return workout


def add_exercise(session, workout, name, position):
    exercise = Exercise(name=name)
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=position)
    session.add_all([exercise, workout_exercise])
    session.commit()
    return exercise, workout_exercise


@pytest.mark.parametrize(
    ("url", "current_link"),
    [
        ("/workouts", 'href="/workouts" aria-current="page">Treinos</a>'),
        ("/workouts/new", 'href="/workouts" aria-current="page">Treinos</a>'),
        ("/exercises", 'href="/exercises" aria-current="page">Exercícios</a>'),
    ],
)
def test_navigation_links_to_both_areas_and_marks_current_area(client, url, current_link):
    page = client.get(url).get_data(as_text=True)

    assert 'aria-label="Navegação principal"' in page
    assert 'href="/workouts"' in page
    assert 'href="/exercises"' in page
    assert current_link in page
    assert page.count('aria-current="page"') == 1


def test_workout_list_shows_primary_action(client):
    workouts_page = client.get("/workouts").get_data(as_text=True)

    assert "+ Novo treino" in workouts_page


def test_success_flash_is_rendered_as_status_message(client):
    response = client.post(
        "/workouts", data={"date": "2026-10-06", "name": "Push"}, follow_redirects=True
    )

    assert (
        '<li class="alert alert-success" role="status">Treino criado com sucesso.</li>'
        in response.get_data(as_text=True)
    )


def test_error_flash_is_rendered_as_alert(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", position=1)

    response = client.post(
        f"/workouts/{workout.id}/exercises",
        data={"exercise_id": exercise.id},
        follow_redirects=True,
    )

    assert (
        '<li class="alert alert-error" role="alert">'
        "Este exercício já foi adicionado ao treino.</li>"
        in response.get_data(as_text=True)
    )


def test_set_error_is_shown_only_under_the_exercise_that_failed(client, session):
    workout = create_workout(session)
    _, first_workout_exercise = add_exercise(session, workout, "Supino", position=1)
    second_exercise, second_workout_exercise = add_exercise(session, workout, "Remada", position=2)

    response = client.post(
        f"/workouts/{workout.id}/exercises/{second_exercise.id}/sets",
        data={"repetitions": "0", "weight_kg": "37.5"},
    )
    page = response.get_data(as_text=True)
    first_card = page.split(f'id="exercise-{first_workout_exercise.id}"')[1].split(
        f'id="exercise-{second_workout_exercise.id}"'
    )[0]
    second_card = page.split(f'id="exercise-{second_workout_exercise.id}"')[1]

    assert page.count("Informe repetições positivas") == 1
    assert "Informe repetições positivas" in second_card
    assert 'value="37.5"' in second_card
    assert 'value="37.5"' not in first_card


def test_add_set_form_starts_with_previous_set_values(client, session):
    workout = create_workout(session)
    _, workout_exercise = add_exercise(session, workout, "Supino", position=1)
    session.add_all(
        [
            WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=12, weight_kg=Decimal("20.00")),
            WorkoutSet(workout_exercise=workout_exercise, position=2, repetitions=8, weight_kg=Decimal("27.50")),
        ]
    )
    session.commit()

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert f'id="repetitions-{workout_exercise.id}" name="repetitions"' in page
    assert 'name="repetitions" type="number" min="1" inputmode="numeric" value="8"' in page
    assert 'name="weight_kg" type="number" min="0" step="0.01" inputmode="decimal" value="27.50"' in page


def test_detail_shows_sets_table_headers_and_add_set_labels(client, session):
    workout = create_workout(session)
    _, workout_exercise = add_exercise(session, workout, "Supino", position=1)
    session.add(WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=10, weight_kg=Decimal("0")))
    session.commit()

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    for header in ("Série", "Repetições", "Peso"):
        assert f">{header}</th>" in page
    assert f'<label for="repetitions-{workout_exercise.id}">Repetições</label>' in page
    assert f'<label for="weight-{workout_exercise.id}">Peso (kg)</label>' in page
    assert "Adicionar série" in page


def test_forms_offer_cancel_action(client, session):
    workout = create_workout(session)

    new_workout_page = client.get("/workouts/new").get_data(as_text=True)
    edit_workout_page = client.get(f"/workouts/{workout.id}/edit").get_data(as_text=True)

    assert 'href="/workouts">Cancelar</a>' in new_workout_page
    assert f'href="/workouts/{workout.id}">Cancelar</a>' in edit_workout_page
