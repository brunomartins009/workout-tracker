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
            r'<li class="panel exercise-card" id="exercise-(\d+)"[^>]*>.*?'
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


# Reorder (drag and drop sends the whole new order)


REORDER_ERROR = "A ordem enviada não corresponde aos exercícios do treino. Recarregue a página e tente novamente."


def reorder(client, workout, item_ids, json=True):
    return client.post(
        f"/workouts/{workout.id}/exercises/reorder",
        data={"workout_exercise_ids": [str(item_id) for item_id in item_ids]},
        headers=JSON_HEADERS if json else None,
    )


def test_reordering_returns_the_reordered_list(client, session, workout_with_exercises):
    workout, _, items = workout_with_exercises

    response = reorder(client, workout, [items[2].id, items[0].id, items[1].id])

    data = response.get_json()
    assert response.status_code == 200
    assert data["message"] == "Ordem dos exercícios atualizada."
    # Each card keeps its id, which lets the page keep the open exercises open.
    assert rendered_cards(data["exercises_html"]) == [
        (items[2].id, 1, "Elevação lateral"),
        (items[0].id, 2, "Supino"),
        (items[1].id, 3, "Crucifixo"),
    ]
    assert data["exercise_count"] == 3
    assert data["total_sets"] == 3
    assert stored_order(session, workout) == [("Elevação lateral", 1), ("Supino", 2), ("Crucifixo", 3)]


def test_reordering_to_the_same_order_changes_nothing(client, session, workout_with_exercises):
    workout, _, items = workout_with_exercises
    before = stored_order(session, workout)

    response = reorder(client, workout, [item.id for item in items])

    assert response.status_code == 200
    assert stored_order(session, workout) == before


@pytest.mark.parametrize(
    "order",
    [
        "missing",  # one exercise left out
        "extra",  # an exercise of another session
        "duplicate",
        "unknown",
        "not a number",
        "empty",
        "huge id",
    ],
)
def test_order_that_does_not_match_the_session_is_rejected(client, session, workout_with_exercises, order):
    workout, exercises, items = workout_with_exercises
    other = create_workout(session, "Pull")
    other_item = add_exercise(session, other, exercises[0], 1)
    before = stored_order(session, workout)
    ids = [item.id for item in items]
    sent = {
        "missing": ids[:2],
        "extra": ids + [other_item.id],
        "duplicate": [ids[0], ids[0], ids[1]],
        "unknown": ids[:2] + [999],
        "not a number": ids[:2] + ["abc"],
        "empty": [],
        "huge id": ids[:2] + [10**25],
    }[order]

    json_response = reorder(client, workout, sent)
    form_response = reorder(client, workout, sent, json=False)

    assert json_response.status_code == 400
    assert json_response.get_json() == {"error": REORDER_ERROR}
    assert form_response.status_code == 302
    assert REORDER_ERROR in client.get(form_response.headers["Location"]).get_data(as_text=True)
    assert stored_order(session, workout) == before
    assert stored_order(session, other) == [("Supino", 1)]


def test_reordering_one_session_does_not_affect_another(client, session, workout_with_exercises):
    workout, exercises, items = workout_with_exercises
    other = create_workout(session, "Pull")
    for position, exercise in enumerate(exercises, start=1):
        add_exercise(session, other, exercise, position)

    reorder(client, workout, [items[1].id, items[2].id, items[0].id])

    assert stored_order(session, other) == [("Supino", 1), ("Crucifixo", 2), ("Elevação lateral", 3)]


# The returned list


def test_returned_list_is_the_page_fragment_with_working_controls(client, session, workout_with_exercises):
    workout, (bench, fly, raise_), items = workout_with_exercises

    html = reorder(client, workout, [items[1].id, items[0].id, items[2].id]).get_json()["exercises_html"]

    assert html.lstrip().startswith("<div data-exercise-list>")
    assert "<html" not in html
    # Same markup as the page: collapsed cards with handle, toggle, Histórico and Remover.
    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)
    page_list = page[page.index("<div data-exercise-list>"):]
    assert rendered_cards(page_list) == rendered_cards(html)
    assert f'<ol class="exercise-list" data-sortable-exercises data-reorder-url="/workouts/{workout.id}/exercises/reorder">' in html
    for position, (item, exercise) in enumerate(((items[1], fly), (items[0], bench), (items[2], raise_)), start=1):
        assert f'id="exercise-{item.id}" data-workout-exercise-id="{item.id}" data-position="{position}">' in html
        assert f'<div class="exercise-card-body" id="exercise-{item.id}-body" hidden>' in html
        assert f'data-history-url="/exercises/{exercise.id}/history"' in html
        assert f'action="{exercise_url(workout, exercise, "delete")}" method="post" data-exercise-form="remove"' in html
    assert html.count("data-drag-handle") == 3
    assert "Reordenar Crucifixo, posição 1 de 3." in html
    # The arrows were replaced by the drag handle.
    assert "move-up" not in html and "move-down" not in html
    # Sets and their forms are part of each card.
    assert "22.50 kg" in html
    assert html.count("data-set-form") > 0


def test_regular_forms_keep_redirecting(client, session, workout_with_exercises):
    workout, (bench, _, _), items = workout_with_exercises

    moved = reorder(client, workout, [items[2].id, items[0].id, items[1].id], json=False)
    removed = client.post(exercise_url(workout, bench, "delete"))

    assert moved.status_code == 302
    assert moved.headers["Location"].endswith(f"/workouts/{workout.id}")
    assert removed.status_code == 302
    assert removed.headers["Location"].endswith(f"/workouts/{workout.id}")


