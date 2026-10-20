"""Ids and numbers beyond what the database can store are rejected cleanly.

SQLite stores integers up to 2**63 - 1; the driver raises OverflowError for
larger ones, which used to become an HTTP 500. With TESTING enabled any such
exception would fail these tests instead of becoming a response.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models import (
    MAX_WEIGHT_KG,
    SQLITE_MAX_INTEGER,
    Exercise,
    Workout,
    WorkoutExercise,
    WorkoutSet,
    WorkoutTemplate,
    WorkoutTemplateExercise,
)


JSON_HEADERS = {"Accept": "application/json"}
HUGE = str(10**25)
TOO_LARGE = str(SQLITE_MAX_INTEGER + 1)
SET_ERROR = "Informe repetições positivas e um peso válido com até duas casas decimais."


@pytest.fixture
def data(session):
    exercise = Exercise(name="Supino", muscle_group="Peito", muscle_subgroup="Peitoral médio")
    workout = Workout(date=date(2026, 10, 8), name="Push")
    item = WorkoutExercise(workout=workout, exercise=exercise, position=1)
    workout_set = WorkoutSet(workout_exercise=item, position=1, repetitions=10, weight_kg=Decimal("20"))
    session.add_all([exercise, workout, item, workout_set])
    session.commit()
    return {"workout_id": workout.id, "exercise_id": exercise.id, "set_id": workout_set.id}


def stored_sets(session):
    session.expire_all()
    return [(s.id, s.position, s.repetitions, s.weight_kg) for s in session.query(WorkoutSet).order_by(WorkoutSet.id)]


# Ids in URLs


@pytest.mark.parametrize("too_large", [HUGE, TOO_LARGE])
@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/workouts/{big}"),
        ("get", "/workouts/{big}/edit"),
        ("post", "/workouts/{big}/complete"),
        ("post", "/workouts/{big}/delete"),
        ("post", "/workouts/{workout_id}/exercises/{big}/delete"),
        ("post", "/workouts/{big}/exercises/reorder"),
        ("post", "/workouts/{workout_id}/exercises/{exercise_id}/sets/{big}/delete"),
        ("get", "/exercises/{big}/history"),
        ("post", "/templates/{big}/start"),
        ("post", "/templates/{big}/delete"),
    ],
)
def test_out_of_range_ids_in_urls_are_not_found(client, session, data, too_large, method, url):
    before = stored_sets(session)

    response = getattr(client, method)(url.format(big=too_large, **data), headers=JSON_HEADERS)

    assert response.status_code == 404
    assert stored_sets(session) == before
    assert session.query(Workout).count() == 1


def test_largest_storable_id_is_still_a_regular_unknown_id(client, data):
    assert client.get(f"/workouts/{SQLITE_MAX_INTEGER}").status_code == 404
    assert client.post(f"/templates/{SQLITE_MAX_INTEGER}/start").status_code == 404


# Ids in forms


@pytest.mark.parametrize("exercise_id", [HUGE, TOO_LARGE, str(SQLITE_MAX_INTEGER), "0", "-1"])
def test_adding_out_of_range_exercise_id_is_not_found(client, session, data, exercise_id):
    response = client.post(
        f"/workouts/{data['workout_id']}/exercises", data={"exercise_id": exercise_id}, headers=JSON_HEADERS
    )

    assert response.status_code == 404
    assert session.query(WorkoutExercise).count() == 1


@pytest.mark.parametrize("exercise_ids", [[HUGE], [TOO_LARGE], ["{valid}", HUGE], ["0"], ["-5"]])
def test_template_with_out_of_range_exercise_ids_is_rejected_without_saving(client, session, data, exercise_ids):
    exercise_ids = [value.format(valid=data["exercise_id"]) for value in exercise_ids]

    json_response = client.post("/templates", data={"name": "Push", "exercise_ids": exercise_ids}, headers=JSON_HEADERS)
    form_response = client.post("/templates", data={"name": "Push", "exercise_ids": exercise_ids})

    assert json_response.status_code == 400
    assert json_response.get_json() == {
        "error": "A lista de exercícios é inválida. Recarregue a página e tente novamente."
    }
    assert form_response.status_code == 302
    assert form_response.headers["Location"].endswith("/templates/new")
    assert session.query(WorkoutTemplate).count() == 0
    assert session.query(WorkoutTemplateExercise).count() == 0


# Repetitions and weights


@pytest.mark.parametrize(
    ("repetitions", "weight_kg"),
    [
        (HUGE, "10"),
        (TOO_LARGE, "10"),
        ("10", "1e400"),  # was stored as Infinity
        ("10", "1e30"),  # was stored inexactly
        ("10", "1000000"),
        ("10", "999999.991"),
    ],
)
def test_excessive_set_values_are_rejected_without_saving(client, session, data, repetitions, weight_kg):
    before = stored_sets(session)
    url = f"/workouts/{data['workout_id']}/exercises/{data['exercise_id']}/sets"

    added = client.post(url, data={"repetitions": repetitions, "weight_kg": weight_kg}, headers=JSON_HEADERS)
    edited = client.post(
        f"{url}/{data['set_id']}/edit", data={"repetitions": repetitions, "weight_kg": weight_kg}, headers=JSON_HEADERS
    )
    added_by_form = client.post(url, data={"repetitions": repetitions, "weight_kg": weight_kg})

    assert added.status_code == 400
    assert added.get_json() == {"error": SET_ERROR}
    assert edited.status_code == 400
    assert edited.get_json() == {"error": SET_ERROR}
    assert added_by_form.status_code == 200
    assert SET_ERROR in added_by_form.get_data(as_text=True)
    assert stored_sets(session) == before


def test_largest_storable_values_are_accepted(client, session, data):
    url = f"/workouts/{data['workout_id']}/exercises/{data['exercise_id']}/sets"

    response = client.post(
        url, data={"repetitions": str(SQLITE_MAX_INTEGER), "weight_kg": str(MAX_WEIGHT_KG)}, headers=JSON_HEADERS
    )

    assert response.status_code == 200
    assert stored_sets(session)[-1][2:] == (SQLITE_MAX_INTEGER, MAX_WEIGHT_KG)


# Model validation


@pytest.mark.parametrize("field", ["position", "repetitions"])
def test_model_rejects_integers_beyond_sqlite_range(field):
    with pytest.raises(ValueError, match=f"{field} is too large"):
        WorkoutSet(**{field: SQLITE_MAX_INTEGER + 1})


def test_model_rejects_weight_beyond_column_precision():
    with pytest.raises(ValueError, match="weight_kg must be at most 999999.99"):
        WorkoutSet(weight_kg=Decimal("1000000"))
