import re
from datetime import date, datetime, timezone

from app.models import Workout
from app.routes.workouts import MONTH_NAMES


def create_workout(session, workout_date, name="Push", created_at=None):
    workout = Workout(date=workout_date, name=name)
    if created_at is not None:
        workout.created_at = created_at
    session.add(workout)
    session.commit()
    return workout


def get_calendar(client, month=None):
    url = "/workouts" if month is None else f"/workouts?month={month}"
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def day_cell(page, iso_date):
    """Return the markup of the highlighted day (link or button) for a date."""
    match = re.search(rf'<(a|button)\s[^>]*data-date="{iso_date}"[^>]*>.*?</\1>', page, re.DOTALL)
    return match.group(0) if match else None


def day_template(page, iso_date):
    match = re.search(rf'<template id="day-{iso_date}">(.*?)</template>', page, re.DOTALL)
    return match.group(1) if match else None


def highlighted_dates(page):
    return re.findall(r'class="calendar-day calendar-day-workout"[^>]*data-date="([^"]+)"', page)


# Page structure


def test_workouts_page_shows_calendar_and_new_workout_action(client):
    page = get_calendar(client, "2026-10")

    assert "<h1>Treinos</h1>" in page
    assert 'href="/workouts/new"' in page
    assert "+ Novo treino" in page
    assert re.findall(r"<th scope=\"col\">([^<]+)</th>", page) == ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    assert '<h2 id="calendar-title">Outubro 2026</h2>' in page


def test_workouts_page_no_longer_lists_workouts(client, session):
    create_workout(session, date(2026, 10, 8), "Push")

    page = get_calendar(client, "2026-10")

    assert "<table class=\"data-table\">" not in page
    assert "Editar</a>" not in page
    assert "/delete" not in page


def test_calendar_opens_on_current_month(client):
    today = date.today()

    page = get_calendar(client)

    assert f'<h2 id="calendar-title">{MONTH_NAMES[today.month - 1]} {today.year}</h2>' in page
    assert "Ir para o mês atual" not in page


def test_calendar_grid_starts_on_monday_and_completes_weeks_with_adjacent_days(client):
    page = get_calendar(client, "2026-10")
    first_row = page.split("<tbody>")[1].split("</tr>")[0]

    # October 2026 starts on a Thursday: Monday 28/09 to Sunday 04/10.
    assert re.findall(r">(\d+)</span>", first_row) == ["28", "29", "30", "1", "2", "3", "4"]
    assert first_row.count("calendar-day-outside") == 3
    assert page.split("<tbody>")[1].count("<tr>") == 5


# Navigation


def test_calendar_links_to_previous_and_next_month(client):
    page = get_calendar(client, "2026-10")

    assert 'href="/workouts?month=2026-09" aria-label="Mês anterior"' in page
    assert 'href="/workouts?month=2026-11" aria-label="Mês seguinte"' in page


def test_calendar_navigation_crosses_year_boundaries(client):
    january = get_calendar(client, "2026-01")
    december = get_calendar(client, "2026-12")

    assert '<h2 id="calendar-title">Janeiro 2026</h2>' in january
    assert 'href="/workouts?month=2025-12" aria-label="Mês anterior"' in january
    assert '<h2 id="calendar-title">Dezembro 2026</h2>' in december
    assert 'href="/workouts?month=2027-01" aria-label="Mês seguinte"' in december


def test_calendar_offers_way_back_to_current_month(client):
    page = get_calendar(client, "2020-03")

    assert '<a href="/workouts">Ir para o mês atual</a>' in page


def test_invalid_month_falls_back_to_current_month(client):
    today = date.today()
    expected_title = f'<h2 id="calendar-title">{MONTH_NAMES[today.month - 1]} {today.year}</h2>'

    for invalid in ("abc", "2026-13", "2026", "0001-01", "9999-12"):
        assert expected_title in get_calendar(client, invalid)


# Highlighted days


def test_month_without_workouts_has_no_highlighted_days(client, session):
    create_workout(session, date(2026, 10, 8))

    page = get_calendar(client, "2026-08")

    assert highlighted_dates(page) == []
    assert "<template" not in page


def test_only_days_with_workouts_are_highlighted(client, session):
    create_workout(session, date(2026, 10, 8))
    create_workout(session, date(2026, 10, 20))

    page = get_calendar(client, "2026-10")

    assert highlighted_dates(page) == ["2026-10-08", "2026-10-20"]
    assert '<span class="calendar-day">9</span>' in page


def test_day_with_one_workout_links_to_that_workout(client, session):
    workout = create_workout(session, date(2026, 10, 8), "Push")

    cell = day_cell(get_calendar(client, "2026-10"), "2026-10-08")

    assert cell.startswith("<a")
    assert f'href="/workouts/{workout.id}"' in cell
    assert 'aria-label="08/10/2026: Push"' in cell


