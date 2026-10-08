from datetime import date
from decimal import Decimal

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_exercise(session, name="Supino 30º"):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral clavicular")
    session.add(exercise)
    session.commit()
    return exercise


def record_occurrence(session, exercise, workout_date, workout_name="Push", sets=(), position=1, workout=None):
    """Create a workout (unless given) where `exercise` was done with `sets` as (reps, weight)."""
    if workout is None:
        workout = Workout(date=workout_date, name=workout_name)
        session.add(workout)
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
    return workout


def get_history(client, exercise):
    response = client.get(f"/exercises/{exercise.id}/history")
    assert response.status_code == 200
    assert response.is_json
    return response.get_json()


# Backend


def test_history_of_nonexistent_exercise_returns_404(client):
    response = client.get("/exercises/999/history")

    assert response.status_code == 404


def test_history_of_exercise_without_occurrences_is_empty(client, session):
    exercise = create_exercise(session)

    data = get_history(client, exercise)

    assert data == {
        "exercise": {"id": exercise.id, "name": "Supino 30º"},
        "history": [],
        "chart": {"labels": [], "workout_names": [], "repetitions": [], "max_weight_kg": []},
    }


def test_history_with_one_occurrence_returns_its_aggregates(client, session):
    exercise = create_exercise(session)
    workout = record_occurrence(
        session,
        exercise,
        date(2026, 10, 7),
        sets=[(10, "20.00"), (10, "22.00"), (9, "22.00"), (9, "21.50")],
    )

    data = get_history(client, exercise)

    assert data["history"] == [
        {
            "workout_id": workout.id,
            "date": "2026-10-07",
            "workout_name": "Push",
            "sets": 4,
            "repetitions": 38,
            "max_weight_kg": 22.0,
        }
    ]


def test_history_returns_every_occurrence_most_recent_first(client, session):
    exercise = create_exercise(session)
    record_occurrence(session, exercise, date(2026, 10, 10), "Push B", sets=[(10, "22")])
    record_occurrence(session, exercise, date(2026, 10, 7), "Push A", sets=[(8, "20")])
    record_occurrence(session, exercise, date(2026, 10, 14), "Push C", sets=[(12, "24")])

    data = get_history(client, exercise)

    assert [occurrence["date"] for occurrence in data["history"]] == ["2026-10-14", "2026-10-10", "2026-10-07"]
    assert [occurrence["workout_name"] for occurrence in data["history"]] == ["Push C", "Push B", "Push A"]


def test_history_keeps_workouts_on_the_same_date_separate(client, session):
    exercise = create_exercise(session)
    first = record_occurrence(session, exercise, date(2026, 10, 7), "Push", sets=[(10, "20")])
    second = record_occurrence(session, exercise, date(2026, 10, 7), "Upper", sets=[(6, "30"), (6, "30")])

    data = get_history(client, exercise)

    # Same date: the most recently created workout comes first, like the workout history.
    assert [(occurrence["workout_id"], occurrence["workout_name"]) for occurrence in data["history"]] == [
        (second.id, "Upper"),
        (first.id, "Push"),
    ]
    assert [occurrence["sets"] for occurrence in data["history"]] == [2, 1]


def test_history_counts_sets_sums_repetitions_and_finds_max_weight_per_occurrence(client, session):
    exercise = create_exercise(session)
    record_occurrence(session, exercise, date(2026, 10, 1), sets=[(12, "17.50"), (10, "20.25"), (8, "20.00")])
    record_occurrence(session, exercise, date(2026, 10, 3), sets=[(5, "40")])

    data = get_history(client, exercise)

    older = data["history"][1]
    assert (older["sets"], older["repetitions"], older["max_weight_kg"]) == (3, 30, 20.25)
    newer = data["history"][0]
    assert (newer["sets"], newer["repetitions"], newer["max_weight_kg"]) == (1, 5, 40.0)


def test_history_supports_bodyweight_sets(client, session):
    exercise = create_exercise(session, "Barra fixa")
    record_occurrence(session, exercise, date(2026, 10, 7), sets=[(12, "0"), (10, "0")])

    occurrence = get_history(client, exercise)["history"][0]

    assert occurrence["max_weight_kg"] == 0.0
    assert occurrence["repetitions"] == 22


def test_history_includes_occurrence_without_sets(client, session):
    exercise = create_exercise(session)
    record_occurrence(session, exercise, date(2026, 10, 1), sets=[(10, "20")])
    record_occurrence(session, exercise, date(2026, 10, 7), "Em andamento")

    data = get_history(client, exercise)

    in_progress = data["history"][0]
    assert (in_progress["sets"], in_progress["repetitions"], in_progress["max_weight_kg"]) == (0, 0, None)
    # In the chart it is a gap, not a drop to zero.
    assert data["chart"]["repetitions"] == [10, None]
    assert data["chart"]["max_weight_kg"] == [20.0, None]


