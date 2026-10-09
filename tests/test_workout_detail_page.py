import re
from datetime import date
from decimal import Decimal

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


JSON_HEADERS = {"Accept": "application/json"}


def create_workout(session, name="Push"):
    workout = Workout(date=date(2026, 10, 8), name=name)
    session.add(workout)
    session.commit()
    return workout


def add_exercise(session, workout, name, position, sets=()):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=position)
    session.add_all([exercise, workout_exercise])
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
    # Pages then read the values as stored by the database (e.g. 20 -> 20.00).
    session.expire_all()
    return exercise, workout_exercise


def exercise_card(page, workout_exercise):
    start = page.index(f'<li class="panel exercise-card" id="exercise-{workout_exercise.id}">')
    return page[start:page.index("</li>", page.index('data-sets', start))]


def card_header(card):
    return card.split('<div class="exercise-card-body"')[0]


def card_body(card):
    return card.split('<div class="exercise-card-body"')[1]


def rendered_sets(html):
    return re.findall(
        r'<td class="set-position">(\d+)</td>\s*'
        r'<td class="set-repetitions[^"]*">(\d+)</td>\s*'
        r'<td class="set-weight[^"]*">([\d.]+) kg</td>',
        html,
    )


def sets_url(workout, exercise, suffix=""):
    return f"/workouts/{workout.id}/exercises/{exercise.id}/sets{suffix}"


# Collapsible exercises


def test_exercises_start_collapsed_with_sets_hidden(client, session):
    workout = create_workout(session)
    _, bench = add_exercise(session, workout, "Supino", 1, sets=[(10, "20")])
    _, fly = add_exercise(session, workout, "Crucifixo", 2)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    for workout_exercise in (bench, fly):
        card = exercise_card(page, workout_exercise)
        assert 'aria-expanded="false"' in card
        assert f'aria-controls="exercise-{workout_exercise.id}-body"' in card
        assert f'<div class="exercise-card-body" id="exercise-{workout_exercise.id}-body" hidden>' in card
    # The sets and the add-set form live inside the hidden body.
    bench_body = card_body(exercise_card(page, bench))
    assert rendered_sets(bench_body) == [("1", "10", "20.00")]
    assert "Adicionar série" in bench_body


def test_collapsed_header_shows_name_and_muscles(client, session):
    workout = create_workout(session)
    _, bench = add_exercise(session, workout, "Supino", 1)

    header = card_header(exercise_card(client.get(f"/workouts/{workout.id}").get_data(as_text=True), bench))

    assert '<span class="exercise-toggle-name">Supino</span>' in header
    assert '<span class="exercise-toggle-muscles">Peito / Peitoral médio</span>' in header


def test_exercise_actions_stay_visible_and_outside_the_toggle(client, session):
    workout = create_workout(session)
    _, first = add_exercise(session, workout, "Supino", 1)
    add_exercise(session, workout, "Crucifixo", 2)

    header = card_header(exercise_card(client.get(f"/workouts/{workout.id}").get_data(as_text=True), first))
    toggle = header.split("<button")[1].split("</button>")[0]
    actions = header.split('<div class="actions">')[1]

    # Histórico, Mover and Remover are in the always-visible header, as siblings
    # of the toggle button, so clicking them does not expand/collapse the card.
    assert "data-exercise-toggle" in toggle
    assert "Histórico" not in toggle
    assert "data-history-url" in actions
    assert "/move-down" in actions
    assert "/delete" in actions
    assert "Remover" in actions


def test_failed_add_set_without_javascript_shows_that_exercise_expanded(client, session):
    workout = create_workout(session)
    _, bench = add_exercise(session, workout, "Supino", 1)
    fly_exercise, fly = add_exercise(session, workout, "Crucifixo", 2)

    page = client.post(sets_url(workout, fly_exercise), data={"repetitions": "0", "weight_kg": "20"}).get_data(as_text=True)

    assert 'aria-expanded="true"' in exercise_card(page, fly)
    assert f'id="exercise-{fly.id}-body">' in page
    assert f'id="exercise-{bench.id}-body" hidden>' in page