# Workout page markup and scripts


def test_page_marks_exercise_forms_and_has_feedback_areas(client, session, workout_with_exercises):
    workout, _, _ = workout_with_exercises

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert 'data-exercise-form="add"' in page
    assert page.count("data-drag-handle") == 3
    assert "data-sortable-exercises" in page
    assert page.count('data-exercise-form="remove"') == 3
    assert "data-exercise-feedback" in page
    assert "data-add-exercise-feedback" in page


def test_empty_session_offers_add_exercise_form(client, session):
    workout = create_workout(session)
    create_exercise(session, "Supino")

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    # The form is the way to add the first exercise (the "+ Adicionar
    # exercício" shortcut in the list header was removed), and the list
    # container exists so the first exercise added with fetch() can be shown.
    assert 'id="add-exercise"' in page
    assert f'action="/workouts/{workout.id}/exercises" method="post" data-exercise-form="add"' in page
    assert '<a href="#add-exercise">' not in page
    assert "<div data-exercise-list>" in page


def test_scripts_delegate_events_so_replaced_html_keeps_working(client):
    with client.get("/static/js/workouts.js") as response:
        workouts_script = response.get_data(as_text=True)
    with client.get("/static/js/exercise_history.js") as response:
        history_script = response.get_data(as_text=True)

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

    items = sorted(session.get(Workout, workout.id).workout_exercises, key=lambda item: item.position)
    html = reorder(client, workout, [items[1].id, items[0].id, items[2].id]).get_json()["exercises_html"]

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
    with client.get("/static/js/workouts.js") as response:
        script = response.get_data(as_text=True)

    assert 'event.target.closest("form[data-confirm-dialog]")' in script
    # Capture phase: runs before the fetch() handler and stops it until confirmed.
    assert "event.stopPropagation();" in script
    assert "form.requestSubmit();" in script
    assert 'form.dataset.confirmed = "true";' in script
    assert "form.submit()" not in script
    assert 'nameElement.textContent = form.dataset.confirmName || "";' in script


def test_operations_refused_while_another_is_running_are_reported(client):
    with client.get("/static/js/workouts.js") as response:
        script = response.get_data(as_text=True)

    assert 'const BUSY_MESSAGE = "Aguarde a operação anterior terminar e tente novamente.";' in script
    assert "showMessage(feedback, BUSY_MESSAGE, \"error\");" in script
    assert "showFeedback(card, BUSY_MESSAGE, \"error\");" in script


def test_completed_session_offers_no_reordering(client, session, workout_with_exercises):
    workout, (bench, _, _), _ = workout_with_exercises
    client.post(f"/workouts/{workout.id}/complete")

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "data-drag-handle" not in page
    assert "data-sortable-exercises" not in page
    assert "/exercises/reorder" not in page


def test_page_script_reorders_by_dragging_and_restores_on_failure(client, session, workout_with_exercises):
    workout, _, _ = workout_with_exercises
    with client.get("/static/js/workouts.js") as response:
        script = response.get_data(as_text=True)
    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "window.SortableList.attach(list" in script
    assert 'data.append("workout_exercise_ids", card.dataset.workoutExerciseId);' in script
    # The saved order (positions rendered by the server) is put back when the
    # server refuses the new order, cannot be reached, or another change is
    # still running.
    assert script.count("showExerciseOrder(list, savedOrder);") == 3
    # A replaced list gets its drag and drop again.
    assert script.count("setUpExerciseSorting();") == 2
    assert page.index('src="/static/js/sortable_list.js"') < page.index('src="/static/js/workouts.js"')


# A session deleted meanwhile (for example, in another tab)


@pytest.mark.parametrize(
    ("url", "data"),
    [
        ("/workouts/{workout}/exercises/{bench}/sets", {"repetitions": "10", "weight_kg": "20"}),
        ("/workouts/{workout}/exercises/{bench}/sets/{set}/edit", {"repetitions": "8", "weight_kg": "20"}),
        ("/workouts/{workout}/exercises/{bench}/sets/{set}/delete", {}),
        ("/workouts/{workout}/exercises", {"exercise_id": "{row}"}),
        ("/workouts/{workout}/exercises/{bench}/delete", {}),
        ("/workouts/{workout}/exercises/reorder", {"workout_exercise_ids": ["{bench_item}"]}),
        ("/workouts/{workout}/edit", {"name": "Pull"}),
    ],
)
def test_fetch_requests_about_a_deleted_session_answer_404(client, session, url, data):
    # The page scripts show "não existe mais" for a 404, which comes without
    # JSON; anything else (such as a 500) would get the generic message.
    workout = create_workout(session)
    bench = create_exercise(session, "Supino")
    row = create_exercise(session, "Remada")
    bench_item = add_exercise(session, workout, bench, 1, sets=[(10, "20")])
    ids = {
        "workout": workout.id,
        "bench": bench.id,
        "row": row.id,
        "set": bench_item.sets[0].id,
        "bench_item": bench_item.id,
    }
    client.post(f"/workouts/{workout.id}/delete")

    response = client.post(
        url.format(**ids),
        data={key: [v.format(**ids) for v in value] if isinstance(value, list) else value.format(**ids) for key, value in data.items()},
        headers=JSON_HEADERS,
    )

    assert response.status_code == 404
    assert session.query(Workout).count() == 0
