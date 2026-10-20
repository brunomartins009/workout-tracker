"""Workout template routes: list, create, delete and start a session."""

from datetime import date

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet, WorkoutTemplate, WorkoutTemplateExercise


JSON_HEADERS = {"Accept": "application/json"}


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def create_template(session, name, exercises):
    template = WorkoutTemplate(name=name)
    for position, exercise in enumerate(exercises, start=1):
        template.template_exercises.append(WorkoutTemplateExercise(exercise=exercise, position=position))
    session.add(template)
    session.commit()
    return template


def template_items(session, template_id):
    session.expire_all()
    template = session.get(WorkoutTemplate, template_id)
    return [(item.exercise.name, item.position) for item in template.template_exercises]


@pytest.fixture
def exercises(session):
    return [create_exercise(session, name) for name in ("Supino", "Crucifixo", "Elevação lateral")]


# Listing: cards below the calendar (the old /templates page redirects there)


def test_old_templates_address_leads_to_the_cards_below_the_calendar(client):
    response = client.get("/templates")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/workouts#modelos")


def test_cards_show_empty_state(client):
    page = client.get("/workouts").get_data(as_text=True)

    assert "Nenhum modelo de treino criado." in page


def test_cards_list_templates_by_name_and_overview_lists_exercises_in_order(client, session, exercises):
    bench, fly, raise_ = exercises
    upper = create_template(session, "upper", [fly])
    push = create_template(session, "Push", [raise_, bench, fly])

    page = client.get("/workouts").get_data(as_text=True)

    cards = page[page.index('id="modelos"'):]
    assert cards.index(f'href="/templates/{push.id}"') < cards.index(f'href="/templates/{upper.id}"')
    push_card = cards[cards.index(f'href="/templates/{push.id}"'):cards.index(f'href="/templates/{upper.id}"')]
    assert "3 exercícios" in push_card
    assert "1 exercício<" in cards
    overview = client.get(f"/templates/{push.id}").get_data(as_text=True)
    assert overview.index("Elevação lateral") < overview.index("Supino") < overview.index("Crucifixo")


def test_overview_offers_start_and_delete_with_confirmation(client, session, exercises):
    template = create_template(session, "Push", exercises[:1])

    page = client.get(f"/templates/{template.id}").get_data(as_text=True)

    assert f'action="/templates/{template.id}/start"' in page
    assert f'action="/templates/{template.id}/delete"' in page
    assert 'data-confirm-dialog="delete-template-dialog"' in page
    assert 'id="delete-template-dialog"' in page


def test_cards_and_overview_escape_template_names(client, session, exercises):
    template = create_template(session, "Push <script>alert(1)</script>", exercises[:1])

    for url in ("/workouts", f"/templates/{template.id}"):
        page = client.get(url).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in page
        assert "Push &lt;script&gt;alert(1)&lt;/script&gt;" in page


# Create


def test_creates_template_with_exercises_in_the_sent_order(client, session, exercises):
    bench, fly, raise_ = exercises

    response = client.post(
        "/templates",
        data={
            "name": "  Push  ",
            "exercise_ids": [str(raise_.id), str(bench.id), str(fly.id)],
            "target_sets": ["3", "4", "3"],
            "target_repetitions": ["15", "10", "12"],
        },
    )

    template = session.query(WorkoutTemplate).one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/templates/{template.id}")
    assert template.name == "Push"
    assert template_items(session, template.id) == [
        ("Elevação lateral", 1),
        ("Supino", 2),
        ("Crucifixo", 3),
    ]


def test_create_answers_json_for_fetch(client, session, exercises):
    response = client.post(
        "/templates",
        data={"name": "Push", "exercise_ids": [str(exercises[0].id)], "target_sets": ["4"], "target_repetitions": ["10"]},
        headers=JSON_HEADERS,
    )

    template = session.query(WorkoutTemplate).one()
    assert response.status_code == 201
    assert response.get_json() == {"message": "Modelo criado com sucesso.", "redirect_url": f"/templates/{template.id}"}


