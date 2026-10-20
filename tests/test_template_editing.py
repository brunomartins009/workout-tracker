"""Creating templates with targets and editing templates with the same builder."""

import json
import re
import threading
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.models import Exercise, Workout, WorkoutSet, WorkoutTemplate, WorkoutTemplateExercise
from app.routes import workout_templates as template_routes


JSON_HEADERS = {"Accept": "application/json"}
TARGETS_ERROR = "Informe as séries (1 a 20) e as repetições por série (1 a 100) de cada exercício."


def create_exercise(session, name):
    exercise = Exercise(name=name, muscle_group="Peito", muscle_subgroup="Peitoral médio")
    session.add(exercise)
    session.commit()
    return exercise


def create_template(session, name, items):
    template = WorkoutTemplate(name=name)
    for position, (exercise, target_sets, target_repetitions) in enumerate(items, start=1):
        template.template_exercises.append(
            WorkoutTemplateExercise(
                exercise=exercise, position=position, target_sets=target_sets, target_repetitions=target_repetitions
            )
        )
    session.add(template)
    session.commit()
    return template


def stored(session, template_id):
    session.expire_all()
    template = session.get(WorkoutTemplate, template_id)
    return template.name, [
        (item.exercise.name, item.position, item.target_sets, item.target_repetitions)
        for item in template.template_exercises
    ]


def form(name, items):
    """Builder form data: items are (exercise, target_sets, target_repetitions)."""
    return {
        "name": name,
        "exercise_ids": [str(exercise.id) for exercise, _, _ in items],
        "target_sets": [str(target_sets) for _, target_sets, _ in items],
        "target_repetitions": [str(target_repetitions) for _, _, target_repetitions in items],
    }


def initial_items(page):
    match = re.search(r'<script type="application/json" id="template-builder-initial">(.*?)</script>', page, re.DOTALL)
    return json.loads(match.group(1))


@pytest.fixture
def exercises(session):
    return [create_exercise(session, name) for name in ("Supino inclinado", "Crucifixo", "Elevação lateral", "Remada")]


# Creating with targets


def test_create_saves_targets_in_order(client, session, exercises):
    bench, fly, raise_, _ = exercises

    response = client.post("/templates", data=form("Push", [(raise_, 3, 15), (bench, 4, 10), (fly, 3, 12)]), headers=JSON_HEADERS)

    assert response.status_code == 201
    template = session.query(WorkoutTemplate).one()
    assert stored(session, template.id) == (
        "Push",
        [("Elevação lateral", 1, 3, 15), ("Supino inclinado", 2, 4, 10), ("Crucifixo", 3, 3, 12)],
    )


@pytest.mark.parametrize(
    ("target_sets", "target_repetitions"),
    [
        (None, ["10"]),  # missing
        (["4"], None),
        ([], []),
        (["4", "3"], ["10"]),  # one value too many
        ([""], ["10"]),
        (["0"], ["10"]),
        (["21"], ["10"]),
        (["4"], ["0"]),
        (["4"], ["101"]),
        (["-1"], ["10"]),
        (["2.5"], ["10"]),
        (["abc"], ["10"]),
        ([str(10**25)], ["10"]),
    ],
)
def test_create_rejects_missing_or_invalid_targets_without_saving(client, session, exercises, target_sets, target_repetitions):
    data = {"name": "Push", "exercise_ids": [str(exercises[0].id)]}
    if target_sets is not None:
        data["target_sets"] = target_sets
    if target_repetitions is not None:
        data["target_repetitions"] = target_repetitions

    json_response = client.post("/templates", data=data, headers=JSON_HEADERS)
    form_response = client.post("/templates", data=data)

    assert json_response.status_code == 400
    assert json_response.get_json() == {"error": TARGETS_ERROR}
    assert form_response.headers["Location"].endswith("/templates/new")
    assert session.query(WorkoutTemplate).count() == 0
    assert session.query(WorkoutTemplateExercise).count() == 0


@pytest.mark.parametrize(("target_sets", "target_repetitions"), [(1, 1), (20, 100)])
def test_create_accepts_targets_at_the_limits(client, session, exercises, target_sets, target_repetitions):
    response = client.post("/templates", data=form("Push", [(exercises[0], target_sets, target_repetitions)]), headers=JSON_HEADERS)

    assert response.status_code == 201
    assert stored(session, session.query(WorkoutTemplate).one().id)[1] == [("Supino inclinado", 1, target_sets, target_repetitions)]


