from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.database import db
from app.exercise_library import group_exercises
from app.models import (
    SQLITE_MAX_INTEGER,
    TARGET_REPETITIONS_MAX,
    TARGET_SETS_MAX,
    Exercise,
    Workout,
    WorkoutExercise,
    WorkoutTemplate,
    WorkoutTemplateExercise,
    targets_are_paired,
)


bp = Blueprint("workout_templates", __name__, url_prefix="/templates")

NAME_REQUIRED_ERROR = "Informe um nome para o modelo."
NAME_TAKEN_ERROR = "Já existe um modelo com este nome."
EXERCISES_REQUIRED_ERROR = "Adicione pelo menos um exercício ao modelo."
INVALID_EXERCISES_ERROR = "A lista de exercícios é inválida. Recarregue a página e tente novamente."
TARGETS_ERROR = (
    f"Informe as séries (1 a {TARGET_SETS_MAX}) e as repetições por série "
    f"(1 a {TARGET_REPETITIONS_MAX}) de cada exercício."
)
CREATE_FAILED_ERROR = "Não foi possível criar o modelo. Recarregue a página e tente novamente."
UPDATE_FAILED_ERROR = "Não foi possível salvar o modelo. Recarregue a página e tente novamente."
INCOMPLETE_TARGETS_ERROR = (
    "Este modelo tem metas incompletas. Edite o modelo e informe as séries e as repetições de cada exercício."
)


@bp.get("")
def list_templates():
    # The templates are listed as cards below the calendar; this address,
    # used before, leads there so links and bookmarks keep working.
    return redirect(url_for("workouts.list_workouts", _anchor="modelos"))


@bp.get("/<int:template_id>")
def template_overview(template_id):
    """A template before starting it: its exercises, in order, with targets.

    Starting, editing and deleting are explicit buttons (and deleting asks for
    confirmation), so viewing a template never changes it or starts a session.
    """
    template = db.session.scalar(
        select(WorkoutTemplate)
        .options(
            selectinload(WorkoutTemplate.template_exercises).joinedload(WorkoutTemplateExercise.exercise)
        )
        .where(WorkoutTemplate.id == template_id)
    )
    if template is None:
        abort(404)
    return render_template("workout_templates/overview.html", template=template)


@bp.get("/new")
def new_template():
    return _render_builder()


@bp.post("")
def create_template():
    """Create a template from the builder form.

    The template and all its exercises are saved in a single commit, so a
    failure never leaves a partial template.
    """
    name, items, error = _template_from_form()
    if error is None:
        template = WorkoutTemplate(name=name)
        _add_items(template, items)
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
        return _error_response(error, url_for("workout_templates.new_template"))
    return _saved_response("Modelo criado com sucesso.", 201, template.id)


@bp.get("/<int:template_id>/edit")
def edit_template(template_id):
    return _render_builder(_get_template_or_404(template_id))


@bp.post("/<int:template_id>/edit")
def update_template(template_id):
    """Replace the name and the exercise list of a template.

    Only the template changes: sessions keep the copies they made when they
    started. The new list replaces the old one in a single commit.
    """
    template = _get_template_or_404(template_id)
    name, items, error = _template_from_form(excluding_template_id=template.id)
    if error is None:
        # The first flush already writes the new name, so it belongs to the
        # same error handling as the commit: another request may have saved
        # the same name, or deleted the template, after the validation above.
        try:
            template.name = name
            template.template_exercises.clear()
            # The old rows are deleted before the new ones are inserted, otherwise
            # an exercise kept in the template would collide with itself in the
            # unique constraints (template, exercise) and (template, position).
            db.session.flush()
            _add_items(template, items)
            db.session.commit()
        except StaleDataError:
            # Raised when the UPDATE of the name finds no row. If the template
            # still exists, it is not the expected case, so it is not hidden.
            db.session.rollback()
            if _template_exists(template_id):
                raise
            abort(404)
        except IntegrityError:
            db.session.rollback()
            # Deleted meanwhile: with an unchanged name, only the inserts of its
            # exercises fail (foreign key), so this is checked first.
            if not _template_exists(template_id):
                abort(404)
            error = NAME_TAKEN_ERROR if _name_taken(name, excluding_template_id=template_id) else UPDATE_FAILED_ERROR

    if error is not None:
        return _error_response(error, url_for("workout_templates.edit_template", template_id=template_id))
    return _saved_response("Modelo atualizado com sucesso.", 200, template_id)


@bp.post("/<int:template_id>/delete")
def delete_template(template_id):
    template = _get_template_or_404(template_id)
    # Only the template and its exercise list are removed; sessions started
    # from it are independent copies and stay untouched.
    db.session.delete(template)
    db.session.commit()

    flash("Modelo excluído com sucesso.", "success")
    return redirect(url_for("workouts.list_workouts", _anchor="modelos"))


