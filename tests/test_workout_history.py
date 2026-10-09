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


def rendered_sets(page):
    """Return (position, repetitions, weight) of each set row, in page order."""
    return re.findall(
        r'<td class="set-position">(\d+)</td>\s*'
        r'<td class="set-repetitions[^"]*">(\d+)</td>\s*'
        r'<td class="set-weight[^"]*">([\d.]+) kg</td>',
        page,
    )


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


# Calendar


def test_calendar_query_count_does_not_grow_with_workouts(client, session):
    workout = create_workout(session, date(2026, 10, 1), "Push")
    add_exercise(session, workout, "Supino", position=1, set_count=2)
    with count_queries() as statements_with_one_workout:
        client.get("/workouts?month=2026-10")

    for day in range(2, 6):
        workout = create_workout(session, date(2026, 10, day), f"Treino {day}")
        add_exercise(session, workout, "Supino", position=1, set_count=2)
        add_exercise(session, workout, f"Remada {day}", position=2, set_count=3)
    with count_queries() as statements_with_many_workouts:
        client.get("/workouts?month=2026-10")

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
    assert rendered_sets(page) == [("1", "12", "42.50")]


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

    assert rendered_sets(page) == [
        ("1", "10", "20.00"),
        ("2", "8", "25.00"),
        ("3", "6", "30.00"),
    ]


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
