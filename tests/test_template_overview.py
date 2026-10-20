"""Template cards below the calendar and the template overview."""

import pytest

from app.models import Exercise, Workout, WorkoutTemplate, WorkoutTemplateExercise


def create_exercise(session, name, muscle_group="Peito", muscle_subgroup="Peitoral médio"):
    exercise = Exercise(name=name, muscle_group=muscle_group, muscle_subgroup=muscle_subgroup)
    session.add(exercise)
    session.commit()
    return exercise


def create_template(session, name, items):
    template = WorkoutTemplate(name=name)
    for position, (exercise, target_sets, target_repetitions) in enumerate(items, start=1):
        template.template_exercises.append(
            WorkoutTemplateExercise(
                exercise=exercise, position=position, target_sets=target_sets, target_repetitions=target_repetitions
            )
        )
    session.add(template)
    session.commit()
    return template


def header_of(page):
    return page.split('<header class="page-header">')[1].split("</header>")[0]


@pytest.fixture
def push(session):
    bench = create_exercise(session, "Supino inclinado")
    raise_ = create_exercise(session, "Elevação lateral", "Ombros", "Deltoide lateral")
    plank = create_exercise(session, "Prancha", "Abdômen", "Reto abdominal")
    return create_template(session, "Push", [(bench, 4, 10), (raise_, 1, 1), (plank, None, None)])


# Overview


def test_overview_shows_name_exercises_in_order_and_targets(client, push):
    page = client.get(f"/templates/{push.id}").get_data(as_text=True)

    assert "<h1>Push</h1>" in page
    assert "Modelo de treino · 3 exercícios" in page
    body = page[page.index('class="template-overview-list"'):]
    assert body.index("Supino inclinado") < body.index("Elevação lateral") < body.index("Prancha")
    assert "Ombros / Deltoide lateral" in body
    assert "<strong>4 séries</strong>\n              × 10 repetições" in body
    # Singular forms.
    assert "<strong>1 série</strong>\n              × 1 repetição" in body
    # A template exercise saved before targets existed.
    assert body.count("Sem meta definida") == 1


def test_overview_offers_start_edit_and_delete_with_start_at_the_top_right(client, push):
    header = header_of(client.get(f"/templates/{push.id}").get_data(as_text=True))

    edit = header.index(f'href="/templates/{push.id}/edit">Editar modelo</a>')
    delete = header.index(f'action="/templates/{push.id}/delete"')
    start = header.index(f'action="/templates/{push.id}/start" method="post" data-submit-once>')
    # Last in the row of actions, which is right-aligned: the top right corner.
    assert edit < delete < start
    assert 'class="inline-form overview-start"' in header
    assert '<button class="btn btn-primary" type="submit">Iniciar treino</button>' in header
    assert 'data-confirm-dialog="delete-template-dialog"' in header
    assert 'data-confirm-name="Push"' in header


def test_start_button_comes_first_and_full_width_on_small_screens(client):
    with client.get("/static/css/main.css") as response:
        css = response.get_data(as_text=True)

    small_screens = css[css.index("@media (max-width: 640px)"):]
    rule = small_screens[small_screens.index(".overview-start {"):small_screens.index("}", small_screens.index(".overview-start {"))]
    assert "order: -1;" in rule
    assert "flex-basis: 100%;" in rule


def test_viewing_the_overview_changes_nothing(client, session, push):
    session.expire_all()
    before = session.get(WorkoutTemplate, push.id).updated_at

    for _ in range(2):
        assert client.get(f"/templates/{push.id}").status_code == 200

    session.expire_all()
    assert session.get(WorkoutTemplate, push.id).updated_at == before
    assert session.query(Workout).count() == 0