@pytest.mark.parametrize(
    ("name", "exercise_ids", "error"),
    [
        ("", ["{valid}"], "Informe um nome para o modelo."),
        ("   ", ["{valid}"], "Informe um nome para o modelo."),
        ("Push", [], "Adicione pelo menos um exercício ao modelo."),
        ("Push", ["abc"], "A lista de exercícios é inválida. Recarregue a página e tente novamente."),
        ("Push", ["999"], "A lista de exercícios é inválida. Recarregue a página e tente novamente."),
        ("Push", ["{valid}", "{valid}"], "A lista de exercícios é inválida. Recarregue a página e tente novamente."),
        # A valid exercise followed by an unknown one: nothing at all is saved.
        ("Push", ["{valid}", "999"], "A lista de exercícios é inválida. Recarregue a página e tente novamente."),
    ],
)
def test_create_rejects_invalid_templates_without_saving_anything(client, session, exercises, name, exercise_ids, error):
    exercise_ids = [value.format(valid=exercises[0].id) for value in exercise_ids]

    json_response = client.post(
        "/templates", data={"name": name, "exercise_ids": exercise_ids}, headers=JSON_HEADERS
    )
    form_response = client.post(
        "/templates", data={"name": name, "exercise_ids": exercise_ids}, follow_redirects=True
    )

    assert json_response.status_code == 400
    assert json_response.get_json() == {"error": error}
    assert error in form_response.get_data(as_text=True)
    assert session.query(WorkoutTemplate).count() == 0
    assert session.query(WorkoutTemplateExercise).count() == 0


@pytest.mark.parametrize("duplicate_name", ["Push", "push", "  PUSH  "])
def test_create_rejects_duplicate_name_ignoring_case_and_spaces(client, session, exercises, duplicate_name):
    create_template(session, "Push", exercises[:1])

    response = client.post(
        "/templates",
        data={"name": duplicate_name, "exercise_ids": [str(exercises[1].id)], "target_sets": ["3"], "target_repetitions": ["10"]},
        headers=JSON_HEADERS,
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Já existe um modelo com este nome."}
    assert session.query(WorkoutTemplate).count() == 1
    assert session.query(WorkoutTemplateExercise).count() == 1


# Delete


def test_deletes_template_without_touching_sessions_or_exercises(client, session, exercises):
    template = create_template(session, "Push", exercises)
    other = create_template(session, "Upper", exercises[:1])
    client.post(f"/templates/{template.id}/start")

    response = client.post(f"/templates/{template.id}/delete", follow_redirects=True)

    assert response.request.path == "/workouts"
    assert "Modelo excluído com sucesso." in response.get_data(as_text=True)
    session.expire_all()
    assert session.get(WorkoutTemplate, template.id) is None
    assert template_items(session, other.id) == [("Supino", 1)]
    assert session.query(Exercise).count() == 3
    # The session started from the deleted template keeps its copy.
    workout = session.query(Workout).one()
    assert [item.exercise.name for item in workout.workout_exercises] == ["Supino", "Crucifixo", "Elevação lateral"]


def test_deleting_nonexistent_template_returns_404(client):
    assert client.post("/templates/999/delete").status_code == 404


# Start a session


def test_starting_template_creates_session_today_with_copied_exercises(client, session, exercises):
    bench, fly, raise_ = exercises
    template = create_template(session, "Push", [raise_, bench, fly])

    response = client.post(f"/templates/{template.id}/start")

    workout = session.query(Workout).one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/workouts/{workout.id}")
    assert workout.name == "Push"
    assert workout.date == date.today()
    assert workout.completed_at is None
    assert [(item.exercise.name, item.position) for item in workout.workout_exercises] == [
        ("Elevação lateral", 1),
        ("Supino", 2),
        ("Crucifixo", 3),
    ]
    assert session.query(WorkoutSet).count() == 0


def test_started_session_opens_in_progress_with_message(client, session, exercises):
    template = create_template(session, "Push", exercises[:1])

    response = client.post(f"/templates/{template.id}/start", follow_redirects=True)

    page = response.get_data(as_text=True)
    assert "Treino iniciado." in page
    assert "Em andamento" in page


def test_starting_template_twice_creates_independent_sessions(client, session, exercises):
    template = create_template(session, "Push", exercises[:2])

    client.post(f"/templates/{template.id}/start")
    client.post(f"/templates/{template.id}/start")

    workouts = session.query(Workout).order_by(Workout.id).all()
    assert len(workouts) == 2
    assert session.query(WorkoutExercise).count() == 4
    # Changing one session does not change the other or the template.
    first_item = workouts[0].workout_exercises[0]
    client.post(f"/workouts/{workouts[0].id}/exercises/{first_item.exercise_id}/delete")
    session.expire_all()
    assert len(session.get(Workout, workouts[1].id).workout_exercises) == 2
    assert template_items(session, template.id) == [("Supino", 1), ("Crucifixo", 2)]


def test_starting_template_does_not_change_the_template(client, session, exercises):
    template = create_template(session, "Push", exercises)
    before = template_items(session, template.id)

    client.post(f"/templates/{template.id}/start")

    assert template_items(session, template.id) == before
    assert session.query(WorkoutTemplate).count() == 1


def test_starting_nonexistent_template_returns_404(client, session):
    assert client.post("/templates/999/start").status_code == 404
    assert session.query(Workout).count() == 0


def test_overview_is_part_of_the_workouts_area(client, session, exercises):
    template = create_template(session, "Push", exercises[:1])

    page = client.get(f"/templates/{template.id}").get_data(as_text=True)

    assert '<a href="/workouts" aria-current="page">Treinos</a>' in page


# Messages when saving fails at the database


def fail_template_insert_with(error_message):
    from sqlalchemy.exc import IntegrityError

    def fail(*_args):
        raise IntegrityError("INSERT INTO workout_templates", {}, Exception(error_message))

    return fail


def test_other_constraint_failure_is_not_reported_as_duplicate_name(client, session, exercises):
    from sqlalchemy import event

    failure = fail_template_insert_with("FOREIGN KEY constraint failed")
    event.listen(WorkoutTemplate, "before_insert", failure)
    try:
        response = client.post(
            "/templates",
            data={"name": "Push", "exercise_ids": [str(exercises[0].id)], "target_sets": ["3"], "target_repetitions": ["10"]},
            headers=JSON_HEADERS,
        )
    finally:
        event.remove(WorkoutTemplate, "before_insert", failure)

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Não foi possível criar o modelo. Recarregue a página e tente novamente."
    }
    assert session.query(WorkoutTemplate).count() == 0


