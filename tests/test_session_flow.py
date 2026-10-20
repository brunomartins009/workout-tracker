"""The whole flow from the calendar: build a template, start it, record and complete it."""

import re
from datetime import date, datetime, timezone

from app.models import Exercise, Workout


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def test_session_is_created_from_a_template_and_appears_in_the_calendar(client, session):
    bench = create_exercise(session, "Supino")
    fly = create_exercise(session, "Crucifixo")

    # Calendar -> "Novo modelo" (builder) -> "Criar modelo"
    calendar = client.get("/workouts").get_data(as_text=True)
    assert 'href="/templates/new">Novo modelo</a>' in calendar
    assert client.get("/templates/new").status_code == 200
    created = client.post(
        "/templates",
        data={
            "name": "Push",
            "exercise_ids": [str(fly.id), str(bench.id)],
            "target_sets": ["3", "4"],
            "target_repetitions": ["12", "10"],
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201

    # After creating: the template's overview, which offers "Iniciar treino".
    overview = client.get(created.get_json()["redirect_url"]).get_data(as_text=True)
    assert "Modelo criado com sucesso." in overview
    template_id = int(re.search(r'action="/templates/(\d+)/start"', overview).group(1))
    assert f'action="/templates/{template_id}/start"' in overview

    # Calendar -> template card -> overview -> "Iniciar treino"
    calendar = client.get("/workouts").get_data(as_text=True)
    assert f'href="/templates/{template_id}"' in calendar[calendar.index('id="modelos"'):]
    assert client.get(f"/templates/{template_id}").status_code == 200
    started = client.post(f"/templates/{template_id}/start", follow_redirects=True)
    workout = session.query(Workout).one()
    assert started.request.path == f"/workouts/{workout.id}"
    assert "Treino iniciado." in started.get_data(as_text=True)
    assert [item.exercise.name for item in workout.workout_exercises] == ["Crucifixo", "Supino"]

    # The session in progress is in today's calendar cell.
    today = date.today()
    calendar = client.get(f"/workouts?month={today:%Y-%m}").get_data(as_text=True)
    assert f'href="/workouts/{workout.id}"' in calendar

    # Record a set and complete it; it stays in the calendar, now read-only.
    client.post(
        f"/workouts/{workout.id}/exercises/{fly.id}/sets", data={"repetitions": "10", "weight_kg": "12"}
    )
    completed = client.post(f"/workouts/{workout.id}/complete", follow_redirects=True)
    assert "Treino concluído." in completed.get_data(as_text=True)
    calendar = client.get(f"/workouts?month={today:%Y-%m}").get_data(as_text=True)
    assert f'href="/workouts/{workout.id}"' in calendar


def test_calendar_shows_in_progress_and_completed_sessions_alike(client, session):
    completed = Workout(
        date=date(2026, 10, 5),
        name="Push",
        completed_at=datetime(2026, 10, 5, 18, 0, tzinfo=timezone.utc),
    )
    in_progress = Workout(date=date(2026, 10, 7), name="Pull")
    session.add_all([completed, in_progress])
    session.commit()

    page = client.get("/workouts?month=2026-10").get_data(as_text=True)

    assert f'href="/workouts/{completed.id}"' in page
    assert f'href="/workouts/{in_progress.id}"' in page
    assert 'aria-label="05/10/2026: Push"' in page
    assert 'aria-label="07/10/2026: Pull"' in page


def test_templates_empty_state_links_to_builder(client):
    page = client.get("/workouts").get_data(as_text=True)

    assert "Nenhum modelo de treino criado." in page
    assert '<a class="btn btn-primary" href="/templates/new">Criar modelo</a>' in page
