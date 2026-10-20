import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, jsonify, make_response, redirect, render_template, request, url_for
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.database import db
from app.exercise_library import group_exercises
from app.models import SQLITE_MAX_INTEGER, Exercise, Workout, WorkoutExercise, WorkoutSet, WorkoutTemplate, utc_now


bp = Blueprint("workouts", __name__, url_prefix="/workouts")

MONTH_NAMES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)
# The calendar weeks start on Sunday and end on Saturday.
WEEKDAY_NAMES = ("Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb")

SET_VALIDATION_ERROR = "Informe repetições positivas e um peso válido com até duas casas decimais."
COMPLETED_WORKOUT_ERROR = "Este treino já foi concluído e não pode mais ser alterado."
COMPLETION_REQUIREMENT_ERROR = "Registre pelo menos uma série em algum exercício antes de concluir o treino."
DUPLICATE_EXERCISE_ERROR = "Este exercício já foi adicionado ao treino."
REORDER_ERROR = "A ordem enviada não corresponde aos exercícios do treino. Recarregue a página e tente novamente."
WORKOUT_FORM_ERROR = "Informe uma data válida e um nome para o treino."
WORKOUT_DATE_ERROR = "Informe uma data válida."
WORKOUT_NAME_ERROR = "Informe um nome para o treino."


@bp.get("")
def list_workouts():
    current_month = date.today().replace(day=1)
    month = _parse_month(request.args.get("month")) or current_month
    next_month = (month + timedelta(days=31)).replace(day=1)
    previous_month = (month - timedelta(days=1)).replace(day=1)

    # Only what the calendar needs: id, date and name of the workouts of the
    # displayed month. Workouts on the same day keep the order used elsewhere
    # (most recently created first, then highest id).
    workouts = db.session.execute(
        select(Workout.id, Workout.date, Workout.name)
        .where(Workout.date >= month, Workout.date < next_month)
        .order_by(Workout.date, Workout.created_at.desc(), Workout.id.desc())
    ).all()
    workouts_by_day = {}
    for workout in workouts:
        workouts_by_day.setdefault(workout.date, []).append(workout)

    # Template cards below the calendar: each opens the template's overview,
    # where the session is started. Alphabetical, like the rest of the app.
    templates = db.session.scalars(
        select(WorkoutTemplate)
        .options(selectinload(WorkoutTemplate.template_exercises))
        .order_by(func.lower(WorkoutTemplate.name), WorkoutTemplate.id)
    ).all()

    return render_template(
        "workouts/list.html",
        month=month,
        month_title=f"{MONTH_NAMES[month.month - 1]} {month.year}",
        # Weeks start on Sunday and include the days of the adjacent months
        # needed to complete the first and last weeks.
        weeks=calendar.Calendar(firstweekday=calendar.SUNDAY).monthdatescalendar(month.year, month.month),
        weekday_names=WEEKDAY_NAMES,
        workouts_by_day=workouts_by_day,
        previous_month_param=_month_param(previous_month),
        next_month_param=_month_param(next_month),
        is_current_month=month == current_month,
        templates=templates,
    )


@bp.get("/<int:workout_id>")
def workout_detail(workout_id):
    workout = _get_workout_or_404(workout_id)
    return _render_workout_detail(workout)


@bp.get("/new")
def new_workout():
    # Sessions are no longer created empty: they are started from a template
    # (POST /templates/<id>/start). The old address leads to the template
    # builder so existing links and bookmarks keep working.
    return redirect(url_for("workout_templates.new_template"))


@bp.get("/<int:workout_id>/edit")
def edit_workout(workout_id):
    workout = _get_in_progress_workout_or_404(workout_id)
    return render_template(
        "workouts/form.html",
        workout=workout,
        form_date=workout.date.isoformat(),
        form_name=workout.name,
    )