def test_name_saved_by_another_request_meanwhile_is_reported_as_duplicate(client, session, exercises):
    # Both requests passed the name check; the unique index rejects the second.
    from sqlalchemy import event

    from app.database import db

    def save_same_name_first(*_args):
        # Another connection saves and commits the same name just before this
        # request inserts its template.
        with db.engine.begin() as other_connection:
            other_connection.exec_driver_sql(
                "INSERT INTO workout_templates (name, created_at, updated_at)"
                " VALUES ('push', '2026-10-09 10:00:00', '2026-10-09 10:00:00')"
            )

    event.listen(WorkoutTemplate, "before_insert", save_same_name_first)
    try:
        response = client.post(
            "/templates",
            data={"name": "Push", "exercise_ids": [str(exercises[0].id)], "target_sets": ["3"], "target_repetitions": ["10"]},
            headers=JSON_HEADERS,
        )
    finally:
        event.remove(WorkoutTemplate, "before_insert", save_same_name_first)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Já existe um modelo com este nome."}
    assert [template.name for template in session.query(WorkoutTemplate).all()] == ["push"]


def test_start_form_is_sent_only_once(client, session, exercises):
    template = create_template(session, "Push", exercises[:1])

    page = client.get(f"/templates/{template.id}").get_data(as_text=True)
    with client.get("/static/js/workouts.js") as response:
        script = response.get_data(as_text=True)

    assert f'action="/templates/{template.id}/start" method="post" data-submit-once>' in page
    assert 'event.target.closest("form[data-submit-once]")' in script
    assert 'form.dataset.submitting === "true"' in script