def test_adding_an_exercise_redirects_to_it(client, session):
    workout = create_workout(session)
    exercise = Exercise(name="Supino", muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()

    response = client.post(f"/workouts/{workout.id}/exercises", data={"exercise_id": exercise.id})

    workout_exercise = session.query(WorkoutExercise).one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/workouts/{workout.id}#exercise-{workout_exercise.id}")


def test_workout_script_toggles_exercises_and_opens_the_exercise_in_the_url(client):
    script = client.get("/static/js/workouts.js").get_data(as_text=True)

    assert "[data-exercise-toggle]" in script
    assert 'toggle.setAttribute("aria-expanded", String(expanded))' in script
    assert 'getAttribute("aria-controls")' in script
    assert "window.location.hash" in script


# Set actions as icons


def test_set_edit_and_delete_are_accessible_icons(client, session):
    workout = create_workout(session)
    exercise, bench = add_exercise(session, workout, "Supino", 1, sets=[(10, "20"), (8, "22")])

    body = card_body(exercise_card(client.get(f"/workouts/{workout.id}").get_data(as_text=True), bench))
    set_rows = re.findall(r'<tr id="set-\d+">(.*?)</tr>', body, re.DOTALL)

    assert len(set_rows) == 2
    for position, row in enumerate(set_rows, start=1):
        assert f'aria-label="Editar série {position}"' in row
        assert f'aria-label="Excluir série {position}"' in row
        assert 'title="Editar série"' in row
        assert 'title="Excluir série"' in row
        assert row.count('<svg class="icon"') == 2
        assert row.count('aria-hidden="true"') == 2
        assert ">Editar<" not in row
        assert ">Excluir<" not in row


def test_each_set_has_hidden_inline_edit_form(client, session):
    workout = create_workout(session)
    exercise, bench = add_exercise(session, workout, "Supino", 1, sets=[(10, "20")])
    workout_set = session.query(WorkoutSet).one()

    body = card_body(exercise_card(client.get(f"/workouts/{workout.id}").get_data(as_text=True), bench))
    edit_row = body.split(f'<tr class="set-edit-row" id="set-{workout_set.id}-edit" hidden>')[1].split("</tr>")[0]

    assert f'data-edit-set="set-{workout_set.id}-edit"' in body
    assert f'action="{sets_url(workout, exercise, f"/{workout_set.id}/edit")}"' in edit_row
    assert f'<label for="edit-repetitions-{workout_set.id}">Repetições</label>' in edit_row
    assert f'<label for="edit-weight-{workout_set.id}">Peso (kg)</label>' in edit_row
    assert 'value="10"' in edit_row
    assert 'value="20.00"' in edit_row
    assert "data-cancel-edit" in edit_row
    # The edit link still points to the edit page, which works without JavaScript.
    assert f'href="{sets_url(workout, exercise, f"/{workout_set.id}/edit")}"' in body


# Sets with fetch(): JSON answers of the existing routes


def test_add_set_with_json_returns_updated_sets_area(client, session):
    workout = create_workout(session)
    exercise, bench = add_exercise(session, workout, "Supino", 1, sets=[(10, "20")])
    add_exercise(session, workout, "Crucifixo", 2, sets=[(12, "10")])

    response = client.post(sets_url(workout, exercise), data={"repetitions": "8", "weight_kg": "22.5"}, headers=JSON_HEADERS)
    data = response.get_json()

    assert response.status_code == 200
    assert data["message"] == "Série adicionada com sucesso."
    assert data["total_sets"] == 3
    assert rendered_sets(data["sets_html"]) == [("1", "10", "20.00"), ("2", "8", "22.50")]
    assert data["sets_html"].lstrip().startswith('<div class="exercise-sets" data-sets>')
    # The add form starts with the values of the new last set.
    assert f'id="repetitions-{bench.id}" name="repetitions" type="number" min="1" inputmode="numeric" value="8"' in data["sets_html"]


def test_add_set_with_json_does_not_leave_a_flash_message_behind(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1)

    client.post(sets_url(workout, exercise), data={"repetitions": "8", "weight_kg": "20"}, headers=JSON_HEADERS)
    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "Série adicionada com sucesso." not in page


def test_invalid_set_with_json_returns_error_and_saves_nothing(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1)

    for repetitions, weight_kg in [("0", "20"), ("10", "-1"), ("10", "20.123"), ("", "")]:
        response = client.post(
            sets_url(workout, exercise),
            data={"repetitions": repetitions, "weight_kg": weight_kg},
            headers=JSON_HEADERS,
        )

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "Informe repetições positivas e um peso válido com até duas casas decimais."
        }
    assert session.query(WorkoutSet).count() == 0


