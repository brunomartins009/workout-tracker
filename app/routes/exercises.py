from flask import Blueprint, render_template
from sqlalchemy import select

from app.database import db
from app.exercise_library import group_exercises
from app.models import Exercise


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
