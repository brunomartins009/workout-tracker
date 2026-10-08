from flask import Blueprint, abort, jsonify, render_template
from sqlalchemy import func, select

from app.database import db
from app.exercise_library import group_exercises
from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


bp = Blueprint("exercises", __name__, url_prefix="/exercises")


# The exercise library is read-only in the UI: exercises are managed in
# app/exercise_library.py and loaded with `flask sync-exercise-library`.
@bp.get("")
def list_exercises():
    exercises = db.session.scalars(select(Exercise)).all()
    return render_template(
        "exercises/list.html",
        exercise_groups=group_exercises(exercises),
        exercise_count=len(exercises),
    )


@bp.get("/<int:exercise_id>/history")
def exercise_history(exercise_id):
    """Return every occurrence of the exercise as JSON for the history modal."""
    exercise = db.session.get(Exercise, exercise_id)
    if exercise is None:
        abort(404)

    # One row per WorkoutExercise (an occurrence of the exercise in a workout),
    # so two workouts on the same date stay separate. The aggregates run in the
    # database; the outer join keeps occurrences that have no sets yet.
    rows = db.session.execute(
        select(
            Workout.id,
            Workout.date,
            Workout.name,
            func.count(WorkoutSet.id),
            func.coalesce(func.sum(WorkoutSet.repetitions), 0),
            func.max(WorkoutSet.weight_kg),
        )
        .join(WorkoutExercise, WorkoutExercise.workout_id == Workout.id)
        .outerjoin(WorkoutSet, WorkoutSet.workout_exercise_id == WorkoutExercise.id)
        .where(WorkoutExercise.exercise_id == exercise.id)
        .group_by(WorkoutExercise.id)
        .order_by(Workout.date.desc(), Workout.created_at.desc())
    ).all()

    history = [
        {
            "workout_id": workout_id,
            "date": workout_date.isoformat(),
            "workout_name": workout_name,
            "sets": set_count,
            "repetitions": total_repetitions,
            # None when the occurrence has no sets yet; shown as "—" and as a
            # gap in the chart instead of a misleading zero.
            "max_weight_kg": float(max_weight) if max_weight is not None else None,
        }
        for workout_id, workout_date, workout_name, set_count, total_repetitions, max_weight in rows
    ]

    # The chart reads the same occurrences as the table, oldest first. Points of
    # occurrences without sets are null so the chart does not drop to zero.
    chronological = list(reversed(history))
    chart = {
        "labels": [occurrence["date"] for occurrence in chronological],
        "workout_names": [occurrence["workout_name"] for occurrence in chronological],
        "repetitions": [
            occurrence["repetitions"] if occurrence["sets"] else None
            for occurrence in chronological
        ],
        "max_weight_kg": [occurrence["max_weight_kg"] for occurrence in chronological],
    }

    return jsonify(
        {
            "exercise": {"id": exercise.id, "name": exercise.name},
            "history": history,
            "chart": chart,
        }
    )
