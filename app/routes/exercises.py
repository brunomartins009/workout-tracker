from flask import Blueprint, abort, jsonify, render_template
from sqlalchemy import func, select

from app.database import db
from app.exercise_library import group_exercises
from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


bp = Blueprint("exercises", __name__, url_prefix="/exercises")

# The history table shows only the most recent occurrences; the chart keeps
# the complete history.
HISTORY_TABLE_LIMIT = 5


# The exercise library is read-only in the UI: exercises are managed in
# app/exercise_library.py and loaded with `flask sync-exercise-library`.
@bp.get("")
def list_exercises():
    exercises = db.session.scalars(select(Exercise)).all()
    # Categories are derived from Exercise.muscle_group; group_exercises gives
    # them the same order used everywhere else in the library.
    categories = [
        (group, sum(len(subgroup_exercises) for _, subgroup_exercises in subgroups))
        for group, subgroups in group_exercises(exercises)
    ]
    return render_template(
        "exercises/list.html",
        categories=categories,
        exercise_count=len(exercises),
    )


@bp.get("/<muscle_group>")
def exercise_category(muscle_group):
    exercises = db.session.scalars(
        select(Exercise).where(Exercise.muscle_group == muscle_group)
    ).all()
    if not exercises:
        abort(404)

    # A single group comes back, already ordered by subgroup and then by name.
    [(_, subgroups)] = group_exercises(exercises)
    ordered_exercises = [
        exercise
        for _, subgroup_exercises in subgroups
        for exercise in subgroup_exercises
    ]
    return render_template(
        "exercises/category.html",
        muscle_group=muscle_group,
        exercises=ordered_exercises,
    )


@bp.get("/<int:exercise_id>/history")
def exercise_history(exercise_id):
    """Return the exercise and its occurrences as JSON for the exercise modal."""
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
        .order_by(Workout.date.desc(), Workout.created_at.desc(), Workout.id.desc())
    ).all()

    occurrences = [
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

    # The chart uses every occurrence, oldest first. Points of occurrences
    # without sets are null so the chart does not drop to zero.
    chronological = list(reversed(occurrences))
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
            "exercise": {
                "id": exercise.id,
                "name": exercise.name,
                "muscle_group": exercise.muscle_group,
                "muscle_subgroup": exercise.muscle_subgroup,
            },
            # Most recent first, limited for the table.
            "history": occurrences[:HISTORY_TABLE_LIMIT],
            "chart": chart,
        }
    )
