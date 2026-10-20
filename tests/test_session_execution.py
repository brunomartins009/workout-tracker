"""The session (execution) page: name and date in place, targets and progress."""

import re
from datetime import date
from html.parser import HTMLParser

import pytest

from app.models import Exercise, Workout, WorkoutTemplate, WorkoutTemplateExercise


JSON_HEADERS = {"Accept": "application/json"}
COMPLETED_ERROR = "Este treino já foi concluído e não pode mais ser alterado."


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


def start(client, session, template):
    client.post(f"/templates/{template.id}/start")
    return session.query(Workout).order_by(Workout.id.desc()).first()


def stored(session, workout_id):
    session.expire_all()
    workout = session.get(Workout, workout_id)
    return workout.name, workout.date


def card_of(page, exercise_name):
    start_index = page.index(f'<span class="exercise-toggle-name">{exercise_name}</span>')
    card_start = page.rindex('<li class="panel exercise-card"', 0, start_index)
    return page[card_start:page.index("</li>", page.index("data-sets", card_start))]


class RenderedElement(HTMLParser):
    """The first element with `tag` (and `attribute`, if given) in rendered HTML.

    Collects its attributes and two texts: what is seen (without visually
    hidden text) and what screen readers read (without aria-hidden content).
    """

    VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self, tag, attribute=None, value=None):
        super().__init__()
        self.tag, self.attribute, self.value = tag, attribute, value
        self.attrs = None
        # (aria-hidden, visually hidden) of each open element inside the target.
        self.open_elements = []
        self.finished = False
        self.seen_parts, self.read_parts = [], []

    def matches(self, tag, attrs):
        if tag != self.tag:
            return False
        if self.attribute is None:
            return True
        return self.attribute in attrs and (self.value is None or attrs[self.attribute] == self.value)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.finished:
            return
        if self.attrs is None:
            if self.matches(tag, attrs):
                self.attrs = attrs
                self.open_elements.append((attrs.get("aria-hidden") == "true", False))
            return
        if tag in self.VOID_ELEMENTS:
            return
        aria_hidden, visually_hidden = self.open_elements[-1]
        self.open_elements.append(
            (
                aria_hidden or attrs.get("aria-hidden") == "true",
                visually_hidden or "visually-hidden" in (attrs.get("class") or "").split(),
            )
        )

    def handle_endtag(self, tag):
        if self.attrs is None or self.finished:
            return
        self.open_elements.pop()
        self.finished = not self.open_elements

    def handle_data(self, data):
        if self.attrs is None or self.finished:
            return
        aria_hidden, visually_hidden = self.open_elements[-1]
        if not visually_hidden:
            self.seen_parts.append(data)
        if not aria_hidden:
            self.read_parts.append(data)

    @property
    def seen(self):
        return " ".join("".join(self.seen_parts).split())

    @property
    def read(self):
        return " ".join("".join(self.read_parts).split())


def rendered_element(html, tag, attribute=None, value=None):
    element = RenderedElement(tag, attribute, value)
    element.feed(html)
    assert element.attrs is not None, f"no <{tag}> with {attribute}={value!r}"
    return element


def progress_text(html):
    return rendered_element(html, "span", "data-progress").seen


def progress_read_text(html):
    """The progress as screen readers read it, from text in the badge: an
    aria-label on the span (no role) would not be reliably read."""
    badge = rendered_element(html, "span", "data-progress")
    assert "aria-label" not in badge.attrs
    return badge.read


def sets_url(workout, exercise):
    return f"/workouts/{workout.id}/exercises/{exercise.id}/sets"


@pytest.fixture
def exercises(session):
    return [create_exercise(session, name) for name in ("Supino inclinado", "Crucifixo", "Remada")]


@pytest.fixture
def template(session, exercises):
    bench, fly, _ = exercises
    return create_template(session, "Push", [(bench, 4, 10), (fly, 3, 12)])


