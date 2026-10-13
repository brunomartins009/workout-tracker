"""Adding, removing and moving exercises of a session with fetch() (JSON answers)."""

import re
from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


JSON_HEADERS = {"Accept": "application/json"}


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


def stored_order(session, workout):
    session.expire_all()
    items = session.get(Workout, workout.id).workout_exercises
    return [(item.exercise.name, item.position) for item in sorted(items, key=lambda item: item.position)]


def rendered_cards(html):
    """[(card id, position, exercise name)] in the order of the HTML."""
    return [
        (int(card_id), int(position), name)
        for card_id, position, name in re.findall(
            r'<li class="panel exercise-card" id="exercise-(\d+)">.*?'
            r'<span class="position-badge" aria-hidden="true">(\d+)</span>.*?'
            r'<span class="exercise-toggle-name">([^<]+)</span>',
            html,
            re.DOTALL,
        )
    ]


@pytest.fixture
def workout_with_exercises(session):
    workout = create_workout(session)
    bench = create_exercise(session, "Supino")
    fly = create_exercise(session, "Crucifixo")
    raise_ = create_exercise(session, "Elevação lateral")
    items = [
        add_exercise(session, workout, bench, 1, sets=[(10, "20"), (8, "22.5")]),
        add_exercise(session, workout, fly, 2, sets=[(12, "10")]),
        add_exercise(session, workout, raise_, 3),
    ]
    return workout, [bench, fly, raise_], items


def exercise_url(workout, exercise, action):
    return f"/workouts/{workout.id}/exercises/{exercise.id}/{action}"


# Add


def test_adding_exercise_returns_the_updated_list(client, session, workout_with_exercises):
    workout, _, items = workout_with_exercises
    row = create_exercise(session, "Remada")

    response = client.post(
        f"/workouts/{workout.id}/exercises", data={"exercise_id": row.id}, headers=JSON_HEADERS
    )

    data = response.get_json()
    added = session.query(WorkoutExercise).filter_by(exercise_id=row.id).one()
    assert response.status_code == 200
    assert data["message"] == "Exercício adicionado ao treino."
    assert data["added_workout_exercise_id"] == added.id
    assert data["exercise_count"] == 4
    assert data["total_sets"] == 3
    assert rendered_cards(data["exercises_html"]) == [
        (items[0].id, 1, "Supino"),
        (items[1].id, 2, "Crucifixo"),
        (items[2].id, 3, "Elevação lateral"),
        (added.id, 4, "Remada"),
    ]
    assert stored_order(session, workout)[-1] == ("Remada", 4)


