from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from app.database import db
from app.models import Workout


bp = Blueprint("workouts", __name__, url_prefix="/workouts")


@bp.get("")
def list_workouts():
    workouts = db.session.scalars(
        select(Workout).order_by(Workout.date.desc(), Workout.id.desc())
    ).all()
    return render_template("workouts/list.html", workouts=workouts)


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


def _get_workout_or_404(workout_id):
    workout = db.session.get(Workout, workout_id)
    if workout is None:
        abort(404)
    return workout


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