# Edit page


def test_edit_page_reuses_the_builder_with_current_exercises_and_targets(client, session, exercises):
    bench, fly, _, _ = exercises
    template = create_template(session, "Push", [(fly, 3, 12), (bench, 4, 10)])

    response = client.get(f"/templates/{template.id}/edit")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "<h1>Editar modelo de treino</h1>" in page
    assert re.search(rf'<form\s+id="template-builder-form"\s+action="/templates/{template.id}/edit"\s+method="post"\s+data-template-builder', page)
    assert 'value="Push" required>' in page
    assert "Salvar alterações</button>" in page
    assert initial_items(page) == [
        {"id": fly.id, "name": "Crucifixo", "subgroup": "Peitoral médio", "target_sets": 3, "target_repetitions": 12},
        {"id": bench.id, "name": "Supino inclinado", "subgroup": "Peitoral médio", "target_sets": 4, "target_repetitions": 10},
    ]
    # The same picker, modal and scripts as the new-template page.
    assert "data-builder-show-group" in page
    assert "data-exercise-add>Adicionar</button>" in page
    assert page.index('src="/static/js/sortable_list.js"') < page.index('src="/static/js/template_builder.js"')


def test_new_template_page_starts_empty(client, exercises):
    page = client.get("/templates/new").get_data(as_text=True)

    assert initial_items(page) == []
    assert "<h1>Novo modelo de treino</h1>" in page
    assert "Criar modelo</button>" in page


def test_edit_page_leaves_missing_targets_empty_instead_of_inventing_them(client, session, exercises):
    template = create_template(session, "Antigo", [(exercises[0], None, None)])

    page = client.get(f"/templates/{template.id}/edit").get_data(as_text=True)

    assert initial_items(page)[0]["target_sets"] is None
    assert initial_items(page)[0]["target_repetitions"] is None


def test_edit_page_escapes_names(client, session):
    exercise = create_exercise(session, "Supino </script><script>alert(1)</script>")
    template = create_template(session, 'Push "<b>"', [(exercise, 3, 10)])

    page = client.get(f"/templates/{template.id}/edit").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in page
    assert 'value="Push &#34;&lt;b&gt;&#34;"' in page
    assert initial_items(page)[0]["name"] == "Supino </script><script>alert(1)</script>"


def test_edit_page_of_unknown_template_is_not_found(client):
    assert client.get("/templates/999/edit").status_code == 404
    assert client.post("/templates/999/edit", data={"name": "X"}).status_code == 404


def test_overview_links_to_edit(client, session, exercises):
    template = create_template(session, "Push", [(exercises[0], 3, 10)])

    page = client.get(f"/templates/{template.id}").get_data(as_text=True)

    assert f'href="/templates/{template.id}/edit">Editar' in page


# Saving an edit


def test_edit_changes_name_exercises_order_and_targets(client, session, exercises):
    bench, fly, raise_, row = exercises
    template = create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12), (raise_, 3, 15)])

    # Renamed, fly removed, row added, order changed and targets changed.
    response = client.post(
        f"/templates/{template.id}/edit",
        data=form("  Peito e costas  ", [(row, 4, 8), (bench, 5, 6), (raise_, 2, 20)]),
        headers=JSON_HEADERS,
    )

    assert response.status_code == 200
    assert response.get_json() == {"message": "Modelo atualizado com sucesso.", "redirect_url": f"/templates/{template.id}"}
    assert stored(session, template.id) == (
        "Peito e costas",
        [("Remada", 1, 4, 8), ("Supino inclinado", 2, 5, 6), ("Elevação lateral", 3, 2, 20)],
    )
    assert session.query(WorkoutTemplateExercise).count() == 3


def test_edit_can_swap_the_positions_of_kept_exercises(client, session, exercises):
    # Kept exercises move to positions held by each other in the same commit.
    bench, fly, _, _ = exercises
    template = create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12)])

    response = client.post(f"/templates/{template.id}/edit", data=form("Push", [(fly, 3, 12), (bench, 4, 10)]), headers=JSON_HEADERS)

    assert response.status_code == 200
    assert stored(session, template.id)[1] == [("Crucifixo", 1, 3, 12), ("Supino inclinado", 2, 4, 10)]


