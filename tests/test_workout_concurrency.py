"""A session completed by one request cannot be changed by another one.

These tests use a second thread, which has its own scoped session and its own
SQLite connection, so they exercise the real transaction and locking behaviour
of SQLite instead of a simulation inside a single session.
"""

import threading
import time
from datetime import date
from decimal import Decimal

import pytest

from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet
from app.routes import workouts as workout_routes


JSON_HEADERS = {"Accept": "application/json"}
COMPLETED_ERROR = "Este treino já foi concluído e não pode mais ser alterado."


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def add_exercise(session, workout, exercise, position, sets=()):
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
    return workout_exercise


def session_content(session, workout_id):
    """What a change could touch: name, date, exercises, positions and sets."""
    session.expire_all()
    workout = session.get(Workout, workout_id)
    items = sorted(workout.workout_exercises, key=lambda item: item.position)
    return {
        "workout": (workout.name, workout.date),
        "exercises": [(item.id, item.exercise_id, item.position) for item in items],
        "sets": sorted(
            (set_.id, set_.workout_exercise_id, set_.position, set_.repetitions, set_.weight_kg)
            for item in items
            for set_ in item.sets
        ),
    }


def run_in_other_thread(app, method, url):
    """Send a request from another thread (another session and connection)."""
    outcome = {}

    def send():
        with app.test_client() as other_client:
            outcome["status"] = getattr(other_client, method)(url).status_code

    thread = threading.Thread(target=send, daemon=True)
    thread.start()
    return thread, outcome


@pytest.fixture
def workout(session):
    workout = Workout(date=date(2026, 10, 8), name="Push")
    session.add(workout)
    session.commit()
    bench = create_exercise(session, "Supino")
    fly = create_exercise(session, "Crucifixo")
    row = create_exercise(session, "Remada")
    bench_item = add_exercise(session, workout, bench, 1, sets=[(10, "20"), (8, "22.5")])
    fly_item = add_exercise(session, workout, fly, 2, sets=[(12, "10")])
    return {
        "workout_id": workout.id,
        "bench_id": bench.id,
        "fly_id": fly.id,
        "row_id": row.id,
        "set_id": bench_item.sets[0].id,
        "bench_item_id": bench_item.id,
        "fly_item_id": fly_item.id,
    }


MUTATIONS = {
    "edit name and date": ("/workouts/{workout_id}/edit", {"date": "2026-10-20", "name": "Outro nome"}),
    "add exercise": ("/workouts/{workout_id}/exercises", {"exercise_id": "{row_id}"}),
    "remove exercise": ("/workouts/{workout_id}/exercises/{bench_id}/delete", {}),
    "reorder exercises": ("/workouts/{workout_id}/exercises/reorder", {"workout_exercise_ids": ["{fly_item_id}", "{bench_item_id}"]}),
    "add set": ("/workouts/{workout_id}/exercises/{bench_id}/sets", {"repetitions": "5", "weight_kg": "30"}),
    "edit set": ("/workouts/{workout_id}/exercises/{bench_id}/sets/{set_id}/edit", {"repetitions": "1", "weight_kg": "99"}),
    "delete set": ("/workouts/{workout_id}/exercises/{bench_id}/sets/{set_id}/delete", {}),
}


def fill_form(data, values):
    """Form data with {placeholders} replaced; a list sends several values."""
    return {
        key: [item.format(**values) for item in value] if isinstance(value, list) else value.format(**values)
        for key, value in data.items()
    }


def request_elsewhere_after_the_check(app, monkeypatch, url):
    """Send `url` from another request right after this request has checked
    that the session is in progress, which is the interleaving found in the
    audit (check first, save afterwards). Returns the other request's status."""
    original = workout_routes._get_workout_or_404
    statuses = []
    triggered = threading.Event()

    def load_then_request_elsewhere(requested_id):
        loaded = original(requested_id)
        # The other request loads the workout through here too; only the
        # first call (the change being tested) starts it.
        if not triggered.is_set():
            triggered.set()
            thread, outcome = run_in_other_thread(app, "post", url)
            thread.join(timeout=10)
            statuses.append(outcome.get("status"))
        return loaded

    monkeypatch.setattr(workout_routes, "_get_workout_or_404", load_then_request_elsewhere)
    return statuses


def complete_after_the_check(app, monkeypatch, workout_id):
    return request_elsewhere_after_the_check(app, monkeypatch, f"/workouts/{workout_id}/complete")


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_change_is_refused_when_session_is_completed_after_the_check(app, client, session, monkeypatch, workout, mutation):
    url, data = MUTATIONS[mutation]
    before = session_content(session, workout["workout_id"])
    completions = complete_after_the_check(app, monkeypatch, workout["workout_id"])

    response = client.post(
        url.format(**workout),
        data=fill_form(data, workout),
        headers=JSON_HEADERS,
    )

    # The completion really happened in between (another connection, committed).
    assert completions == [302]
    assert response.status_code == 409
    assert response.get_json() == {"error": COMPLETED_ERROR}
    assert session_content(session, workout["workout_id"]) == before
    assert session.get(Workout, workout["workout_id"]).is_completed