def test_day_with_several_workouts_opens_dialog_instead_of_navigating(client, session):
    create_workout(session, date(2026, 10, 8), "Push")
    create_workout(session, date(2026, 10, 8), "Upper")

    page = get_calendar(client, "2026-10")
    cell = day_cell(page, "2026-10-08")

    assert cell.startswith("<button")
    assert 'type="button"' in cell
    assert "href=" not in cell
    assert 'aria-haspopup="dialog"' in cell
    assert 'data-day-workouts="day-2026-10-08"' in cell
    assert 'data-day-label="08/10/2026"' in cell
    assert "2 treinos" in cell


def test_dialog_content_lists_every_workout_of_the_day_with_links(client, session):
    push = create_workout(session, date(2026, 10, 8), "Push")
    upper = create_workout(session, date(2026, 10, 8), "Upper")
    other_day = create_workout(session, date(2026, 10, 9), "Legs")

    template = day_template(get_calendar(client, "2026-10"), "2026-10-08")

    cards = re.findall(r'href="/workouts/(\d+)">\s*<span class="library-card-title">([^<]+)</span>', template)
    assert sorted(cards) == sorted([(str(push.id), "Push"), (str(upper.id), "Upper")])
    assert f"/workouts/{other_day.id}" not in template


def test_workouts_of_the_same_day_follow_creation_time_then_id(client, session):
    morning = datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc)
    evening = datetime(2026, 10, 8, 19, 0, tzinfo=timezone.utc)
    created_last = create_workout(session, date(2026, 10, 8), "Criado por último", created_at=evening)
    same_moment_first = create_workout(session, date(2026, 10, 8), "Mesmo instante 1", created_at=morning)
    same_moment_second = create_workout(session, date(2026, 10, 8), "Mesmo instante 2", created_at=morning)

    template = day_template(get_calendar(client, "2026-10"), "2026-10-08")

    # Same rule as the rest of the app: most recently created first, then highest id.
    names = re.findall(r'<span class="library-card-title">([^<]+)</span>', template)
    assert names == [created_last.name, same_moment_second.name, same_moment_first.name]


def test_workouts_of_other_months_are_not_shown(client, session):
    september = create_workout(session, date(2026, 9, 30), "Setembro")
    november = create_workout(session, date(2026, 11, 1), "Novembro")
    october = create_workout(session, date(2026, 10, 15), "Outubro")

    page = get_calendar(client, "2026-10")

    # 30/09 and 01/11 appear in the grid, but only as plain adjacent days.
    assert highlighted_dates(page) == ["2026-10-15"]
    assert f"/workouts/{september.id}" not in page
    assert f"/workouts/{november.id}" not in page
    assert f"/workouts/{october.id}" in page


# Dialog of a day with several workouts


def test_calendar_page_has_day_dialog_and_script(client):
    page = get_calendar(client, "2026-10")

    dialog = page.split('<dialog class="modal modal-small" id="day-workouts-dialog"')[1].split("</dialog>")[0]
    assert 'aria-labelledby="day-workouts-title"' in dialog
    assert '<h2 id="day-workouts-title">Treinos de <span data-day-workouts-label></span></h2>' in dialog
    assert 'data-day-workouts-close aria-label="Fechar">×</button>' in dialog
    assert "data-day-workouts-list" in dialog
    assert 'src="/static/js/workouts.js"' in page
    # The calendar does not need the chart library.
    assert "chart.umd.min.js" not in page


def test_workout_names_with_html_are_escaped_in_the_calendar(client, session):
    create_workout(session, date(2026, 10, 8), "Upper <b>teste</b>")
    create_workout(session, date(2026, 10, 8), "Push")
    create_workout(session, date(2026, 10, 9), "Legs <i>x</i>")

    page = get_calendar(client, "2026-10")

    assert "<b>teste</b>" not in page
    assert "<i>x</i>" not in page
    assert "Upper &lt;b&gt;teste&lt;/b&gt;" in day_template(page, "2026-10-08")
    assert 'aria-label="09/10/2026: Legs &lt;i&gt;x&lt;/i&gt;"' in page


def test_calendar_script_copies_escaped_cards_and_closes_like_other_modals(client):
    script = client.get("/static/js/workouts.js").get_data(as_text=True)

    assert "template.content.cloneNode(true)" in script
    assert "label.textContent = button.dataset.dayLabel" in script
    assert "dialog.showModal()" in script
    assert "event.target === dialog" in script
    assert '[data-day-workouts-close]' in script
    # Closed before following a workout card link.
    assert 'event.target.closest("a")' in script
    assert ".innerHTML" not in script
