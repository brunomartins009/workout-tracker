import re
from datetime import date

import pytest

from app.models import Exercise, Workout, WorkoutExercise


def create_exercise(session, name, muscle_group="XXXXX", muscle_subgroup="XXXXX"):
    exercise = Exercise(name=name, muscle_group=muscle_group, muscle_subgroup=muscle_subgroup)
    session.add(exercise)
    session.commit()
    return exercise


def card_titles(page):
    return re.findall(r'<span class="library-card-title[^"]*">([^<]+)</span>', page)


def category_cards(page):
    """Return (link, title, count text) for each category card on the library page."""
    return re.findall(
        r'<a class="library-card" href="([^"]+)">\s*'
        r'<span class="library-card-title[^"]*">([^<]+)</span>\s*'
        r'<span class="library-card-detail category-count">([^<]+)</span>',
        page,
    )


def exercise_cards(page):
    """Return (name, subgroup) for each exercise card on a category page."""
    return re.findall(
        r'<span class="library-card-title">([^<]+)</span>\s*'
        r'<span class="library-card-detail exercise-subgroup[^"]*">([^<]+)</span>',
        page,
    )


# Library home: categories


def test_library_is_accessible_and_empty_state_is_shown(client):
    response = client.get("/exercises")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Biblioteca de exercícios" in page
    assert "Nenhum exercício na biblioteca." in page