# Name and date, changed in place


def test_changing_only_the_date(client, session, template):
    workout = start(client, session, template)
    other = start(client, session, template)

    response = client.post(f"/workouts/{workout.id}/edit", data={"date": "2026-10-02"}, headers=JSON_HEADERS)

    assert response.status_code == 200
    assert response.get_json() == {
        "message": "Data atualizada.",
        "name": "Push",
        "date": "2026-10-02",
        "date_label": "02/10/2026",
    }
    assert stored(session, workout.id) == ("Push", date(2026, 10, 2))
    # Other sessions and the template are not changed.
    assert stored(session, other.id) == ("Push", date.today())
    assert session.get(WorkoutTemplate, template.id).name == "Push"


def test_changing_only_the_name(client, session, template):
    workout = start(client, session, template)
    other = start(client, session, template)

    response = client.post(f"/workouts/{workout.id}/edit", data={"name": "  Push pesado  "}, headers=JSON_HEADERS)

    assert response.status_code == 200
    assert response.get_json()["message"] == "Nome atualizado."
    assert response.get_json()["name"] == "Push pesado"
    assert stored(session, workout.id) == ("Push pesado", date.today())
    assert stored(session, other.id) == ("Push", date.today())
    session.expire_all()
    assert session.get(WorkoutTemplate, template.id).name == "Push"


def test_changing_both_fields_at_once(client, session, template):
    workout = start(client, session, template)

    response = client.post(f"/workouts/{workout.id}/edit", data={"date": "2026-09-30", "name": "Pull"}, headers=JSON_HEADERS)

    assert response.get_json()["message"] == "Nome e data atualizados."
    assert stored(session, workout.id) == ("Pull", date(2026, 9, 30))


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"date": ""}, "Informe uma data válida."),
        ({"date": "abc"}, "Informe uma data válida."),
        ({"date": "2026-13-01"}, "Informe uma data válida."),
        ({"date": "2026-02-30"}, "Informe uma data válida."),
        ({"name": ""}, "Informe um nome para o treino."),
        ({"name": "   "}, "Informe um nome para o treino."),
        ({"date": "x", "name": " "}, "Informe uma data válida. Informe um nome para o treino."),
        ({"date": "2026-10-02", "name": " "}, "Informe um nome para o treino."),
        ({}, "Informe uma data válida e um nome para o treino."),
    ],
)
def test_invalid_values_change_nothing(client, session, template, data, error):
    workout = start(client, session, template)
    before = stored(session, workout.id)

    response = client.post(f"/workouts/{workout.id}/edit", data=data, headers=JSON_HEADERS)

    assert response.status_code == 400
    assert response.get_json() == {"error": error}
    assert stored(session, workout.id) == before


def test_regular_form_still_works_without_javascript(client, session, template):
    workout = start(client, session, template)

    saved = client.post(f"/workouts/{workout.id}/edit", data={"date": "2026-10-03"})
    invalid = client.post(f"/workouts/{workout.id}/edit", data={"date": "abc"})

    assert saved.status_code == 302
    assert saved.headers["Location"].endswith(f"/workouts/{workout.id}")
    assert invalid.status_code == 200
    page = invalid.get_data(as_text=True)
    assert "Informe uma data válida e um nome para o treino." in page
    # What was typed is kept, and the name field keeps the saved name.
    assert 'value="abc"' in page
    assert 'value="Push"' in page
    assert stored(session, workout.id) == ("Push", date(2026, 10, 3))


@pytest.mark.parametrize("data", [{"date": "2026-10-02"}, {"name": "Outro"}])
def test_completed_session_keeps_its_name_and_date(client, session, template, exercises, data):
    workout = start(client, session, template)
    client.post(sets_url(workout, exercises[0]), data={"repetitions": "10", "weight_kg": "20"})
    client.post(f"/workouts/{workout.id}/complete")
    before = stored(session, workout.id)

    json_response = client.post(f"/workouts/{workout.id}/edit", data=data, headers=JSON_HEADERS)
    form_response = client.post(f"/workouts/{workout.id}/edit", data=data)

    assert json_response.status_code == 409
    assert json_response.get_json() == {"error": COMPLETED_ERROR}
    assert form_response.status_code == 302
    assert stored(session, workout.id) == before


