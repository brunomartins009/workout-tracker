import re
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.database import db
from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


def create_workout(session, workout_date=date(2026, 10, 5), name="Treino A"):
    workout = Workout(date=workout_date, name=name)
    session.add(workout)
    session.commit()
    return workout


def get_or_create_exercise(session, name):
    exercise = session.query(Exercise).filter_by(name=name).one_or_none()
    if exercise is None:
        exercise = Exercise(name=name)
        session.add(exercise)
        session.commit()
    return exercise


def add_exercise(session, workout, name, position, set_count=0):
    exercise = get_or_create_exercise(session, name)
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=position)
    session.add(workout_exercise)
    for set_position in range(1, set_count + 1):
        session.add(
            WorkoutSet(
                workout_exercise=workout_exercise,
                position=set_position,
                repetitions=10,
                weight_kg=Decimal("20.00"),
            )
        )
    session.commit()
    return workout_exercise


def history_row(page, workout):
    match = re.search(rf'<tr id="workout-{workout.id}">(.*?)</tr>', page, re.DOTALL)
    assert match is not None, f"history row for workout {workout.id} not found"
    return match.group(1)


def summary_value(page, css_class):
    match = re.search(rf'<dd class="{css_class}">(\d+)</dd>', page)
    assert match is not None, f"summary value {css_class} not found"
    return int(match.group(1))


@contextmanager
def count_queries():
    statements = []

    def before_cursor_execute(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(db.engine, "before_cursor_execute", before_cursor_execute)


# History


def test_history_without_workouts_shows_empty_state(client):
    response = client.get("/workouts")

    assert response.status_code == 200
    assert "Nenhum treino cadastrado." in response.get_data(as_text=True)


def test_history_shows_multiple_workouts_with_name_and_date(client, session):
    push = create_workout(session, date(2026, 10, 1), "Push")
    pull = create_workout(session, date(2026, 10, 3), "Pull")

    page = client.get("/workouts").get_data(as_text=True)

    assert "Push" in history_row(page, push)
    assert "01/10/2026" in history_row(page, push)
    assert "Pull" in history_row(page, pull)
    assert "03/10/2026" in history_row(page, pull)


def test_history_orders_workouts_by_most_recent_date_first(client, session):
    oldest = create_workout(session, date(2026, 9, 1), "Treino antigo")
    newest = create_workout(session, date(2026, 10, 1), "Treino recente")
    middle = create_workout(session, date(2026, 9, 15), "Treino do meio")

    page = client.get("/workouts").get_data(as_text=True)

    assert page.index(f'id="workout-{newest.id}"') < page.index(f'id="workout-{middle.id}"')
    assert page.index(f'id="workout-{middle.id}"') < page.index(f'id="workout-{oldest.id}"')


def test_history_shows_exercise_and_set_counts(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, "Supino", position=1, set_count=3)
    add_exercise(session, workout, "Remada", position=2, set_count=2)
    add_exercise(session, workout, "Prancha", position=3, set_count=0)

    row = history_row(client.get("/workouts").get_data(as_text=True), workout)

    assert '<td class="exercise-count">3</td>' in row
    assert '<td class="set-count">5</td>' in row


def test_history_shows_zero_counts_for_empty_workout(client, session):
    workout = create_workout(session)

    row = history_row(client.get("/workouts").get_data(as_text=True), workout)

    assert '<td class="exercise-count">0</td>' in row
    assert '<td class="set-count">0</td>' in row


def test_history_counts_are_isolated_between_workouts(client, session):
    first = create_workout(session, date(2026, 10, 1), "Push")
    second = create_workout(session, date(2026, 10, 2), "Pull")
    add_exercise(session, first, "Supino", position=1, set_count=4)
    add_exercise(session, second, "Supino", position=1, set_count=1)
    add_exercise(session, second, "Remada", position=2, set_count=2)

    page = client.get("/workouts").get_data(as_text=True)
    first_row = history_row(page, first)
    second_row = history_row(page, second)

    assert '<td class="exercise-count">1</td>' in first_row
    assert '<td class="set-count">4</td>' in first_row
    assert '<td class="exercise-count">2</td>' in second_row
    assert '<td class="set-count">3</td>' in second_row


def test_history_links_to_workout_detail_and_keeps_actions(client, session):
    workout = create_workout(session)

    page = client.get("/workouts").get_data(as_text=True)
    row = history_row(page, workout)

    assert f'href="/workouts/{workout.id}"' in row
    assert f'href="/workouts/{workout.id}/edit"' in row
    assert f'action="/workouts/{workout.id}/delete"' in row
    assert 'href="/workouts/new"' in page


def test_history_query_count_does_not_grow_with_workouts(client, session):
    workout = create_workout(session, date(2026, 10, 1), "Push")
    add_exercise(session, workout, "Supino", position=1, set_count=2)
    with count_queries() as statements_with_one_workout:
        client.get("/workouts")

    for day in range(2, 6):
        workout = create_workout(session, date(2026, 10, day), f"Treino {day}")
        add_exercise(session, workout, "Supino", position=1, set_count=2)
        add_exercise(session, workout, f"Remada {day}", position=2, set_count=3)
    with count_queries() as statements_with_many_workouts:
        client.get("/workouts")

    assert len(statements_with_many_workouts) == len(statements_with_one_workout)


# Detail


def test_detail_shows_workout_exercises_sets_repetitions_and_weight(client, session):
    workout = create_workout(session, date(2026, 10, 5), "Push")
    exercise = get_or_create_exercise(session, "Supino")
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=1)
    session.add_all(
        [
            workout_exercise,
            WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=12, weight_kg=Decimal("42.50")),
        ]
    )
    session.commit()

    response = client.get(f"/workouts/{workout.id}")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Push" in page
    assert "05/10/2026" in page
    assert "Supino" in page
    assert "Série 1: 12 reps, 42.50 kg" in page