@bp.post("/<int:workout_id>/edit")
def update_workout(workout_id):
    """Change the name and/or the date of a session in progress.

    The edit page sends both fields. The workout page changes one at a time
    with fetch() (the name or the date, clicked in its header), so a field
    that is not sent keeps its value. Only this session changes: its template
    and the other sessions are never touched.
    """
    workout = _lock_in_progress_workout_or_404(workout_id)
    form_date = request.form.get("date")
    form_name = request.form.get("name")

    errors = []
    if form_date is None and form_name is None:
        errors.append(WORKOUT_FORM_ERROR)
    if form_date is not None:
        try:
            workout.date = _parse_date(form_date)
        except ValueError:
            errors.append(WORKOUT_DATE_ERROR)
    if form_name is not None:
        try:
            workout.name = form_name
        except ValueError:
            errors.append(WORKOUT_NAME_ERROR)

    if errors:
        db.session.rollback()
        if _wants_json():
            return jsonify({"error": " ".join(errors)}), 400
        return _render_form_with_error(
            workout=workout,
            form_date=form_date if form_date is not None else workout.date.isoformat(),
            form_name=form_name if form_name is not None else workout.name,
        )

    db.session.commit()
    if _wants_json():
        changed = "Nome e data atualizados." if form_date is not None and form_name is not None else (
            "Data atualizada." if form_date is not None else "Nome atualizado."
        )
        return jsonify(
            {
                "message": changed,
                "name": workout.name,
                "date": workout.date.isoformat(),
                "date_label": workout.date.strftime("%d/%m/%Y"),
            }
        )
    flash("Treino atualizado com sucesso.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout.id))


@bp.post("/<int:workout_id>/delete")
def delete_workout(workout_id):
    workout = _get_workout_or_404(workout_id)
    db.session.delete(workout)
    db.session.commit()

    flash("Treino excluído com sucesso.", "success")
    return redirect(url_for("workouts.list_workouts"))


@bp.post("/<int:workout_id>/complete")
def complete_workout(workout_id):
    workout = _get_in_progress_workout_or_404(workout_id)

    # The rule and the change are a single UPDATE: the session is completed
    # only if it is still in progress and has at least one set in any of its
    # exercises at that moment. Checking first and saving afterwards would let
    # a set deleted (or a completion made) in between slip through.
    has_a_set = (
        select(WorkoutSet.id)
        .join(WorkoutSet.workout_exercise)
        .where(WorkoutExercise.workout_id == workout.id)
        .exists()
    )
    result = db.session.execute(
        update(Workout)
        .where(Workout.id == workout.id, Workout.completed_at.is_(None), has_a_set)
        .values(completed_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    # The UPDATE bypasses the already loaded object; read it again when used.
    db.session.expire(workout)
    if result.rowcount != 1:
        db.session.rollback()
        message = COMPLETED_WORKOUT_ERROR if workout.is_completed else COMPLETION_REQUIREMENT_ERROR
        flash(message, "error")
        return redirect(url_for("workouts.workout_detail", workout_id=workout.id))

    db.session.commit()
    flash("Treino concluído.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout.id))


@bp.post("/<int:workout_id>/exercises")
def add_workout_exercise(workout_id):
    workout = _lock_in_progress_workout_or_404(workout_id)
    exercise_id = request.form.get("exercise_id", type=int)
    # A missing, non-numeric or out-of-range id is treated like an unknown
    # exercise (an id beyond the SQLite INTEGER range would make the query fail).
    if exercise_id is None or not 0 < exercise_id <= SQLITE_MAX_INTEGER:
        abort(404)
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
        return _duplicate_exercise_response(workout_id)

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
        return _duplicate_exercise_response(workout_id)

    if _wants_json():
        return _exercises_json_response(
            workout, "Exercício adicionado ao treino.", added_workout_exercise_id=workout_exercise.id
        )
    flash("Exercício adicionado ao treino.", "success")
    # The anchor makes the workout page open (expand) the new exercise.
    return redirect(
        url_for(
            "workouts.workout_detail",
            workout_id=workout_id,
            _anchor=f"exercise-{workout_exercise.id}",
        )
    )


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/delete")
def delete_workout_exercise(workout_id, exercise_id):
    workout = _lock_in_progress_workout_or_404(workout_id)
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
    if _wants_json():
        return _exercises_json_response(workout, "Exercício removido do treino.")
    flash("Exercício removido do treino.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/reorder")
def reorder_workout_exercises(workout_id):
    """Save a new order of the session's exercises (drag and drop on the page).

    The page sends every workout exercise id of the session, in the new order.
    A missing, unknown or repeated id means the page is out of date, and the
    order is left as it was.
    """
    workout = _lock_in_progress_workout_or_404(workout_id)
    workout_exercises = db.session.scalars(
        select(WorkoutExercise).where(WorkoutExercise.workout_id == workout_id)
    ).all()
    by_id = {workout_exercise.id: workout_exercise for workout_exercise in workout_exercises}
    try:
        new_order = [int(value) for value in request.form.getlist("workout_exercise_ids")]
    except ValueError:
        new_order = None
    if new_order is None or len(new_order) != len(by_id) or set(new_order) != set(by_id):
        # Nothing was changed; this also ends the transaction that holds the session.
        db.session.rollback()
        if _wants_json():
            return jsonify({"error": REORDER_ERROR}), 400
        flash(REORDER_ERROR, "error")
        return redirect(url_for("workouts.workout_detail", workout_id=workout_id))

    # Positions are unique within a session, so they are first moved above
    # the current ones and only then set to 1..n.
    highest_position = max((item.position for item in workout_exercises), default=0)
    for index, workout_exercise_id in enumerate(new_order, start=1):
        by_id[workout_exercise_id].position = highest_position + index
    db.session.flush()
    for index, workout_exercise_id in enumerate(new_order, start=1):
        by_id[workout_exercise_id].position = index
    db.session.commit()

    if _wants_json():
        return _exercises_json_response(workout, "Ordem dos exercícios atualizada.")
    flash("Ordem dos exercícios atualizada.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/sets")
def add_workout_set(workout_id, exercise_id):
    workout = _lock_in_progress_workout_or_404(workout_id)
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
        if _wants_json():
            return _set_error_json(SET_VALIDATION_ERROR)
        return _render_workout_detail(
            workout,
            set_error=SET_VALIDATION_ERROR,
            set_form_values={"repetitions": repetitions, "weight_kg": weight_kg},
            failed_workout_exercise_id=workout_exercise.id,
        )
    except IntegrityError:
        db.session.rollback()
        if _wants_json():
            return _set_error_json("Não foi possível adicionar a série. Tente novamente.")
        return _render_workout_detail(
            workout,
            set_error="Não foi possível adicionar a série. Tente novamente.",
            set_form_values={"repetitions": repetitions, "weight_kg": weight_kg},
            failed_workout_exercise_id=workout_exercise.id,
        )

    if _wants_json():
        return _sets_json_response(workout, workout_exercise, "Série adicionada com sucesso.")
    flash("Série adicionada com sucesso.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.get("/<int:workout_id>/exercises/<int:exercise_id>/sets/<int:set_id>/edit")
def edit_workout_set(workout_id, exercise_id, set_id):
    workout = _get_in_progress_workout_or_404(workout_id)
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
    workout = _lock_in_progress_workout_or_404(workout_id)
    workout_exercise = _get_workout_exercise_or_404(workout_id, exercise_id)
    workout_set = _get_workout_set_or_404(workout_exercise.id, set_id)
    repetitions, weight_kg = _set_form_values()

    try:
        workout_set.repetitions = int(repetitions)
        workout_set.weight_kg = Decimal(weight_kg)
        db.session.commit()
    except (InvalidOperation, ValueError, IntegrityError):
        db.session.rollback()
        if _wants_json():
            return _set_error_json(SET_VALIDATION_ERROR)
        return _render_set_form_with_error(
            workout,
            workout_exercise,
            workout_set,
            repetitions,
            weight_kg,
        )

    if _wants_json():
        return _sets_json_response(workout, workout_exercise, "Série atualizada com sucesso.")
    flash("Série atualizada com sucesso.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


@bp.post("/<int:workout_id>/exercises/<int:exercise_id>/sets/<int:set_id>/delete")
def delete_workout_set(workout_id, exercise_id, set_id):
    workout = _lock_in_progress_workout_or_404(workout_id)
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
    if _wants_json():
        return _sets_json_response(workout, workout_exercise, "Série excluída com sucesso.")
    flash("Série excluída com sucesso.", "success")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


def _get_workout_or_404(workout_id):
    workout = db.session.get(Workout, workout_id)
    if workout is None:
        abort(404)
    return workout


def _get_in_progress_workout_or_404(workout_id):
    """Return a workout that can still be changed, or stop the request.

    Completed sessions are read-only. This check alone is used by the pages
    that only show an edit form; routes that change the session use
    _lock_in_progress_workout_or_404, which also holds the session until the
    change is saved.
    """
    workout = _get_workout_or_404(workout_id)
    if workout.is_completed:
        _reject_completed_workout(workout.id)
    return workout


def _lock_in_progress_workout_or_404(workout_id):
    """Return a workout that can still be changed, and keep it so until commit.

    Checking completed_at and saving afterwards is not enough: another request
    could complete the session in between. So every change starts with a
    conditional UPDATE (only while completed_at is NULL), which also records
    when the session last changed. It is the first write of the transaction:
    Python's sqlite3 driver opens the transaction right before it, and SQLite
    allows one writer at a time. From then until commit or rollback, a
    completion of this session waits and afterwards sees this change; a
    completion saved before it leaves no row to update, and the request stops
    without changing anything.
    """
    workout = _get_in_progress_workout_or_404(workout_id)
    result = db.session.execute(
        update(Workout)
        .where(Workout.id == workout.id, Workout.completed_at.is_(None))
        .values(updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        # Completed or deleted by another request after the check above. The
        # rollback expired the loaded workout, and reading it (even its id)
        # would fail if its row is gone, so the row is looked up directly.
        still_exists = db.session.scalar(select(Workout.id).where(Workout.id == workout_id))
        if still_exists is None:
            abort(404)
        _reject_completed_workout(workout_id)
    return workout


def _reject_completed_workout(workout_id):
    """Stop the request: fetch() calls receive a 409 with the message, regular
    forms are redirected back to the workout page."""
    if _wants_json():
        abort(make_response(jsonify({"error": COMPLETED_WORKOUT_ERROR}), 409))
    flash(COMPLETED_WORKOUT_ERROR, "error")
    abort(redirect(url_for("workouts.workout_detail", workout_id=workout_id)))


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


def _wants_json():
    # The set and exercise forms on the workout page are sent with fetch()
    # asking for JSON, so the page can be updated without reloading. A regular form submission
    # (no JavaScript) asks for HTML and keeps the redirect/re-render behaviour.
    return (
        request.accept_mimetypes.best_match(["text/html", "application/json"])
        == "application/json"
    )


def _sets_json_response(workout, workout_exercise, message):
    """Return the re-rendered sets area of one exercise after a set change.

    The HTML comes from the same template used by the full page, so the sets
    markup exists in a single place.
    """
    # Reload from the database so the fragment shows exactly what a page reload
    # would: positions renumbered after a delete and weights normalized by the
    # column (a set saved as "22.5" is stored and shown as 22.50).
    db.session.expire_all()
    total_sets = db.session.scalar(
        select(func.count(WorkoutSet.id))
        .join(WorkoutSet.workout_exercise)
        .where(WorkoutExercise.workout_id == workout.id)
    )
    return jsonify(
        {
            "message": message,
            "sets_html": render_template(
                "partials/workout_exercise_sets.html",
                workout=workout,
                workout_exercise=workout_exercise,
                set_error=None,
                set_form_values={},
                failed_workout_exercise_id=None,
            ),
            "total_sets": total_sets,
            # The card header shows the recorded sets against the target.
            "progress_html": render_template(
                "partials/exercise_progress.html", workout_exercise=workout_exercise
            ),
        }
    )


def _set_error_json(message):
    return jsonify({"error": message}), 400


def _exercises_json_response(workout, message, added_workout_exercise_id=None):
    """Return the re-rendered exercise list after an exercise is added, removed or moved.

    The whole list is returned because these changes renumber the positions
    shown in every card. The HTML comes from the same template used by the
    full page.
    """
    # Reload from the database so the list shows the order and positions as stored.
    db.session.expire_all()
    workout_exercises = _workout_exercises(workout.id)
    return jsonify(
        {
            "message": message,
            "exercises_html": render_template(
                "partials/workout_exercise_list.html",
                workout=workout,
                workout_exercises=workout_exercises,
                set_error=None,
                set_form_values={},
                failed_workout_exercise_id=None,
            ),
            "exercise_count": len(workout_exercises),
            "total_sets": sum(len(workout_exercise.sets) for workout_exercise in workout_exercises),
            # Lets the page open the exercise that was just added.
            "added_workout_exercise_id": added_workout_exercise_id,
        }
    )


def _duplicate_exercise_response(workout_id):
    if _wants_json():
        return jsonify({"error": DUPLICATE_EXERCISE_ERROR}), 400
    flash(DUPLICATE_EXERCISE_ERROR, "error")
    return redirect(url_for("workouts.workout_detail", workout_id=workout_id))


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
        error=SET_VALIDATION_ERROR,
    ), 200


def _parse_month(value):
    """Parse ?month=YYYY-MM. Invalid values return None (the current month is shown)."""
    if not value:
        return None
    try:
        month = datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        return None
    # The calendar links to the previous and next months, which must be valid dates.
    if not date.min.year < month.year < date.max.year:
        return None
    return month


def _month_param(month):
    return f"{month.year:04d}-{month.month:02d}"


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
        error=WORKOUT_FORM_ERROR,
    ), 200