def test_new_date_moves_the_session_in_the_calendar(client, session, template):
    workout = start(client, session, template)

    client.post(f"/workouts/{workout.id}/edit", data={"date": "2025-12-31"}, headers=JSON_HEADERS)

    december = client.get("/workouts?month=2025-12").get_data(as_text=True)
    today = client.get(f"/workouts?month={date.today():%Y-%m}").get_data(as_text=True)
    assert f'href="/workouts/{workout.id}"' in december
    assert 'data-date="2025-12-31"' in december
    assert f'href="/workouts/{workout.id}"' not in today


def test_in_progress_page_offers_name_and_date_in_place(client, session, template):
    workout = start(client, session, template)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)
    header = page.split('<header class="page-header">')[1].split("</header>")[0]

    assert "Editar treino" not in header
    assert 'data-inline-edit-open="session-name-form"' in header
    assert 'data-inline-edit-open="session-date-form"' in header
    # Screen readers read the name and the date, followed by the action: no
    # aria-label replaces them, in the buttons or in the heading.
    name_button = rendered_element(header, "button", "data-inline-edit-open", "session-name-form")
    date_button = rendered_element(header, "button", "data-inline-edit-open", "session-date-form")
    assert "aria-label" not in name_button.attrs
    assert "aria-label" not in date_button.attrs
    assert name_button.read == "Push (alterar o nome)"
    assert date_button.read == f"{date.today().strftime('%d/%m/%Y')} (alterar a data)"
    assert rendered_element(header, "h1").read == "Push (alterar o nome)"
    # What is seen stays the name and the date only.
    assert name_button.seen == "Push"
    assert date_button.seen == date.today().strftime("%d/%m/%Y")
    assert f'<form class="inline-edit-form" id="session-date-form" action="/workouts/{workout.id}/edit" method="post" data-inline-edit hidden>' in header
    assert f'<input id="session-date-input" name="date" type="date" value="{date.today().isoformat()}" required>' in header
    assert '<input id="session-name-input" name="name" type="text" value="Push"' in header
    assert f'<a href="/workouts/{workout.id}/edit">Alterar nome e data</a>' in header  # without JavaScript
    # The name in the delete dialog is updated together with the title.
    assert page.count("<span data-session-name>Push</span>") == 2


def test_completed_page_shows_name_and_date_as_plain_text(client, session, template, exercises):
    workout = start(client, session, template)
    client.post(sets_url(workout, exercises[0]), data={"repetitions": "10", "weight_kg": "20"})
    client.post(f"/workouts/{workout.id}/complete")

    header = client.get(f"/workouts/{workout.id}").get_data(as_text=True).split('<header class="page-header">')[1].split("</header>")[0]

    assert "<h1>Push</h1>" in header
    assert "data-inline-edit" not in header
    assert "/edit" not in header


# Targets and progress


def test_exercise_cards_show_targets_and_progress(client, session, template, exercises):
    workout = start(client, session, template)

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    bench_card = card_of(page, "Supino inclinado")
    assert '<span class="exercise-toggle-target">Meta: 4 séries × 10 repetições</span>' in bench_card
    assert progress_text(bench_card) == "0/4 séries"
    assert progress_read_text(bench_card) == "0 séries registradas de 4 planejadas"
    assert progress_text(card_of(page, "Crucifixo")) == "0/3 séries"