def test_library_shows_each_category_once_with_its_exercise_count(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")
    create_exercise(session, "Supino inclinado", "Peito", "Peitoral clavicular")
    create_exercise(session, "Crucifixo", "Peito", "Peitoral médio")
    create_exercise(session, "Stiff", "Pernas", "Posteriores de coxa")

    page = client.get("/exercises").get_data(as_text=True)

    assert [(title, count) for _, title, count in category_cards(page)] == [
        ("Peito", "3 exercícios"),
        ("Pernas", "1 exercício"),
    ]


def test_library_lists_categories_alphabetically_ignoring_accents(client, session):
    for name, group in [
        ("Stiff", "Pernas"),
        ("Abdominal curto", "Abdômen"),
        ("Supino reto", "Peito"),
        ("Rosca direta", "Braços"),
        ("Pulldown", "Costas"),
        ("Elevação lateral", "Ombros"),
    ]:
        create_exercise(session, name, group, "Subgrupo")

    page = client.get("/exercises").get_data(as_text=True)

    assert card_titles(page) == ["Abdômen", "Braços", "Costas", "Ombros", "Peito", "Pernas"]


def test_library_category_cards_link_to_their_category_page(client, session):
    create_exercise(session, "Abdominal curto", "Abdômen", "Reto abdominal")
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    page = client.get("/exercises").get_data(as_text=True)

    assert [(link, title) for link, title, _ in category_cards(page)] == [
        ("/exercises/Abd%C3%B4men", "Abdômen"),
        ("/exercises/Peito", "Peito"),
    ]
    for link, _, _ in category_cards(page):
        assert client.get(link).status_code == 200


def test_library_shows_unclassified_category_last(client, session):
    create_exercise(session, "Pulldown", "Costas", "Latíssimo do dorso")
    create_exercise(session, "Exercício pendente")

    page = client.get("/exercises").get_data(as_text=True)

    assert card_titles(page) == ["Costas", "XXXXX"]
    assert '<span class="library-card-title unclassified">XXXXX</span>' in page


def test_library_home_does_not_list_exercises_or_load_modal_scripts(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    page = client.get("/exercises").get_data(as_text=True)

    assert "Supino reto" not in page
    assert "data-history-url" not in page
    assert "chart.umd.min.js" not in page
    assert "exercise_history.js" not in page


# Category page


def test_category_page_shows_only_exercises_of_that_category(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")
    create_exercise(session, "Stiff", "Pernas", "Posteriores de coxa")

    response = client.get("/exercises/Peito")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<h1>Peito</h1>" in page
    assert exercise_cards(page) == [("Supino reto", "Peitoral médio")]
    assert "Stiff" not in page


def test_category_page_orders_by_subgroup_then_name(client, session):
    create_exercise(session, "Leg press", "Pernas", "Quadríceps")
    create_exercise(session, "Stiff", "Pernas", "Posteriores de coxa")
    create_exercise(session, "Agachamento", "Pernas", "Quadríceps")
    create_exercise(session, "Elevação pélvica", "Pernas", "Glúteos")
    create_exercise(session, "Mesa flexora", "Pernas", "Posteriores de coxa")
    create_exercise(session, "Encolhimento", "Pernas", "Glúteos")

    page = client.get("/exercises/Pernas").get_data(as_text=True)

    assert exercise_cards(page) == [
        # Accented names sort next to their unaccented letters, not after "Z".
        ("Elevação pélvica", "Glúteos"),
        ("Encolhimento", "Glúteos"),
        ("Mesa flexora", "Posteriores de coxa"),
        ("Stiff", "Posteriores de coxa"),
        ("Agachamento", "Quadríceps"),
        ("Leg press", "Quadríceps"),
    ]


def test_category_page_keeps_unclassified_subgroup_visible_and_last(client, session):
    create_exercise(session, "Remada cavalinho", "Costas", "XXXXX")
    create_exercise(session, "Pulldown", "Costas", "Latíssimo do dorso")

    page = client.get("/exercises/Costas").get_data(as_text=True)

    assert exercise_cards(page) == [("Pulldown", "Latíssimo do dorso"), ("Remada cavalinho", "XXXXX")]
    assert '<span class="library-card-detail exercise-subgroup unclassified">XXXXX</span>' in page


def test_category_with_accented_name_is_reachable(client, session):
    create_exercise(session, "Abdominal curto", "Abdômen", "Reto abdominal")

    response = client.get("/exercises/Abdômen")

    assert response.status_code == 200
    assert exercise_cards(response.get_data(as_text=True)) == [("Abdominal curto", "Reto abdominal")]


def test_unknown_category_returns_404(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    assert client.get("/exercises/Inexistente").status_code == 404
    # Category names are matched exactly, as stored in Exercise.muscle_group.
    assert client.get("/exercises/peito").status_code == 404


def test_category_page_links_back_to_library(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    page = client.get("/exercises/Peito").get_data(as_text=True)

    assert '<a class="back-link" href="/exercises">← Biblioteca</a>' in page


def test_each_exercise_card_opens_the_modal_with_its_own_history(client, session):
    bench = create_exercise(session, "Supino reto", "Peito", "Peitoral médio")
    fly = create_exercise(session, "Crucifixo", "Peito", "Peitoral médio")

    page = client.get("/exercises/Peito").get_data(as_text=True)

    assert page.count('aria-haspopup="dialog"') == 2
    for exercise in (bench, fly):
        assert f'data-history-url="/exercises/{exercise.id}/history"' in page
        assert f'data-exercise-name="{exercise.name}"' in page
    assert '<dialog class="modal" id="exercise-history-dialog"' in page


def test_category_page_loads_chart_library_and_modal_script(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    page = client.get("/exercises/Peito").get_data(as_text=True)

    assert page.index('src="/static/vendor/chart.umd.min.js"') < page.index('src="/static/js/exercise_history.js"')


def test_library_pages_have_no_create_edit_or_delete_actions(client, session):
    exercise = create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    for url in ("/exercises", "/exercises/Peito"):
        page = client.get(url).get_data(as_text=True)

        assert "Novo exercício" not in page
        assert 'href="/exercises/new"' not in page
        assert f"/exercises/{exercise.id}/edit" not in page
        assert f"/exercises/{exercise.id}/delete" not in page
        assert "<form" not in page.split("<main")[1]


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/exercises/new"),
        ("get", "/exercises/1/edit"),
        ("post", "/exercises/1/edit"),
        ("post", "/exercises/1/delete"),
    ],
)
def test_exercise_management_routes_no_longer_exist(client, session, method, url):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    response = getattr(client, method)(url, data={"name": "Outro nome"})

    assert response.status_code == 404


def test_exercises_cannot_be_created_through_http(client, session):
    response = client.post("/exercises", data={"name": "Supino reto"})

    assert response.status_code == 405
    assert session.query(Exercise).count() == 0


def test_exercise_used_in_workout_is_unchanged_by_removed_routes(client, session):
    exercise = create_exercise(session, "Supino reto", "Peito", "Peitoral médio")
    workout = Workout(date=date(2026, 10, 6), name="Push")
    session.add_all([workout, WorkoutExercise(workout=workout, exercise=exercise, position=1)])
    session.commit()

    client.post(f"/exercises/{exercise.id}/edit", data={"name": "Outro"})
    client.post(f"/exercises/{exercise.id}/delete")

    session.expire_all()
    assert session.get(Exercise, exercise.id).name == "Supino reto"
    assert session.query(WorkoutExercise).filter_by(exercise_id=exercise.id).count() == 1