def test_edit_message_is_shown_after_redirect(client, session, exercises):
    template = create_template(session, "Push", [(exercises[0], 3, 10)])

    response = client.post(f"/templates/{template.id}/edit", data=form("Push", [(exercises[0], 4, 10)]), follow_redirects=True)

    assert response.request.path == f"/templates/{template.id}"
    assert "Modelo atualizado com sucesso." in response.get_data(as_text=True)


@pytest.mark.parametrize("same_name", ["Push", "push", "  PUSH  "])
def test_edit_may_keep_its_own_name(client, session, exercises, same_name):
    template = create_template(session, "Push", [(exercises[0], 3, 10)])

    response = client.post(f"/templates/{template.id}/edit", data=form(same_name, [(exercises[0], 4, 10)]), headers=JSON_HEADERS)

    assert response.status_code == 200


@pytest.mark.parametrize("other_name", ["Pull", "pull", "  PULL  "])
def test_edit_rejects_the_name_of_another_template(client, session, exercises, other_name):
    create_template(session, "Pull", [(exercises[1], 3, 10)])
    template = create_template(session, "Push", [(exercises[0], 3, 10)])
    before = stored(session, template.id)

    response = client.post(f"/templates/{template.id}/edit", data=form(other_name, [(exercises[0], 4, 10)]), headers=JSON_HEADERS)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Já existe um modelo com este nome."}
    assert stored(session, template.id) == before


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"name": "   ", "exercise_ids": ["{bench}"], "target_sets": ["3"], "target_repetitions": ["10"]}, "Informe um nome para o modelo."),
        ({"name": "Push"}, "Adicione pelo menos um exercício ao modelo."),
        ({"name": "Push", "exercise_ids": ["999"], "target_sets": ["3"], "target_repetitions": ["10"]}, "A lista de exercícios é inválida. Recarregue a página e tente novamente."),
        ({"name": "Push", "exercise_ids": ["{bench}", "{bench}"], "target_sets": ["3", "3"], "target_repetitions": ["10", "10"]}, "A lista de exercícios é inválida. Recarregue a página e tente novamente."),
        ({"name": "Push", "exercise_ids": ["{bench}"], "target_sets": ["0"], "target_repetitions": ["10"]}, TARGETS_ERROR),
        ({"name": "Push", "exercise_ids": ["{bench}"]}, TARGETS_ERROR),
        # Targets go together: only one of them is not accepted.
        ({"name": "Push", "exercise_ids": ["{bench}"], "target_sets": ["4"]}, TARGETS_ERROR),
        ({"name": "Push", "exercise_ids": ["{bench}"], "target_repetitions": ["10"]}, TARGETS_ERROR),
    ],
)
def test_invalid_edit_keeps_the_template_unchanged(client, session, exercises, data, error):
    template = create_template(session, "Push", [(exercises[0], 4, 10), (exercises[1], 3, 12)])
    before = stored(session, template.id)
    data = {
        key: [value.format(bench=exercises[0].id) for value in values] if isinstance(values, list) else values
        for key, values in data.items()
    }

    json_response = client.post(f"/templates/{template.id}/edit", data=data, headers=JSON_HEADERS)
    form_response = client.post(f"/templates/{template.id}/edit", data=data)

    assert json_response.status_code == 400
    assert json_response.get_json() == {"error": error}
    assert form_response.headers["Location"].endswith(f"/templates/{template.id}/edit")
    assert error in client.get(form_response.headers["Location"]).get_data(as_text=True)
    assert stored(session, template.id) == before


def test_edit_failing_at_the_database_changes_nothing(client, session, exercises):
    template = create_template(session, "Push", [(exercises[0], 4, 10), (exercises[1], 3, 12)])
    before = stored(session, template.id)

    def fail(*_args):
        raise IntegrityError("INSERT INTO workout_template_exercises", {}, Exception("CHECK constraint failed"))

    event.listen(WorkoutTemplateExercise, "before_insert", fail)
    try:
        response = client.post(
            f"/templates/{template.id}/edit", data=form("Novo nome", [(exercises[2], 3, 10)]), headers=JSON_HEADERS
        )
    finally:
        event.remove(WorkoutTemplateExercise, "before_insert", fail)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Não foi possível salvar o modelo. Recarregue a página e tente novamente."}
    # The old exercises were deleted in the same transaction, which was rolled back.
    assert stored(session, template.id) == before