def test_progress_counts_recorded_sets_after_each_change(client, session, template, exercises):
    bench = exercises[0]
    workout = start(client, session, template)

    progress = []
    for repetitions in ("10", "6", "12", "3", "8"):  # any repetitions count as a recorded set
        response = client.post(sets_url(workout, bench), data={"repetitions": repetitions, "weight_kg": "20"}, headers=JSON_HEADERS)
        assert response.status_code == 200
        progress.append(progress_text(response.get_json()["progress_html"]))
        if repetitions == "10":
            # Only the sets are counted: one set, whatever its repetitions.
            assert progress_read_text(response.get_json()["progress_html"]) == "1 série registrada de 4 planejadas"
    set_id = session.get(Workout, workout.id).workout_exercises[0].sets[0].id
    deleted = client.post(f"{sets_url(workout, bench)}/{set_id}/delete", headers=JSON_HEADERS)

    # More sets than planned are allowed and shown as they are.
    assert progress == ["1/4 séries", "2/4 séries", "3/4 séries", "4/4 séries", "5/4 séries"]
    assert progress_text(deleted.get_json()["progress_html"]) == "4/4 séries"
    assert progress_read_text(deleted.get_json()["progress_html"]) == "4 séries registradas de 4 planejadas"
    assert deleted.get_json()["total_sets"] == 4
    edited = client.post(
        f"{sets_url(workout, bench)}/{session.get(Workout, workout.id).workout_exercises[0].sets[0].id}/edit",
        data={"repetitions": "1", "weight_kg": "20"},
        headers=JSON_HEADERS,
    )
    assert progress_text(edited.get_json()["progress_html"]) == "4/4 séries"


def test_each_set_shows_the_target_repetitions_as_reference(client, session, template, exercises):
    bench = exercises[0]
    workout = start(client, session, template)
    for repetitions in ("10", "7"):
        client.post(sets_url(workout, bench), data={"repetitions": repetitions, "weight_kg": "20"})

    card = card_of(client.get(f"/workouts/{workout.id}").get_data(as_text=True), "Supino inclinado")

    assert '<th scope="col" class="numeric">Meta</th>' in card
    rows = re.findall(r'<td class="set-repetitions numeric">(\d+)</td>\s*<td class="set-target numeric">([^<]+)</td>', card)
    # The column header (Meta) and the Repetições column give the unit, as in
    # the hint of the first set's field: only the number is shown.
    assert rows == [("10", "10"), ("7", "10")]
    assert 'colspan="5"' in card


def test_first_set_starts_with_the_target_repetitions(client, session, template, exercises):
    bench = exercises[0]
    workout = start(client, session, template)

    first = card_of(client.get(f"/workouts/{workout.id}").get_data(as_text=True), "Supino inclinado")
    client.post(sets_url(workout, bench), data={"repetitions": "8", "weight_kg": "20"})
    session.expire_all()
    second = card_of(client.get(f"/workouts/{workout.id}").get_data(as_text=True), "Supino inclinado")

    assert f'name="repetitions" type="number" min="1" inputmode="numeric" value="10" required' in first
    assert '<span class="label-hint">(meta 10)</span>' in first
    # Later sets repeat the previous set, as before.
    assert f'name="repetitions" type="number" min="1" inputmode="numeric" value="8" required' in second


def test_exercises_without_targets_show_only_the_count(client, session, exercises):
    bench, fly, row = exercises
    old_template = create_template(session, "Antigo", [(bench, None, None)])
    workout = start(client, session, old_template)
    client.post(f"/workouts/{workout.id}/exercises", data={"exercise_id": fly.id})
    client.post(sets_url(workout, bench), data={"repetitions": "10", "weight_kg": "20"})

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    bench_card = card_of(page, "Supino inclinado")
    assert progress_text(bench_card) == "1 série"
    assert progress_read_text(bench_card) == "1 série registrada, sem meta"
    assert "exercise-toggle-target" not in bench_card
    assert "set-target" not in bench_card
    assert '<th scope="col" class="numeric">Meta</th>' not in bench_card
    assert progress_text(card_of(page, "Crucifixo")) == "0 séries"