def test_adding_duplicate_exercise_with_fetch_is_rejected(client, session, workout_with_exercises):
    workout, (bench, _, _), _ = workout_with_exercises
    before = stored_order(session, workout)

    response = client.post(
        f"/workouts/{workout.id}/exercises", data={"exercise_id": bench.id}, headers=JSON_HEADERS
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Este exercício já foi adicionado ao treino."}
    assert stored_order(session, workout) == before


@pytest.mark.parametrize("exercise_id", ["999", "", "abc"])
def test_adding_unknown_exercise_with_fetch_returns_404(client, session, workout_with_exercises, exercise_id):
    workout, _, _ = workout_with_exercises
    before = stored_order(session, workout)

    response = client.post(
        f"/workouts/{workout.id}/exercises", data={"exercise_id": exercise_id}, headers=JSON_HEADERS
    )

    assert response.status_code == 404
    assert stored_order(session, workout) == before


# Remove


def test_removing_exercise_returns_renumbered_list_and_counts(client, session, workout_with_exercises):
    workout, (bench, _, _), items = workout_with_exercises

    response = client.post(exercise_url(workout, bench, "delete"), headers=JSON_HEADERS)

    data = response.get_json()
    assert response.status_code == 200
    assert data["message"] == "Exercício removido do treino."
    assert data["added_workout_exercise_id"] is None
    assert data["exercise_count"] == 2
    # The two sets of the removed occurrence are gone; the library exercise stays.
    assert data["total_sets"] == 1
    assert rendered_cards(data["exercises_html"]) == [
        (items[1].id, 1, "Crucifixo"),
        (items[2].id, 2, "Elevação lateral"),
    ]
    assert stored_order(session, workout) == [("Crucifixo", 1), ("Elevação lateral", 2)]
    assert session.get(Exercise, bench.id) is not None


def test_removing_last_exercise_returns_empty_state(client, session):
    workout = create_workout(session)
    bench = create_exercise(session, "Supino")
    add_exercise(session, workout, bench, 1)

    data = client.post(exercise_url(workout, bench, "delete"), headers=JSON_HEADERS).get_json()

    assert data["exercise_count"] == 0
    assert "Nenhum exercício adicionado a este treino." in data["exercises_html"]


def test_removing_unknown_exercise_with_fetch_returns_404(client, session, workout_with_exercises):
    workout, _, _ = workout_with_exercises
    row = create_exercise(session, "Remada")

    response = client.post(exercise_url(workout, row, "delete"), headers=JSON_HEADERS)

    assert response.status_code == 404
    assert len(stored_order(session, workout)) == 3


# Move


def test_moving_exercise_returns_reordered_list(client, session, workout_with_exercises):
    workout, (bench, fly, raise_), items = workout_with_exercises

    up = client.post(exercise_url(workout, raise_, "move-up"), headers=JSON_HEADERS).get_json()
    down = client.post(exercise_url(workout, bench, "move-down"), headers=JSON_HEADERS).get_json()

    assert up["message"] == "Ordem dos exercícios atualizada."
    assert [name for _, _, name in rendered_cards(up["exercises_html"])] == ["Supino", "Elevação lateral", "Crucifixo"]
    # Each card keeps its id, which lets the page keep the open exercises open.
    assert rendered_cards(down["exercises_html"]) == [
        (items[2].id, 1, "Elevação lateral"),
        (items[0].id, 2, "Supino"),
        (items[1].id, 3, "Crucifixo"),
    ]
    assert down["exercise_count"] == 3
    assert down["total_sets"] == 3
    assert stored_order(session, workout) == [("Elevação lateral", 1), ("Supino", 2), ("Crucifixo", 3)]


@pytest.mark.parametrize(("index", "action"), [(0, "move-up"), (2, "move-down")])
def test_moving_past_the_ends_returns_the_unchanged_list(client, session, workout_with_exercises, index, action):
    workout, exercises, _ = workout_with_exercises
    before = stored_order(session, workout)

    response = client.post(exercise_url(workout, exercises[index], action), headers=JSON_HEADERS)

    assert response.status_code == 200
    assert stored_order(session, workout) == before
    assert [name for _, _, name in rendered_cards(response.get_json()["exercises_html"])] == [
        "Supino",
        "Crucifixo",
        "Elevação lateral",
    ]


# The returned list


def test_returned_list_is_the_page_fragment_with_working_controls(client, session, workout_with_exercises):
    workout, (bench, fly, raise_), items = workout_with_exercises

    html = client.post(exercise_url(workout, fly, "move-up"), headers=JSON_HEADERS).get_json()["exercises_html"]

    assert html.lstrip().startswith("<div data-exercise-list>")
    assert "<html" not in html
    # Same markup as the page: collapsed cards with toggle, Histórico, ↑/↓ and Remover.
    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)
    page_list = page[page.index("<div data-exercise-list>"):]
    assert rendered_cards(page_list) == rendered_cards(html)
    for item, exercise in ((items[0], bench), (items[1], fly), (items[2], raise_)):
        assert f'<div class="exercise-card-body" id="exercise-{item.id}-body" hidden>' in html
        assert f'data-history-url="/exercises/{exercise.id}/history"' in html
        assert f'action="{exercise_url(workout, exercise, "delete")}" method="post" data-exercise-form="remove"' in html
    # Crucifixo is first now: no ↑ for it and no ↓ for the last one.
    assert exercise_url(workout, fly, "move-up") not in html
    assert f'action="{exercise_url(workout, fly, "move-down")}" method="post" data-exercise-form="move-down"' in html
    assert exercise_url(workout, raise_, "move-down") not in html
    # Sets and their forms are part of each card.
    assert "22.50 kg" in html
    assert html.count("data-set-form") > 0


def test_regular_forms_keep_redirecting(client, session, workout_with_exercises):
    workout, (bench, _, raise_), _ = workout_with_exercises

    moved = client.post(exercise_url(workout, raise_, "move-up"))
    removed = client.post(exercise_url(workout, bench, "delete"))

    assert moved.status_code == 302
    assert removed.status_code == 302
    assert removed.headers["Location"].endswith(f"/workouts/{workout.id}")


# Workout page markup and scripts


def test_page_marks_exercise_forms_and_has_feedback_areas(client, session, workout_with_exercises):
    workout, _, _ = workout_with_exercises

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert 'data-exercise-form="add"' in page
    assert page.count('data-exercise-form="move-up"') == 2
    assert page.count('data-exercise-form="move-down"') == 2
    assert page.count('data-exercise-form="remove"') == 3
    assert "data-exercise-feedback" in page
    assert "data-add-exercise-feedback" in page