# Sessions are never changed by editing their template


def test_editing_a_template_does_not_change_sessions_started_from_it(client, session, exercises):
    bench, fly, raise_, row = exercises
    template = create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12)])
    client.post(f"/templates/{template.id}/start")
    client.post(f"/templates/{template.id}/start")
    in_progress, completed = session.query(Workout).order_by(Workout.id).all()
    session.add(WorkoutSet(workout_exercise=completed.workout_exercises[0], position=1, repetitions=10, weight_kg=Decimal("20")))
    session.commit()
    client.post(f"/workouts/{completed.id}/complete")

    def session_content(workout_id):
        session.expire_all()
        workout = session.get(Workout, workout_id)
        items = sorted(workout.workout_exercises, key=lambda item: item.position)
        return workout.name, workout.date, [
            (item.exercise.name, item.position, item.target_sets, item.target_repetitions, len(item.sets)) for item in items
        ]

    before = {workout_id: session_content(workout_id) for workout_id in (in_progress.id, completed.id)}

    client.post(
        f"/templates/{template.id}/edit",
        data=form("Outro nome", [(row, 2, 20), (raise_, 5, 5)]),
        headers=JSON_HEADERS,
    )

    assert stored(session, template.id)[0] == "Outro nome"
    assert {workout_id: session_content(workout_id) for workout_id in before} == before
    assert before[in_progress.id] == ("Push", date.today(), [("Supino inclinado", 1, 4, 10, 0), ("Crucifixo", 2, 3, 12, 0)])


def test_session_started_after_an_edit_uses_the_new_version(client, session, exercises):
    bench, fly, _, _ = exercises
    template = create_template(session, "Push", [(bench, 4, 10)])
    client.post(f"/templates/{template.id}/edit", data=form("Push B", [(fly, 3, 12), (bench, 5, 5)]), headers=JSON_HEADERS)

    client.post(f"/templates/{template.id}/start")

    workout = session.query(Workout).one()
    assert workout.name == "Push B"
    assert [
        (item.exercise.name, item.position, item.target_sets, item.target_repetitions)
        for item in sorted(workout.workout_exercises, key=lambda item: item.position)
    ] == [("Crucifixo", 1, 3, 12), ("Supino inclinado", 2, 5, 5)]


# Scripts


def test_builder_script_sends_targets_and_reorders_by_dragging(client):
    with client.get("/static/js/template_builder.js") as response:
        builder = response.get_data(as_text=True)
    with client.get("/static/js/sortable_list.js") as response:
        sortable = response.get_data(as_text=True)

    assert 'data.append("target_sets", exercise.targetSets);' in builder
    assert 'data.append("target_repetitions", exercise.targetRepetitions);' in builder
    assert "form.reportValidity()" in builder
    assert "window.SortableList.attach(selectedList" in builder
    # Arrows were replaced by the drag handle (which also answers to the arrow keys).
    assert 'buildActionButton("up"' not in builder
    assert 'buildActionButton("down"' not in builder
    assert 'addEventListener("pointerdown"' in sortable
    assert "setPointerCapture" in sortable
    assert 'addEventListener("pointercancel"' in sortable
    assert '"ArrowUp"' in sortable and '"ArrowDown"' in sortable
    assert ".innerHTML" not in builder and ".innerHTML" not in sortable


def test_drag_handle_does_not_scroll_the_page_on_touch(client):
    with client.get("/static/css/main.css") as response:
        css = response.get_data(as_text=True)

    handle_rule = css[css.index(".drag-handle {"):css.index("}", css.index(".drag-handle {"))]
    assert "touch-action: none;" in handle_rule


# Another request changes the database during an edit
#
# The other request runs in another thread, with its own session and SQLite
# connection, right after this request has validated the form: the
# interleaving where the name, or the template itself, changes between the
# validation and the save.