def test_edit_set_with_json_updates_only_that_set(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1, sets=[(10, "20"), (8, "22")])
    first_set = session.query(WorkoutSet).filter_by(position=1).one()

    response = client.post(
        sets_url(workout, exercise, f"/{first_set.id}/edit"),
        data={"repetitions": "12", "weight_kg": "21"},
        headers=JSON_HEADERS,
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["message"] == "Série atualizada com sucesso."
    assert rendered_sets(data["sets_html"]) == [("1", "12", "21.00"), ("2", "8", "22.00")]
    assert data["total_sets"] == 2


def test_invalid_edit_with_json_keeps_the_set_unchanged(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1, sets=[(10, "20")])
    workout_set = session.query(WorkoutSet).one()

    response = client.post(
        sets_url(workout, exercise, f"/{workout_set.id}/edit"),
        data={"repetitions": "-3", "weight_kg": "20"},
        headers=JSON_HEADERS,
    )

    session.expire_all()
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert session.get(WorkoutSet, workout_set.id).repetitions == 10


def test_delete_set_with_json_renumbers_the_remaining_sets(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1, sets=[(10, "20"), (9, "21"), (8, "22")])
    middle_set = session.query(WorkoutSet).filter_by(position=2).one()

    response = client.post(sets_url(workout, exercise, f"/{middle_set.id}/delete"), headers=JSON_HEADERS)
    data = response.get_json()

    assert response.status_code == 200
    assert data["message"] == "Série excluída com sucesso."
    assert rendered_sets(data["sets_html"]) == [("1", "10", "20.00"), ("2", "8", "22.00")]
    assert data["total_sets"] == 2


def test_deleting_last_set_with_json_shows_empty_state(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1, sets=[(10, "20")])
    workout_set = session.query(WorkoutSet).one()

    data = client.post(sets_url(workout, exercise, f"/{workout_set.id}/delete"), headers=JSON_HEADERS).get_json()

    assert "Nenhuma série registrada." in data["sets_html"]
    assert data["total_sets"] == 0


def test_set_routes_with_json_return_404_for_unrelated_set(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1)
    other_workout = create_workout(session, "Outro")
    other_exercise, _ = add_exercise(session, other_workout, "Remada", 1, sets=[(10, "20")])
    other_set = session.query(WorkoutSet).one()

    response = client.post(sets_url(workout, exercise, f"/{other_set.id}/delete"), headers=JSON_HEADERS)

    assert response.status_code == 404
    assert session.query(WorkoutSet).count() == 1


def test_set_routes_without_json_keep_redirecting(client, session):
    workout = create_workout(session)
    exercise, _ = add_exercise(session, workout, "Supino", 1)

    response = client.post(sets_url(workout, exercise), data={"repetitions": "8", "weight_kg": "20"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/workouts/{workout.id}")


def test_set_script_uses_fetch_safely_and_prevents_duplicate_submissions(client):
    script = client.get("/static/js/workouts.js").get_data(as_text=True)

    assert 'headers: { Accept: "application/json" }' in script
    assert "new FormData(form)" in script
    assert 'if (card.dataset.busy === "true")' in script
    assert "button.disabled = busy" in script
    # The page is only updated after a successful answer.
    assert "if (result.ok && result.data && result.data.sets_html)" in script
    assert "new DOMParser().parseFromString(html" in script
    assert "feedback.textContent = message" in script
    assert ".innerHTML" not in script


# Workout actions


def test_workout_page_can_delete_the_workout(client, session):
    workout = create_workout(session)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)
    header = page.split('<header class="page-header">')[1].split("</header>")[0]

    assert f'href="/workouts/{workout.id}/edit">Editar treino</a>' in header
    assert f'action="/workouts/{workout.id}/delete" method="post"' in header
    assert ">Excluir treino</button>" in header


def test_workout_pages_link_back_to_calendar(client, session):
    workout = create_workout(session)

    for url in (f"/workouts/{workout.id}", "/workouts/new", f"/workouts/{workout.id}/edit"):
        assert '<a class="back-link" href="/workouts">← Treinos</a>' in client.get(url).get_data(as_text=True)


def test_editing_a_workout_redirects_to_it(client, session):
    workout = create_workout(session)

    response = client.post(f"/workouts/{workout.id}/edit", data={"date": "2026-10-09", "name": "Pull"})

    assert response.headers["Location"].endswith(f"/workouts/{workout.id}")


def test_workout_page_loads_workout_and_history_scripts(client, session):
    workout = create_workout(session)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert 'src="/static/js/exercise_history.js"' in page
    assert 'src="/static/js/workouts.js"' in page
