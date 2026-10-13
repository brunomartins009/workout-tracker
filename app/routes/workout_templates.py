from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.database import db
from app.exercise_library import group_exercises
from app.models import SQLITE_MAX_INTEGER, Exercise, Workout, WorkoutExercise, WorkoutTemplate, WorkoutTemplateExercise


bp = Blueprint("workout_templates", __name__, url_prefix="/templates")

NAME_REQUIRED_ERROR = "Informe um nome para o modelo."
NAME_TAKEN_ERROR = "Já existe um modelo com este nome."
EXERCISES_REQUIRED_ERROR = "Adicione pelo menos um exercício ao modelo."
INVALID_EXERCISES_ERROR = "A lista de exercícios é inválida. Recarregue a página e tente novamente."
CREATE_FAILED_ERROR = "Não foi possível criar o modelo. Recarregue a página e tente novamente."


@bp.get("")
def list_templates():
    templates = db.session.scalars(
        select(WorkoutTemplate)
        .options(
            selectinload(WorkoutTemplate.template_exercises).joinedload(WorkoutTemplateExercise.exercise)
        )
        .order_by(func.lower(WorkoutTemplate.name), WorkoutTemplate.id)
    ).all()
    return render_template("workout_templates/list.html", templates=templates)


@bp.get("/new")
def new_template():
    """Template builder: name, exercise picker and the selected exercises.

    Every muscle group and its exercises are rendered in this one page, so the
    picker can move between groups without reloading and losing the selection,
    which lives only in the page (template_builder.js) until "Criar modelo".
    """
    exercises = db.session.scalars(select(Exercise)).all()
    # Same order as the library: groups, then subgroups, then names.
    muscle_groups = [
        (
            muscle_group,
            [exercise for _, subgroup_exercises in subgroups for exercise in subgroup_exercises],
        )
        for muscle_group, subgroups in group_exercises(exercises)
    ]
    return render_template("workout_templates/new.html", muscle_groups=muscle_groups)


@bp.post("")
def create_template():
    """Create a template from a name and an ordered list of exercise ids.

    The builder page sends `name` and one `exercise_ids` value per selected
    exercise, in the chosen order. The template and all its exercises are
    saved in a single commit, so a failure never leaves a partial template.
    """
    name = request.form.get("name", "").strip()
    raw_exercise_ids = request.form.getlist("exercise_ids")

    error = _template_error(name, raw_exercise_ids)
    if error is None:
        template = WorkoutTemplate(name=name)
        for position, exercise_id in enumerate(raw_exercise_ids, start=1):
            template.template_exercises.append(
                WorkoutTemplateExercise(exercise_id=int(exercise_id), position=position)
            )
        db.session.add(template)
        try:
            db.session.commit()
        except IntegrityError:
            # The unique index on the normalized name is the final guarantee,
            # e.g. if the same name is submitted twice at the same time. Any
            # other constraint failure gets a generic message instead.
            db.session.rollback()
            error = NAME_TAKEN_ERROR if _name_taken(name) else CREATE_FAILED_ERROR

    if error is not None:
        if _wants_json():
            return jsonify({"error": error}), 400
        flash(error, "error")
        return redirect(url_for("workout_templates.new_template"))

    message = "Modelo criado com sucesso."
    # Also flashed for fetch(): the builder then opens redirect_url, which shows it.
    flash(message, "success")
    if _wants_json():
        return jsonify(
            {"message": message, "redirect_url": url_for("workout_templates.list_templates")}
        ), 201
    return redirect(url_for("workout_templates.list_templates"))


@bp.post("/<int:template_id>/delete")
def delete_template(template_id):
    template = _get_template_or_404(template_id)
    # Only the template and its exercise list are removed; sessions started
    # from it are independent copies and stay untouched.
    db.session.delete(template)
    db.session.commit()

    flash("Modelo excluído com sucesso.", "success")
    return redirect(url_for("workout_templates.list_templates"))


@bp.post("/<int:template_id>/start")
def start_workout(template_id):
    """Start a new session today, copying the template's name and exercises."""
    template = _get_template_or_404(template_id)

    workout = Workout(date=date.today(), name=template.name)
    for position, template_exercise in enumerate(template.template_exercises, start=1):
        workout.workout_exercises.append(
            WorkoutExercise(exercise_id=template_exercise.exercise_id, position=position)
        )
    db.session.add(workout)
    db.session.commit()

    flash("Treino iniciado.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout.id))


def _template_error(name, raw_exercise_ids):
    """Return the message explaining why the template cannot be created, or None."""
    if not name:
        return NAME_REQUIRED_ERROR
    if not raw_exercise_ids:
        return EXERCISES_REQUIRED_ERROR

    try:
        exercise_ids = [int(exercise_id) for exercise_id in raw_exercise_ids]
    except ValueError:
        return INVALID_EXERCISES_ERROR
    # Ids beyond the SQLite INTEGER range cannot exist and would make the query fail.
    if not all(0 < exercise_id <= SQLITE_MAX_INTEGER for exercise_id in exercise_ids):
        return INVALID_EXERCISES_ERROR
    # The builder never sends the same exercise twice or an unknown one, so
    # either means a stale page or a hand-made request.
    if len(set(exercise_ids)) != len(exercise_ids):
        return INVALID_EXERCISES_ERROR
    existing_count = db.session.scalar(
        select(func.count(Exercise.id)).where(Exercise.id.in_(exercise_ids))
    )
    if existing_count != len(exercise_ids):
        return INVALID_EXERCISES_ERROR

    if _name_taken(name):
        return NAME_TAKEN_ERROR
    return None


def _name_taken(name):
    # Same normalization as the unique index: trimmed and case-insensitive.
    return db.session.scalar(
        select(WorkoutTemplate.id).where(
            func.lower(func.trim(WorkoutTemplate.name)) == func.lower(name)
        )
    ) is not None


def _get_template_or_404(template_id):
    template = db.session.get(WorkoutTemplate, template_id)
    if template is None:
        abort(404)
    return template


def _wants_json():
    # The builder page submits with fetch() asking for JSON, so a validation
    # error keeps the name and the selection that live only in the page.
    return (
        request.accept_mimetypes.best_match(["text/html", "application/json"])
        == "application/json"
    )
