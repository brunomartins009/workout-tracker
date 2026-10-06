from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.database import db
from app.models import Exercise, Workout, WorkoutExercise


bp = Blueprint("workouts", __name__, url_prefix="/workouts")


@bp.get("")
def list_workouts():
    workouts = db.session.scalars(
        select(Workout).order_by(Workout.date.desc(), Workout.id.desc())
    ).all()
    return render_template("workouts/list.html", workouts=workouts)


@bp.get("/<int:workout_id>")
def workout_detail(workout_id):
    workout = _get_workout_or_404(workout_id)
    workout_exercises = _workout_exercises(workout_id)
    exercises = db.session.scalars(select(Exercise).order_by(Exercise.name)).all()
    return render_template(
        "workouts/detail.html",
        workout=workout,
        workout_exercises=workout_exercises,
        exercises=exercises,
    )


@bp.get("/new")
def new_workout():
    return render_template("workouts/form.html", workout=None, form_date="", form_name="")


@bp.post("")
def create_workout():
    form_date, form_name = _form_values()

    try:
        workout = Workout(date=_parse_date(form_date), name=form_name)
        db.session.add(workout)
        db.session.commit()
    except ValueError:
        return _render_form_with_error(
            workout=None,
            form_date=form_date,
            form_name=form_name,
        )

    flash("Treino criado com sucesso.")
    return redirect(url_for("workouts.list_workouts"))


@bp.get("/<int:workout_id>/edit")
def edit_workout(workout_id):
    workout = _get_workout_or_404(workout_id)
    return render_template(
        "workouts/form.html",
        workout=workout,
        form_date=workout.date.isoformat(),
        form_name=workout.name,
    )


@bp.post("/<int:workout_id>/edit")
def update_workout(workout_id):
    workout = _get_workout_or_404(workout_id)
    form_date, form_name = _form_values()

    try:
        workout.date = _parse_date(form_date)
        workout.name = form_name
        db.session.commit()
    except ValueError:
        return _render_form_with_error(
            workout=workout,
            form_date=form_date,
            form_name=form_name,
        )

    flash("Treino atualizado com sucesso.")
    return redirect(url_for("workouts.list_workouts"))


@bp.post("/<int:workout_id>/delete")
def delete_workout(workout_id):
    workout = _get_workout_or_404(workout_id)
    db.session.delete(workout)
    db.session.commit()

    flash("Treino excluído com sucesso.")
    return redirect(url_for("workouts.list_workouts"))


@bp.post("/<int:workout_id>/exercises")
def add_workout_exercise(workout_id):
    _get_workout_or_404(workout_id)
    exercise_id = request.form.get("exercise_id", type=int)
    exercise = db.session.get(Exercise, exercise_id)
    if exercise is None:
        abort(404)

    existing_workout_exercise = db.session.scalar(
        select(WorkoutExercise).where(
            WorkoutExercise.workout_id == workout_id,
            WorkoutExercise.exercise_id == exercise.id,
        )
    )
    if existing_workout_exercise is not None:
        flash("Este exercício já foi adicionado ao treino.")
        return redirect(url_for("workouts.workout_detail", workout_id=workout_id))

    last_position = db.session.scalar(
        select(func.max(WorkoutExercise.position)).where(
            WorkoutExercise.workout_id == workout_id
        )
    )
    workout_exercise = WorkoutExercise(
        workout_id=workout_id,
        exercise_id=exercise.id,
        position=(last_position or 0) + 1,
    )
    db.session.add(workout_exercise)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Este exercício já foi adicionado ao treino.")
    else:
        flash("Exercício adicionado ao treino.")

    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/delete")
def delete_workout_exercise(workout_id, exercise_id):
    _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    removed_position = workout_exercise.position
    db.session.delete(workout_exercise)
    db.session.flush()

    following_exercises = db.session.scalars(
        select(WorkoutExercise)
        .where(
            WorkoutExercise.workout_id == workout_id,
            WorkoutExercise.position > removed_position,
        )
        .order_by(WorkoutExercise.position)
    ).all()
    for following_exercise in following_exercises:
        following_exercise.position -= 1
        db.session.flush()

    db.session.commit()
    flash("Exercício removido do treino.")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/move-up")
def move_workout_exercise_up(workout_id, exercise_id):
    _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    previous_exercise = db.session.scalar(
        select(WorkoutExercise).where(
            WorkoutExercise.workout_id == workout_id,
            WorkoutExercise.position == workout_exercise.position - 1,
        )
    )
    if previous_exercise is not None:
        _swap_positions(workout_exercise, previous_exercise, workout_id)
        db.session.commit()

    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/move-down")
def move_workout_exercise_down(workout_id, exercise_id):
    _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    next_exercise = db.session.scalar(
        select(WorkoutExercise).where(
            WorkoutExercise.workout_id == workout_id,
            WorkoutExercise.position == workout_exercise.position + 1,
        )
    )
    if next_exercise is not None:
        _swap_positions(workout_exercise, next_exercise, workout_id)
        db.session.commit()

    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


def _get_workout_or_404(workout_id):
    workout = db.session.get(Workout, workout_id)
    if workout is None:
        abort(404)
    return workout


def _get_workout_exercise_or_404(workout_id, exercise_id):
    workout_exercise = db.session.scalar(
        select(WorkoutExercise).where(
            WorkoutExercise.workout_id == workout_id,
            WorkoutExercise.exercise_id == exercise_id,
        )
    )
    if workout_exercise is None:
        abort(404)
    return workout_exercise


def _workout_exercises(workout_id):
    return db.session.scalars(
        select(WorkoutExercise)
        .options(joinedload(WorkoutExercise.exercise))
        .where(WorkoutExercise.workout_id == workout_id)
        .order_by(WorkoutExercise.position)
    ).all()


def _swap_positions(workout_exercise, neighbor_exercise, workout_id):
    original_position = workout_exercise.position
    neighbor_original_position = neighbor_exercise.position
    last_position = db.session.scalar(
        select(func.max(WorkoutExercise.position)).where(
            WorkoutExercise.workout_id == workout_id
        )
    )

    workout_exercise.position = (last_position or 0) + 1
    db.session.flush()
    neighbor_exercise.position = original_position
    db.session.flush()
    workout_exercise.position = neighbor_original_position


def _form_values():
    return request.form.get("date", ""), request.form.get("name", "")


def _parse_date(value):
    if not value:
        raise ValueError("date is required")
    return date.fromisoformat(value)


def _render_form_with_error(workout, form_date, form_name):
    return render_template(
        "workouts/form.html",
        workout=workout,
        form_date=form_date,
        form_name=form_name,
        error="Informe uma data válida e um nome para o treino.",
    ), 200