def test_history_only_includes_the_requested_exercise(client, session):
    bench = create_exercise(session, "Supino 30º")
    row = create_exercise(session, "Remada cavalinho")
    workout = record_occurrence(session, bench, date(2026, 10, 7), sets=[(10, "20")])
    record_occurrence(session, row, None, sets=[(12, "50"), (12, "50")], position=2, workout=workout)

    occurrences = get_history(client, bench)["history"]

    assert len(occurrences) == 1
    assert (occurrences[0]["sets"], occurrences[0]["repetitions"]) == (1, 10)


def test_chart_uses_table_data_in_chronological_order(client, session):
    exercise = create_exercise(session)
    record_occurrence(session, exercise, date(2026, 10, 14), "Push C", sets=[(14, "24"), (14, "24"), (14, "24")])
    record_occurrence(session, exercise, date(2026, 10, 7), "Push A", sets=[(10, "22"), (10, "22")])
    record_occurrence(session, exercise, date(2026, 10, 10), "Push B", sets=[(20, "22.5")])

    data = get_history(client, exercise)

    assert data["chart"] == {
        "labels": ["2026-10-07", "2026-10-10", "2026-10-14"],
        "workout_names": ["Push A", "Push B", "Push C"],
        "repetitions": [20, 20, 42],
        "max_weight_kg": [22.0, 22.5, 24.0],
    }
    table_oldest_first = list(reversed(data["history"]))
    assert data["chart"]["repetitions"] == [occurrence["repetitions"] for occurrence in table_oldest_first]
    assert data["chart"]["max_weight_kg"] == [occurrence["max_weight_kg"] for occurrence in table_oldest_first]


def test_history_does_not_change_stored_data(client, session):
    exercise = create_exercise(session)
    record_occurrence(session, exercise, date(2026, 10, 7), sets=[(10, "20")])

    get_history(client, exercise)

    session.expire_all()
    assert session.query(WorkoutSet).one().repetitions == 10
    assert session.query(WorkoutExercise).count() == 1


# Interface


def test_every_exercise_in_workout_has_a_history_button(client, session):
    bench = create_exercise(session, "Supino 30º")
    row = create_exercise(session, "Remada cavalinho")
    workout = record_occurrence(session, bench, date(2026, 10, 7))
    record_occurrence(session, row, None, position=2, workout=workout)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert page.count(">Histórico<span") == 2
    for exercise in (bench, row):
        assert f'data-history-url="/exercises/{exercise.id}/history"' in page
        assert f'data-exercise-name="{exercise.name}"' in page
        assert f'Histórico<span class="visually-hidden"> de {exercise.name}</span>' in page


def test_workout_page_contains_history_modal_with_title_and_close_button(client, session):
    exercise = create_exercise(session)
    workout = record_occurrence(session, exercise, date(2026, 10, 7))

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert '<dialog class="modal" id="exercise-history-dialog" aria-labelledby="exercise-history-title">' in page
    assert '<h2 id="exercise-history-title">Histórico — <span data-history-exercise-name></span></h2>' in page
    assert 'data-history-close aria-label="Fechar histórico">×</button>' in page
    assert "data-history-body" in page


def test_workout_page_loads_chart_library_and_history_script(client, session):
    exercise = create_exercise(session)
    workout = record_occurrence(session, exercise, date(2026, 10, 7))

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    chart_position = page.index('src="/static/vendor/chart.umd.min.js"')
    assert chart_position < page.index('src="/static/js/exercise_history.js"')
    assert client.get("/static/vendor/chart.umd.min.js").status_code == 200
    assert client.get("/static/js/exercise_history.js").status_code == 200


def test_other_pages_do_not_load_history_scripts(client):
    for url in ("/workouts", "/exercises", "/workouts/new"):
        assert "chart.umd.min.js" not in client.get(url).get_data(as_text=True)


def test_history_script_handles_closing_loading_and_empty_states(client):
    script = client.get("/static/js/exercise_history.js").get_data(as_text=True)

    # Close: X button, click on the backdrop and Escape (native <dialog> behaviour
    # of showModal(), which fires the same "close" event).
    assert "dialog.showModal()" in script
    assert '[data-history-close]' in script
    assert "event.target === dialog" in script
    assert 'addEventListener("close"' in script
    assert "Carregando histórico..." in script
    assert "Nenhum histórico disponível para este exercício." in script
    # The table is built from the JSON, never from HTML strings.
    assert ".innerHTML" not in script