def test_audit_interleaving_with_regular_form_keeps_the_completed_session_intact(app, client, session, monkeypatch, workout):
    # The case found in the audit: deleting a set while the session is
    # completed elsewhere used to leave a completed session without that set.
    before = session_content(session, workout["workout_id"])
    complete_after_the_check(app, monkeypatch, workout["workout_id"])

    response = client.post(MUTATIONS["delete set"][0].format(**workout))

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/workouts/{workout['workout_id']}")
    assert COMPLETED_ERROR in client.get(response.headers["Location"]).get_data(as_text=True)
    assert session_content(session, workout["workout_id"]) == before
    assert session.query(WorkoutSet).count() == 3


def test_completion_waits_for_a_change_in_progress_and_then_sees_it(app, client, session, monkeypatch):
    # The other order: the change already holds the session when the
    # completion arrives. Deleting the only set must make the completion fail,
    # never leave a completed session without sets.
    workout = Workout(date=date(2026, 10, 8), name="Push")
    session.add(workout)
    session.commit()
    bench = create_exercise(session, "Supino")
    item = add_exercise(session, workout, bench, 1, sets=[(10, "20")])
    workout_id, set_id = workout.id, item.sets[0].id

    original = workout_routes._lock_in_progress_workout_or_404
    observed = {}

    def lock_then_let_completion_try(requested_id):
        locked = original(requested_id)
        thread, outcome = run_in_other_thread(app, "post", f"/workouts/{workout_id}/complete")
        time.sleep(0.5)
        # Still running: the completion is waiting for this transaction.
        observed.update(thread=thread, outcome=outcome, waiting=thread.is_alive())
        return locked

    monkeypatch.setattr(workout_routes, "_lock_in_progress_workout_or_404", lock_then_let_completion_try)

    response = client.post(
        f"/workouts/{workout_id}/exercises/{bench.id}/sets/{set_id}/delete", headers=JSON_HEADERS
    )
    observed["thread"].join(timeout=10)

    assert response.status_code == 200
    assert observed["waiting"] is True
    assert observed["outcome"]["status"] == 302
    session.expire_all()
    stored = session.get(Workout, workout_id)
    # The completion ran after the deletion and refused a session without sets.
    assert stored.completed_at is None
    assert session.query(WorkoutSet).count() == 0


def test_change_after_completion_check_records_the_last_change(client, session, workout):
    # Both values are read from the database (stored without time zone).
    session.expire_all()
    before = session.get(Workout, workout["workout_id"]).updated_at

    client.post(MUTATIONS["delete set"][0].format(**workout), headers=JSON_HEADERS)

    session.expire_all()
    assert session.get(Workout, workout["workout_id"]).updated_at > before


def test_failed_change_does_not_touch_the_session(client, session, workout):
    session.expire_all()
    stored = session.get(Workout, workout["workout_id"])
    before = (stored.updated_at, session_content(session, workout["workout_id"]))

    response = client.post(
        f"/workouts/{workout['workout_id']}/exercises/{workout['bench_id']}/sets",
        data={"repetitions": "0", "weight_kg": "10"},
        headers=JSON_HEADERS,
    )

    assert response.status_code == 400
    session.expire_all()
    stored = session.get(Workout, workout["workout_id"])
    assert (stored.updated_at, session_content(session, workout["workout_id"])) == before


# A session deleted by another request during the change


def session_rows(session):
    session.expire_all()
    return {
        "workouts": session.query(Workout).count(),
        "workout_exercises": session.query(WorkoutExercise).count(),
        "sets": session.query(WorkoutSet).count(),
        "exercises": session.query(Exercise).count(),
    }


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_change_to_a_session_deleted_after_the_check_is_not_found(app, client, session, monkeypatch, workout, mutation):
    url, data = MUTATIONS[mutation]
    deletions = request_elsewhere_after_the_check(app, monkeypatch, f"/workouts/{workout['workout_id']}/delete")

    response = client.post(
        url.format(**workout),
        data=fill_form(data, workout),
        headers=JSON_HEADERS,
    )

    # The deletion really happened in between (another connection, committed).
    assert deletions == [302]
    assert response.status_code == 404
    # Only the deletion took effect: no row of the change was written.
    assert session_rows(session) == {"workouts": 0, "workout_exercises": 0, "sets": 0, "exercises": 3}


def test_regular_form_for_a_session_deleted_after_the_check_is_not_found(app, client, session, monkeypatch, workout):
    request_elsewhere_after_the_check(app, monkeypatch, f"/workouts/{workout['workout_id']}/delete")

    response = client.post(
        MUTATIONS["add set"][0].format(**workout), data={"repetitions": "5", "weight_kg": "30"}
    )

    assert response.status_code == 404
    assert session_rows(session) == {"workouts": 0, "workout_exercises": 0, "sets": 0, "exercises": 3}