def test_starting_from_the_overview_creates_the_session(client, session, push):
    response = client.post(f"/templates/{push.id}/start", follow_redirects=True)

    workout = session.query(Workout).one()
    assert response.request.path == f"/workouts/{workout.id}"
    assert "Treino iniciado." in response.get_data(as_text=True)
    assert [
        (item.exercise.name, item.target_sets, item.target_repetitions)
        for item in sorted(workout.workout_exercises, key=lambda item: item.position)
    ] == [("Supino inclinado", 4, 10), ("Elevação lateral", 1, 1), ("Prancha", None, None)]


def test_overview_links_back_to_the_template_cards(client, push):
    page = client.get(f"/templates/{push.id}").get_data(as_text=True)

    assert '<a class="back-link" href="/workouts#modelos">← Treinos</a>' in page


@pytest.mark.parametrize("template_id", ["999", str(10**25)])
def test_overview_of_unknown_template_is_not_found(client, template_id):
    assert client.get(f"/templates/{template_id}").status_code == 404


# Cards below the calendar


def test_cards_come_after_the_calendar_and_open_the_overview(client, session, push):
    page = client.get("/workouts").get_data(as_text=True)

    assert page.index('id="calendar-title"') < page.index('id="modelos"')
    cards = page[page.index('id="modelos"'):]
    assert f'<a class="library-card template-link-card" href="/templates/{push.id}">' in cards
    assert '<span class="library-card-title">Push</span>' in cards
    assert "3 exercícios" in cards
    assert "Escolha um modelo para ver os exercícios e iniciar o treino." in cards


def test_cards_empty_state_offers_to_create_the_first_template(client):
    cards = client.get("/workouts").get_data(as_text=True).split('id="modelos"')[1]

    assert "Nenhum modelo de treino criado." in cards
    assert '<a class="btn btn-primary" href="/templates/new">Criar modelo</a>' in cards


def test_cards_are_shown_in_every_month_of_the_calendar(client, push):
    for month in ("2020-01", "2026-10", "2030-12"):
        page = client.get(f"/workouts?month={month}").get_data(as_text=True)
        assert f'href="/templates/{push.id}"' in page


# The old /templates address and where saving and deleting lead


def test_old_templates_address_keeps_messages_on_the_way(client):
    with client.session_transaction() as flask_session:
        flask_session["_flashes"] = [("success", "Mensagem pendente.")]

    response = client.get("/templates", follow_redirects=True)

    assert response.request.path == "/workouts"
    assert "Mensagem pendente." in response.get_data(as_text=True)


def test_deleting_from_the_overview_returns_to_the_cards(client, session, push):
    response = client.post(f"/templates/{push.id}/delete")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/workouts#modelos")
    page = client.get("/workouts").get_data(as_text=True)
    assert "Modelo excluído com sucesso." in page
    assert f'href="/templates/{push.id}"' not in page


def test_creating_and_editing_lead_to_the_overview(client, session, push):
    exercise = session.query(Exercise).first()
    form = {"exercise_ids": [str(exercise.id)], "target_sets": ["3"], "target_repetitions": ["10"]}

    created = client.post("/templates", data={"name": "Pull", **form}, follow_redirects=True)
    pull = session.query(WorkoutTemplate).filter_by(name="Pull").one()
    edited = client.post(f"/templates/{push.id}/edit", data={"name": "Push", **form}, follow_redirects=True)

    assert created.request.path == f"/templates/{pull.id}"
    assert "Modelo criado com sucesso." in created.get_data(as_text=True)
    assert edited.request.path == f"/templates/{push.id}"
    assert "Modelo atualizado com sucesso." in edited.get_data(as_text=True)


def test_builder_links_back_to_where_it_was_opened_from(client, push):
    new_page = client.get("/templates/new").get_data(as_text=True)
    edit_page = client.get(f"/templates/{push.id}/edit").get_data(as_text=True)

    assert '<a class="back-link" href="/workouts#modelos">← Treinos</a>' in new_page
    assert f'<a class="back-link" href="/templates/{push.id}">← Push</a>' in edit_page