@bp.post("/<int:template_id>/start")
def start_workout(template_id):
    """Start a new session today, copying the template's name, exercises and targets."""
    template = _get_template_or_404(template_id)
    # The builder always saves both targets, but a template saved otherwise
    # could have only one; the model refuses to copy such a pair into a session.
    if not all(
        targets_are_paired(item.target_sets, item.target_repetitions) for item in template.template_exercises
    ):
        flash(INCOMPLETE_TARGETS_ERROR, "error")
        return redirect(url_for("workout_templates.template_overview", template_id=template.id))

    workout = Workout(date=date.today(), name=template.name)
    # Values are copied, so later changes to the template never reach the session.
    for position, template_exercise in enumerate(template.template_exercises, start=1):
        workout.workout_exercises.append(
            WorkoutExercise(
                exercise_id=template_exercise.exercise_id,
                position=position,
                target_sets=template_exercise.target_sets,
                target_repetitions=template_exercise.target_repetitions,
            )
        )
    db.session.add(workout)
    db.session.commit()

    flash("Treino iniciado.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout.id))


def _render_builder(template=None):
    """Template builder, used to create a template and to edit one.

    Every muscle group and its exercises are rendered in this one page, so the
    picker can move between groups without reloading and losing the selection,
    which lives only in the page (template_builder.js) until it is saved.
    When editing, the current exercises and targets are the initial selection.
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
    initial_items = [
        {
            "id": item.exercise_id,
            "name": item.exercise.name,
            "subgroup": item.exercise.muscle_subgroup,
            # None for exercises saved before targets existed: the builder
            # asks for them instead of inventing values.
            "target_sets": item.target_sets,
            "target_repetitions": item.target_repetitions,
        }
        for item in (template.template_exercises if template is not None else [])
    ]
    return render_template(
        "workout_templates/form.html",
        template=template,
        muscle_groups=muscle_groups,
        initial_items=initial_items,
        target_sets_max=TARGET_SETS_MAX,
        target_repetitions_max=TARGET_REPETITIONS_MAX,
    )


def _template_from_form(excluding_template_id=None):
    """Read and validate the builder form.

    The builder sends `name` and, for each selected exercise in the chosen
    order, one `exercise_ids`, one `target_sets` and one `target_repetitions`
    value. Returns (name, items, error), where items are
    (exercise_id, target_sets, target_repetitions) tuples in order.
    """
    name = request.form.get("name", "").strip()
    raw_exercise_ids = request.form.getlist("exercise_ids")
    if not name:
        return name, [], NAME_REQUIRED_ERROR
    if not raw_exercise_ids:
        return name, [], EXERCISES_REQUIRED_ERROR

    exercise_ids = _exercise_ids(raw_exercise_ids)
    if exercise_ids is None:
        return name, [], INVALID_EXERCISES_ERROR

    target_sets = _targets(request.form.getlist("target_sets"), len(exercise_ids), TARGET_SETS_MAX)
    target_repetitions = _targets(
        request.form.getlist("target_repetitions"), len(exercise_ids), TARGET_REPETITIONS_MAX
    )
    if target_sets is None or target_repetitions is None:
        return name, [], TARGETS_ERROR

    if _name_taken(name, excluding_template_id):
        return name, [], NAME_TAKEN_ERROR
    return name, list(zip(exercise_ids, target_sets, target_repetitions)), None


def _exercise_ids(raw_exercise_ids):
    """The ids as integers, or None if any is invalid, repeated or unknown."""
    try:
        exercise_ids = [int(exercise_id) for exercise_id in raw_exercise_ids]
    except ValueError:
        return None
    # Ids beyond the SQLite INTEGER range cannot exist and would make the query fail.
    if not all(0 < exercise_id <= SQLITE_MAX_INTEGER for exercise_id in exercise_ids):
        return None
    # The builder never sends the same exercise twice or an unknown one, so
    # either means a stale page or a hand-made request.
    if len(set(exercise_ids)) != len(exercise_ids):
        return None
    existing_count = db.session.scalar(
        select(func.count(Exercise.id)).where(Exercise.id.in_(exercise_ids))
    )
    if existing_count != len(exercise_ids):
        return None
    return exercise_ids


def _targets(raw_values, expected_count, maximum):
    """One whole number from 1 to `maximum` per exercise, or None.

    Targets are required when a template is saved from the builder; the
    database only allows them to be missing for templates saved before
    targets existed.
    """
    if len(raw_values) != expected_count:
        return None
    try:
        values = [int(value) for value in raw_values]
    except ValueError:
        return None
    if not all(1 <= value <= maximum for value in values):
        return None
    return values


def _add_items(template, items):
    for position, (exercise_id, target_sets, target_repetitions) in enumerate(items, start=1):
        template.template_exercises.append(
            WorkoutTemplateExercise(
                exercise_id=exercise_id,
                position=position,
                target_sets=target_sets,
                target_repetitions=target_repetitions,
            )
        )


def _name_taken(name, excluding_template_id=None):
    # Same normalization as the unique index: trimmed and case-insensitive.
    query = select(WorkoutTemplate.id).where(
        func.lower(func.trim(WorkoutTemplate.name)) == func.lower(name)
    )
    if excluding_template_id is not None:
        query = query.where(WorkoutTemplate.id != excluding_template_id)
    return db.session.scalar(query) is not None


def _error_response(error, form_url):
    if _wants_json():
        return jsonify({"error": error}), 400
    flash(error, "error")
    return redirect(form_url)


def _saved_response(message, json_status, template_id):
    # Also flashed for fetch(): the builder then opens redirect_url (the
    # template's overview), which shows it.
    flash(message, "success")
    redirect_url = url_for("workout_templates.template_overview", template_id=template_id)
    if _wants_json():
        return jsonify({"message": message, "redirect_url": redirect_url}), json_status
    return redirect(redirect_url)


def _template_exists(template_id):
    # Looked up directly: after a rollback the loaded template is expired, and
    # reading it would fail if its row is gone.
    return db.session.scalar(select(WorkoutTemplate.id).where(WorkoutTemplate.id == template_id)) is not None


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