def test_detail_for_nonexistent_workout_returns_404(client):
    response = client.get("/workouts/999")

    assert response.status_code == 404


def test_detail_lists_exercises_in_position_order(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, "Terceiro exercício", position=3)
    add_exercise(session, workout, "Primeiro exercício", position=1)
    add_exercise(session, workout, "Segundo exercício", position=2)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert page.index("Primeiro exercício") < page.index("Segundo exercício")
    assert page.index("Segundo exercício") < page.index("Terceiro exercício")


def test_detail_lists_sets_in_position_order(client, session):
    workout = create_workout(session)
    exercise = get_or_create_exercise(session, "Supino")
    workout_exercise = WorkoutExercise(workout=workout, exercise=exercise, position=1)
    session.add_all(
        [
            workout_exercise,
            WorkoutSet(workout_exercise=workout_exercise, position=3, repetitions=6, weight_kg=Decimal("30.00")),
            WorkoutSet(workout_exercise=workout_exercise, position=1, repetitions=10, weight_kg=Decimal("20.00")),
            WorkoutSet(workout_exercise=workout_exercise, position=2, repetitions=8, weight_kg=Decimal("25.00")),
        ]
    )
    session.commit()

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert page.index("Série 1: 10 reps, 20.00 kg") < page.index("Série 2: 8 reps, 25.00 kg")
    assert page.index("Série 2: 8 reps, 25.00 kg") < page.index("Série 3: 6 reps, 30.00 kg")


def test_detail_summary_shows_exercise_and_set_totals(client, session):
    workout = create_workout(session)
    add_exercise(session, workout, "Supino", position=1, set_count=3)
    add_exercise(session, workout, "Remada", position=2, set_count=4)
    add_exercise(session, workout, "Prancha", position=3, set_count=0)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "Resumo" in page
    assert summary_value(page, "exercise-count") == 3
    assert summary_value(page, "set-count") == 7


def test_detail_summary_for_empty_workout_is_zero(client, session):
    workout = create_workout(session)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert summary_value(page, "exercise-count") == 0
    assert summary_value(page, "set-count") == 0


def test_detail_only_shows_data_from_requested_workout(client, session):
    push = create_workout(session, date(2026, 10, 1), "Push")
    pull = create_workout(session, date(2026, 10, 2), "Pull")
    add_exercise(session, push, "Supino", position=1, set_count=2)
    add_exercise(session, pull, "Remada", position=1, set_count=5)

    page = client.get(f"/workouts/{push.id}").get_data(as_text=True)
    # "Remada" legitimately appears in the "add exercise" select, so only the
    # part of the page that lists the workout's own exercises is checked.
    workout_exercises_section = page.split("<h2>Adicionar exercício</h2>")[0]

    assert "Supino" in workout_exercises_section
    assert "Remada" not in workout_exercises_section
    assert summary_value(page, "exercise-count") == 1
    assert summary_value(page, "set-count") == 2
