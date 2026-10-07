from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.database import db
from app.exercise_library import group_exercises
from app.models import Exercise, Workout, WorkoutExercise, WorkoutSet


bp = Blueprint("workouts", __name__, url_prefix="/workouts")


@bp.get("")
def list_workouts():
    # A single aggregate query returns each workout with its counts, so the
    # history page does not issue one extra query per workout (N+1).
    # The outer joins keep workouts that have no exercises or no sets; DISTINCT
    # is needed because joining sets repeats each exercise once per set.
    workout_rows = db.session.execute(
        select(
            Workout,
            func.count(func.distinct(WorkoutExercise.id)).label("exercise_count"),
            func.count(WorkoutSet.id).label("set_count"),
        )
        .outerjoin(WorkoutExercise, WorkoutExercise.workout_id == Workout.id)
        .outerjoin(WorkoutSet, WorkoutSet.workout_exercise_id == WorkoutExercise.id)
        .group_by(Workout.id)
        .order_by(Workout.date.desc(), Workout.id.desc())
    ).all()
    return render_template("workouts/list.html", workout_rows=workout_rows)


@bp.get("/<int:workout_id>")
def workout_detail(workout_id):
    workout = _get_workout_or_404(workout_id)
    return _render_workout_detail(workout)


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

    flash("Treino criado com sucesso.", "success")
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

    flash("Treino atualizado com sucesso.", "success")
    return redirect(url_for("workouts.list_workouts"))


@bp.post("/<int:workout_id>/delete")
def delete_workout(workout_id):
    workout = _get_workout_or_404(workout_id)
    db.session.delete(workout)
    db.session.commit()

    flash("Treino excluído com sucesso.", "success")
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
        flash("Este exercício já foi adicionado ao treino.", "error")
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
        flash("Este exercício já foi adicionado ao treino.", "error")
    else:
        flash("Exercício adicionado ao treino.", "success")

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
    flash("Exercício removido do treino.", "success")
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


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/sets")
def add_workout_set(workout_id, exercise_id):
    workout = _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    repetitions, weight_kg = _set_form_values()

    try:
        last_position = db.session.scalar(
            select(func.max(WorkoutSet.position)).where(
                WorkoutSet.workout_exercise_id == workout_exercise.id
            )
        )
        workout_set = WorkoutSet(
            workout_exercise_id=workout_exercise.id,
            position=(last_position or 0) + 1,
            repetitions=int(repetitions),
            weight_kg=Decimal(weight_kg),
        )
        db.session.add(workout_set)
        db.session.commit()
    except (InvalidOperation, ValueError):
        db.session.rollback()
        return _render_workout_detail(
            workout,
            set_error="Informe repetições positivas e um peso válido com até duas casas decimais.",
            set_form_values={"repetitions": repetitions, "weight_kg": weight_kg},
            failed_workout_exercise_id=workout_exercise.id,
        )
    except IntegrityError:
        db.session.rollback()
        return _render_workout_detail(
            workout,
            set_error="Não foi possível adicionar a série. Tente novamente.",
            set_form_values={"repetitions": repetitions, "weight_kg": weight_kg},
            failed_workout_exercise_id=workout_exercise.id,
        )

    flash("Série adicionada com sucesso.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.get("/<int:workout_id>/exercises/<int:exercise_id>/sets/<int:set_id>/edit")
def edit_workout_set(workout_id, exercise_id, set_id):
    workout = _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    workout_set = _get_workout_set_or_404(workout_exercise.id, set_id)
    return render_template(
        "workouts/set_form.html",
        workout=workout,
        workout_exercise=workout_exercise,
        workout_set=workout_set,
        form_repetitions=workout_set.repetitions,
        form_weight_kg=workout_set.weight_kg,
    )


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/sets/<int:set_id>/edit")
def update_workout_set(workout_id, exercise_id, set_id):
    workout = _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    workout_set = _get_workout_set_or_404(workout_exercise.id, set_id)
    repetitions, weight_kg = _set_form_values()

    try:
        workout_set.repetitions = int(repetitions)
        workout_set.weight_kg = Decimal(weight_kg)
        db.session.commit()
    except (InvalidOperation, ValueError):
        db.session.rollback()
        return _render_set_form_with_error(
            workout,
            workout_exercise,
            workout_set,
            repetitions,
            weight_kg,
        )
    except IntegrityError:
        db.session.rollback()
        return _render_set_form_with_error(
            workout,
            workout_exercise,
            workout_set,
            repetitions,
            weight_kg,
        )

    flash("Série atualizada com sucesso.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/sets/<int:set_id>/delete")
def delete_workout_set(workout_id, exercise_id, set_id):
    _get_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    workout_set = _get_workout_set_or_404(workout_exercise.id, set_id)
    removed_position = workout_set.position
    db.session.delete(workout_set)
    db.session.flush()

    following_sets = db.session.scalars(
        select(WorkoutSet)
        .where(
            WorkoutSet.workout_exercise_id == workout_exercise.id,
            WorkoutSet.position > removed_position,
        )
        .order_by(WorkoutSet.position)
    ).all()
    for following_set in following_sets:
        following_set.position -= 1
        db.session.flush()

    db.session.commit()
    flash("Série excluída com sucesso.", "success")
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


def _get_workout_set_or_404(workout_exercise_id, set_id):
    workout_set = db.session.scalar(
        select(WorkoutSet).where(
            WorkoutSet.id == set_id,
            WorkoutSet.workout_exercise_id == workout_exercise_id,
        )
    )
    if workout_set is None:
        abort(404)
    return workout_set


def _workout_exercises(workout_id):
    return db.session.scalars(
        select(WorkoutExercise)
        .options(
            joinedload(WorkoutExercise.exercise),
            selectinload(WorkoutExercise.sets),
        )
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


def _render_workout_detail(
    workout,
    set_error=None,
    set_form_values=None,
    failed_workout_exercise_id=None,
):
    exercises = db.session.scalars(select(Exercise)).all()
    workout_exercises = _workout_exercises(workout.id)
    # Sets are already loaded by selectinload, so counting them here adds no queries.
    total_sets = sum(len(workout_exercise.sets) for workout_exercise in workout_exercises)
    return render_template(
        "workouts/detail.html",
        workout=workout,
        workout_exercises=workout_exercises,
        total_sets=total_sets,
        exercise_groups=group_exercises(exercises),
        set_error=set_error,
        set_form_values=set_form_values or {},
        # Lets the template show the error and the submitted values only under
        # the exercise whose "add set" form failed, not under every exercise.
        failed_workout_exercise_id=failed_workout_exercise_id,
    )


def _set_form_values():
    return request.form.get("repetitions", ""), request.form.get("weight_kg", "")


def _render_set_form_with_error(
    workout,
    workout_exercise,
    workout_set,
    repetitions,
    weight_kg,
):
    return render_template(
        "workouts/set_form.html",
        workout=workout,
        workout_exercise=workout_exercise,
        workout_set=workout_set,
        form_repetitions=repetitions,
        form_weight_kg=weight_kg,
        error="Informe repetições positivas e um peso válido com até duas casas decimais.",
    ), 200


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