def run_after_the_validation(app, monkeypatch, method, url, data=None):
    original = template_routes._template_from_form
    statuses = []
    triggered = threading.Event()

    def validate_then_run_other_request(*args, **kwargs):
        result = original(*args, **kwargs)
        # The other request may go through the validation too; only the first
        # call (the edit being tested) starts it.
        if not triggered.is_set():
            triggered.set()

            def send():
                with app.test_client() as other_client:
                    statuses.append(getattr(other_client, method)(url, data=data).status_code)

            thread = threading.Thread(target=send, daemon=True)
            thread.start()
            thread.join(timeout=10)
        return result

    monkeypatch.setattr(template_routes, "_template_from_form", validate_then_run_other_request)
    return statuses


@pytest.mark.parametrize("as_json", [True, False])
def test_name_saved_by_another_request_during_an_edit_is_reported_as_duplicate(app, client, session, monkeypatch, exercises, as_json):
    template = create_template(session, "Push", [(exercises[0], 4, 10)])
    before = stored(session, template.id)
    other = run_after_the_validation(app, monkeypatch, "post", "/templates", form("Pull", [(exercises[1], 3, 12)]))

    response = client.post(
        f"/templates/{template.id}/edit",
        data=form("pull", [(exercises[2], 5, 5)]),
        headers=JSON_HEADERS if as_json else None,
    )

    # The other template was really saved in between.
    assert other == [302]
    if as_json:
        assert response.status_code == 400
        assert response.get_json() == {"error": "Já existe um modelo com este nome."}
    else:
        assert response.status_code == 302
        assert response.headers["Location"].endswith(f"/templates/{template.id}/edit")
        assert "Já existe um modelo com este nome." in client.get(response.headers["Location"]).get_data(as_text=True)
    # Nothing of the edit was saved.
    assert stored(session, template.id) == before
    assert sorted(t.name for t in session.query(WorkoutTemplate).all()) == ["Pull", "Push"]


# SQLAlchemy warns that the old exercise rows were already gone when it tried
# to delete them: expected here, since the other request deleted them.
@pytest.mark.filterwarnings("ignore:DELETE statement on table 'workout_template_exercises'")
@pytest.mark.parametrize("as_json", [True, False])
@pytest.mark.parametrize(
    "new_name",
    [
        "Push B",  # the name changes: the UPDATE finds no row (StaleDataError)
        "Push",  # same name: only the inserts of the exercises fail (foreign key)
    ],
)
def test_template_deleted_by_another_request_during_an_edit_is_not_found(app, client, session, monkeypatch, exercises, new_name, as_json):
    template_id = create_template(session, "Push", [(exercises[0], 4, 10), (exercises[1], 3, 12)]).id
    other = run_after_the_validation(app, monkeypatch, "post", f"/templates/{template_id}/delete")

    response = client.post(
        f"/templates/{template_id}/edit",
        data=form(new_name, [(exercises[2], 5, 5), (exercises[0], 3, 8)]),
        headers=JSON_HEADERS if as_json else None,
    )

    # The deletion was really saved in between.
    assert other == [302]
    assert response.status_code == 404
    session.expire_all()
    assert session.get(WorkoutTemplate, template_id) is None
    # Nothing of the edit was saved: no template and no exercise rows left.
    assert session.query(WorkoutTemplate).count() == 0
    assert session.query(WorkoutTemplateExercise).count() == 0


def test_unexpected_stale_data_error_is_not_hidden(client, session, exercises):
    template = create_template(session, "Push", [(exercises[0], 4, 10)])
    before = stored(session, template.id)

    def fail(*_args):
        raise StaleDataError("UPDATE statement on table 'workout_templates' expected to update 1 row(s); 0 were matched.")

    event.listen(WorkoutTemplate, "before_update", fail)
    try:
        # The template still exists, so this is not a deletion: the error is
        # propagated instead of becoming a 404 (TESTING propagates exceptions).
        with pytest.raises(StaleDataError):
            client.post(f"/templates/{template.id}/edit", data=form("Push B", [(exercises[0], 3, 8)]), headers=JSON_HEADERS)
    finally:
        event.remove(WorkoutTemplate, "before_update", fail)

    assert stored(session, template.id) == before