def test_exercise_list_answers_keep_targets_and_progress(client, session, template, exercises):
    bench, fly, _ = exercises
    workout = start(client, session, template)
    client.post(sets_url(workout, bench), data={"repetitions": "10", "weight_kg": "20"})

    items = sorted(session.get(Workout, workout.id).workout_exercises, key=lambda item: item.position)
    html = client.post(
        f"/workouts/{workout.id}/exercises/reorder",
        data={"workout_exercise_ids": [str(items[1].id), str(items[0].id)]},
        headers=JSON_HEADERS,
    ).get_json()["exercises_html"]

    assert progress_text(card_of(html, "Supino inclinado")) == "1/4 séries"
    assert "Meta: 3 séries × 12 repetições" in card_of(html, "Crucifixo")


def test_completed_session_still_shows_targets_and_progress(client, session, template, exercises):
    workout = start(client, session, template)
    client.post(sets_url(workout, exercises[0]), data={"repetitions": "10", "weight_kg": "20"})
    client.post(f"/workouts/{workout.id}/complete")

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert progress_text(card_of(page, "Supino inclinado")) == "1/4 séries"
    assert "Meta: 4 séries × 10 repetições" in page
    assert progress_text(card_of(page, "Crucifixo")) == "0/3 séries"


def test_singular_forms_of_target_and_progress(client, session, exercises):
    workout = start(client, session, create_template(session, "Curto", [(exercises[0], 1, 1)]))

    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert "Meta: 1 série × 1 repetição" in page
    assert progress_text(page) == "0/1 série"
    assert progress_read_text(page) == "0 séries registradas de 1 planejada"

    client.post(sets_url(workout, exercises[0]), data={"repetitions": "1", "weight_kg": "20"})
    session.expire_all()
    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    assert progress_text(page) == "1/1 série"
    assert progress_read_text(page) == "1 série registrada de 1 planejada"
    assert '<td class="set-target numeric">1</td>' in page


def test_targets_are_written_the_same_way_in_the_template_and_in_the_session(client, session, exercises):
    template = create_template(session, "Misto", [(exercises[0], 4, 10), (exercises[1], 1, 1), (exercises[2], 1, 12)])
    overview = client.get(f"/templates/{template.id}").get_data(as_text=True)
    workout = start(client, session, template)
    page = client.get(f"/workouts/{workout.id}").get_data(as_text=True)

    expected = ["4 séries × 10 repetições", "1 série × 1 repetição", "1 série × 12 repetições"]
    overview_targets = [
        " ".join(text.split())
        for text in re.findall(r'<span class="target-summary">(.*?)</span>', re.sub(r"</?strong>", "", overview), re.S)
    ]
    session_targets = re.findall(r'<span class="exercise-toggle-target">Meta: ([^<]+)</span>', page)
    assert overview_targets == expected
    assert session_targets == expected


# Scripts


def test_page_script_updates_progress_and_session_details(client):
    with client.get("/static/js/workouts.js") as response:
        script = response.get_data(as_text=True)

    assert "replaceProgress(card, result.data.progress_html);" in script
    assert "setUpSessionDetails();" in script
    assert 'element.textContent = details.name;' in script
    assert 'element.textContent = details.date_label;' in script
    assert "input.value = input.defaultValue;" in script
    assert ".innerHTML" not in script


def test_hidden_inline_forms_are_not_displayed(client):
    # The inline edit forms are flex containers; without this rule the hidden
    # attribute would be overridden and both forms would show on page load.
    with client.get("/static/css/main.css") as response:
        css = response.get_data(as_text=True).replace("\r\n", "\n")

    rule = css[css.index("[hidden] {"):css.index("}", css.index("[hidden] {"))]
    assert "display: none !important;" in rule
    assert ".inline-edit-form {\n  display: flex;" in css
