"""Template builder page (/templates/new) and the create flow it relies on."""

import re

from app.models import Exercise, WorkoutTemplate


JSON_HEADERS = {"Accept": "application/json"}


def create_exercise(session, name, muscle_group="Peito", muscle_subgroup="Peitoral médio"):
    exercise = Exercise(name=name, muscle_group=muscle_group, muscle_subgroup=muscle_subgroup)
    session.add(exercise)
    session.commit()
    return exercise


def group_views(page):
    """[(group title, [exercise names in order])] of the builder's group views."""
    views = re.findall(
        r'<div class="builder-group" id="(builder-group-\d+)" data-builder-group hidden>(.*?)</ul>',
        page,
        re.DOTALL,
    )
    return [
        (
            re.search(r'<h3 class="builder-group-title[^"]*" tabindex="-1">([^<]+)</h3>', body).group(1),
            re.findall(r'<span class="library-card-title">([^<]+)</span>', body),
        )
        for _, body in views
    ]


def test_builder_page_has_name_field_selection_panel_and_create_button(client):
    response = client.get("/templates/new")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<input id="template-name" name="name" type="text"' in page
    assert re.search(r'<form\s+id="template-builder-form"\s+action="/templates"\s+method="post"\s+data-template-builder', page)
    assert "data-selected-list" in page
    assert "Criar modelo</button>" in page
    # The create button comes after the picker and the selection panel.
    assert page.index('id="exercise-picker"') < page.index("data-selected-list") < page.index("Criar modelo</button>")


def test_builder_lists_muscle_groups_and_their_exercises_like_the_library(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")
    create_exercise(session, "Crucifixo", "Peito", "Peitoral médio")
    create_exercise(session, "Supino 30º", "Peito", "Peitoral clavicular")
    create_exercise(session, "Remada", "Costas", "Latíssimo do dorso")

    page = client.get("/templates/new").get_data(as_text=True)

    groups = re.findall(
        r'<button class="library-card" type="button" data-builder-show-group="(builder-group-\d+)">\s*'
        r'<span class="library-card-title[^"]*">([^<]+)</span>\s*'
        r'<span class="library-card-detail category-count">([^<]+)</span>',
        page,
    )
    assert groups == [
        ("builder-group-1", "Costas", "1 exercício"),
        ("builder-group-2", "Peito", "3 exercícios"),
    ]
    # Exercises start hidden, ordered by subgroup and then by name.
    assert group_views(page) == [
        ("Costas", ["Remada"]),
        ("Peito", ["Supino 30º", "Crucifixo", "Supino reto"]),
    ]


def test_builder_exercise_cards_open_the_exercise_modal_with_add_button(client, session):
    bench = create_exercise(session, "Supino reto")

    page = client.get("/templates/new").get_data(as_text=True)

    assert f'data-history-url="/exercises/{bench.id}/history"' in page
    assert f'data-exercise-id="{bench.id}" data-exercise-subgroup="Peitoral médio"' in page
    assert 'id="exercise-history-dialog"' in page
    # "Adicionar" sits in the modal header, right before the close button.
    header = page[page.index('<header class="modal-header">'):page.index("</header>", page.index('<header class="modal-header">'))]
    assert header.index("data-exercise-add>Adicionar</button>") < header.index("data-history-close")
    assert page.index('src="/static/vendor/chart.umd.min.js"') < page.index('src="/static/js/exercise_history.js"')
    assert page.index('src="/static/js/exercise_history.js"') < page.index('src="/static/js/template_builder.js"')


def test_library_modal_has_no_add_button(client, session):
    create_exercise(session, "Supino reto")

    page = client.get("/exercises/Peito").get_data(as_text=True)

    assert 'id="exercise-history-dialog"' in page
    assert "data-exercise-add" not in page
    assert "data-exercise-id" not in page


def test_builder_escapes_exercise_names(client, session):
    create_exercise(session, "Supino <b>teste</b>")

    page = client.get("/templates/new").get_data(as_text=True)

    assert "<b>teste</b>" not in page
    assert "Supino &lt;b&gt;teste&lt;/b&gt;" in page


def test_builder_with_empty_library_shows_empty_state(client):
    page = client.get("/templates/new").get_data(as_text=True)

    assert "Nenhum exercício na biblioteca." in page


def test_templates_page_links_to_builder(client):
    page = client.get("/workouts").get_data(as_text=True)

    assert 'href="/templates/new">Novo modelo</a>' in page


def test_builder_script_is_served_and_does_not_use_inner_html(client):
    with client.get("/static/js/template_builder.js") as response:
        script = response.get_data(as_text=True)
        assert response.status_code == 200
    assert ".innerHTML" not in script
    assert 'data.append("exercise_ids"' in script
    assert 'Accept: "application/json"' in script


def test_created_template_message_is_shown_after_fetch_redirect(client, session):
    bench = create_exercise(session, "Supino reto")

    response = client.post(
        "/templates",
        data={"name": "Push", "exercise_ids": [str(bench.id)], "target_sets": ["3"], "target_repetitions": ["10"]},
        headers=JSON_HEADERS,
    )
    page = client.get(response.get_json()["redirect_url"]).get_data(as_text=True)

    assert "Modelo criado com sucesso." in page
    assert session.query(WorkoutTemplate).count() == 1


def test_create_error_without_javascript_returns_to_builder(client, session):
    response = client.post("/templates", data={"name": "Push"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/templates/new")
    page = client.get("/templates/new").get_data(as_text=True)
    assert "Adicione pelo menos um exercício ao modelo." in page
    assert session.query(WorkoutTemplate).count() == 0


def test_builder_page_is_part_of_the_workouts_area(client):
    page = client.get("/templates/new").get_data(as_text=True)

    assert '<a href="/workouts" aria-current="page">Treinos</a>' in page
