from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import db
from app.models import Exercise


bp = Blueprint("exercises", __name__, url_prefix="/exercises")


@bp.get("")
def list_exercises():
    exercises = db.session.scalars(select(Exercise).order_by(Exercise.name)).all()
    return render_template("exercises/list.html", exercises=exercises)


@bp.get("/new")
def new_exercise():
    return render_template("exercises/form.html", exercise=None)


@bp.post("")
def create_exercise():
    exercise = Exercise()

    try:
        exercise.name = request.form.get("name", "")
        db.session.add(exercise)
        db.session.commit()
    except ValueError:
        return render_template(
            "exercises/form.html",
            exercise=exercise,
            error="Informe um nome de exercício.",
        ), 200
    except IntegrityError:
        db.session.rollback()
        return render_template(
            "exercises/form.html",
            exercise=exercise,
            error="Já existe um exercício com esse nome.",
        ), 200

    flash("Exercício criado com sucesso.", "success")
    return redirect(url_for("exercises.list_exercises"))


@bp.get("/<int:exercise_id>/edit")
def edit_exercise(exercise_id):
    exercise = _get_exercise_or_404(exercise_id)
    return render_template("exercises/form.html", exercise=exercise)


@bp.post("/<int:exercise_id>/edit")
def update_exercise(exercise_id):
    exercise = _get_exercise_or_404(exercise_id)

    try:
        exercise.name = request.form.get("name", "")
        db.session.commit()
    except ValueError:
        return render_template(
            "exercises/form.html",
            exercise=exercise,
            error="Informe um nome de exercício.",
        ), 200
    except IntegrityError:
        db.session.rollback()
        return render_template(
            "exercises/form.html",
            exercise=exercise,
            error="Já existe um exercício com esse nome.",
        ), 200

    flash("Exercício atualizado com sucesso.", "success")
    return redirect(url_for("exercises.list_exercises"))


@bp.post("/<int:exercise_id>/delete")
def delete_exercise(exercise_id):
    exercise = _get_exercise_or_404(exercise_id)
    db.session.delete(exercise)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Este exercício não pode ser excluído porque possui histórico de treino.", "error")
    else:
        flash("Exercício excluído com sucesso.", "success")

    return redirect(url_for("exercises.list_exercises"))


def _get_exercise_or_404(exercise_id):
    exercise = db.session.get(Exercise, exercise_id)
    if exercise is None:
        abort(404)
    return exercise