def test_empty_session_offers_add_exercise_link(client, session):
    workout = create_workout(session)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert '<a href="#add-exercise">+ Adicionar exercício</a>' in page
    assert "<div data-exercise-list>" in page


def test_scripts_delegate_events_so_replaced_html_keeps_working(client):
    workouts_script = client.get("/static/js/workouts.js").get_data(as_text=True)
    history_script = client.get("/static/js/exercise_history.js").get_data(as_text=True)

    assert 'event.target.closest("[data-exercise-form]")' in workouts_script
    assert 'event.target.closest("[data-exercise-toggle]")' in workouts_script
    assert 'event.target.closest("[data-set-form]")' in workouts_script
    assert "result.data.exercises_html" in workouts_script
    assert 'parsed.querySelector("[data-exercise-list]")' in workouts_script
    assert "window.scrollTo(scrollX, scrollY)" in workouts_script
    assert ".innerHTML" not in workouts_script
    assert 'document.addEventListener("click"' in history_script
    assert 'event.target.closest("[data-history-url]")' in history_script


# Confirmation before removing an exercise


def test_remove_buttons_ask_for_confirmation_naming_the_exercise(client, session, workout_with_exercises):
    workout, (bench, _, _), _ = workout_with_exercises

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert page.count('data-confirm-dialog="remove-exercise-dialog"') == 3
    assert (
        f'action="{exercise_url(workout, bench, "delete")}" method="post" data-exercise-form="remove"\n'
        '                data-confirm-dialog="remove-exercise-dialog" data-confirm-name="Supino">'
    ) in page
    dialog = page[page.index('<dialog class="modal modal-small" id="remove-exercise-dialog"'):]
    dialog = dialog[:dialog.index("</dialog>")]
    assert "Remover exercício?" in dialog
    assert "<span data-confirm-name></span>" in dialog
    assert "As séries registradas para ele nesta sessão também serão excluídas." in dialog
    assert "data-confirm-accept>Remover exercício</button>" in dialog
    assert "data-confirm-close>Cancelar</button>" in dialog


def test_returned_list_keeps_the_confirmation_on_remove_buttons(client, session, workout_with_exercises):
    workout, (_, fly, _), _ = workout_with_exercises

    html = client.post(exercise_url(workout, fly, "move-up"), headers=JSON_HEADERS).get_json()["exercises_html"]

    assert html.count('data-confirm-dialog="remove-exercise-dialog"') == 3
    assert 'data-confirm-name="Crucifixo"' in html


def test_confirmation_names_are_escaped(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, create_exercise(session, 'Supino "aspas" <b>x</b>'), 1)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert 'data-confirm-name="Supino &#34;aspas&#34; &lt;b&gt;x&lt;/b&gt;"' in page


def test_completed_workout_has_no_remove_confirmation_and_still_rejects_removal(client, session, workout_with_exercises):
    workout, (bench, _, _), _ = workout_with_exercises
    client.post(f"/workouts/{workout.id}/complete")
    before = stored_order(session, workout)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)
    # A direct request, as if the confirmation had been skipped.
    response = client.post(exercise_url(workout, bench, "delete"), headers=JSON_HEADERS)

    assert "remove-exercise-dialog" not in page
    assert response.status_code == 409
    assert stored_order(session, workout) == before
    assert session.query(WorkoutSet).count() == 3


def test_confirmation_script_is_delegated_and_resubmits_through_fetch(client):
    script = client.get("/static/js/workouts.js").get_data(as_text=True)

    assert 'event.target.closest("form[data-confirm-dialog]")' in script
    # Capture phase: runs before the fetch() handler and stops it until confirmed.
    assert "event.stopPropagation();" in script
    assert "form.requestSubmit();" in script
    assert 'form.dataset.confirmed = "true";' in script
    assert "form.submit()" not in script
    assert 'nameElement.textContent = form.dataset.confirmName || "";' in script


def test_operations_refused_while_another_is_running_are_reported(client):
    script = client.get("/static/js/workouts.js").get_data(as_text=True)

    assert 'const BUSY_MESSAGE = "Aguarde a operação anterior terminar e tente novamente.";' in script
    assert "showMessage(feedback, BUSY_MESSAGE, \"error\");" in script
    assert "showFeedback(card, BUSY_MESSAGE, \"error\");" in script
