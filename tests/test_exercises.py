import re
from datetime import date

import pytest

from app.models import Exercise, Workout, WorkoutExercise


def create_exercise(session, name, muscle_group="XXXXX", muscle_subgroup="XXXXX"):
    exercise = Exercise(name=name, muscle_group=muscle_group, muscle_subgroup=muscle_subgroup)
    session.add(exercise)
    session.commit()
    return exercise


def headings(page, level):
    return re.findall(rf"<h{level}[^>]*>([^<]+)</h{level}>", page)


def test_library_is_accessible_and_empty_state_is_shown(client):
    response = client.get("/exercises")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Biblioteca de exercícios" in page
    assert "Nenhum exercício na biblioteca." in page


def test_library_shows_exercises_with_group_and_subgroup(client, session):
    create_exercise(session, "Supino inclinado", "Peito", "Peitoral clavicular")
    create_exercise(session, "Cadeira extensora", "Pernas", "Quadríceps")

    page = client.get("/exercises").get_data(as_text=True)

    for text in ("Supino inclinado", "Cadeira extensora", "Peito", "Pernas", "Peitoral clavicular", "Quadríceps"):
        assert text in page


def test_library_groups_exercises_under_their_group_and_subgroup(client, session):
    create_exercise(session, "Supino reto", "Peito", "Peitoral médio")
    create_exercise(session, "Stiff", "Pernas", "Posteriores de coxa")
    create_exercise(session, "Supino inclinado", "Peito", "Peitoral clavicular")

    page = client.get("/exercises").get_data(as_text=True)
    chest_section = page.split(">Peito</h2>")[1].split(">Pernas</h2>")[0]
    legs_section = page.split(">Pernas</h2>")[1]

    assert "Supino reto" in chest_section
    assert "Supino inclinado" in chest_section
    assert "Stiff" not in chest_section
    assert "Stiff" in legs_section
    assert chest_section.index("Peitoral clavicular") < chest_section.index("Supino inclinado")
    assert chest_section.index("Peitoral médio") < chest_section.index("Supino reto")


def test_library_orders_groups_subgroups_and_exercises_alphabetically(client, session):
    create_exercise(session, "Leg press", "Pernas", "Quadríceps")
    create_exercise(session, "Agachamento", "Pernas", "Quadríceps")
    create_exercise(session, "Elevação lateral", "Ombros", "Deltoide lateral")
    create_exercise(session, "Mesa flexora", "Pernas", "Posteriores de coxa")
    create_exercise(session, "Abdominal curto", "Abdômen", "Reto abdominal")
    create_exercise(session, "Encolhimento", "Ombros", "Deltoide lateral")

    page = client.get("/exercises").get_data(as_text=True)
    legs_section = page.split(">Pernas</h2>")[1]

    assert headings(page, 2) == ["Abdômen", "Ombros", "Pernas"]
    assert headings(legs_section, 3) == ["Posteriores de coxa", "Quadríceps"]
    assert legs_section.index("Agachamento") < legs_section.index("Leg press")
    # Accented names sort next to their unaccented letters, not after "Z".
    assert page.index("Elevação lateral") < page.index("Encolhimento")


def test_library_shows_unclassified_marker_after_classified_entries(client, session):
    create_exercise(session, "Remada cavalinho", "Costas", "XXXXX")
    create_exercise(session, "Pulldown", "Costas", "Latíssimo do dorso")
    create_exercise(session, "Exercício pendente")

    page = client.get("/exercises").get_data(as_text=True)
    back_section = page.split(">Costas</h2>")[1]

    assert headings(page, 2) == ["Costas", "XXXXX"]
    assert headings(back_section, 3)[:2] == ["Latíssimo do dorso", "XXXXX"]
    assert "Remada cavalinho" in back_section
    assert "Exercício pendente" in page


def test_library_has_no_create_edit_or_delete_actions(client, session):
    exercise = create_exercise(session, "Supino reto", "Peito", "Peitoral médio")

    page = client.get("/exercises").get_data(as_text=True)

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
