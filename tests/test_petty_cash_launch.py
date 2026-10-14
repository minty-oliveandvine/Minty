"""The Petty Cash launch page (Part 15.6a) - entity.report_dashboard renders petty_cash/launch.html.

Pins the states blueprints/entity/services/launch.py decides (first use, in progress, the gate,
not started, done), what each draws, the Before You Start / Correct deposit rules, and the Part 14
structure (one h1, one Primary, Step progress with aria-current, no calendar or Tailwind CDN).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta

import pytest

import char_factories as F

GATE = re.compile(r"Finish \w+ \d+ \w+ \d{4} first")


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def no_notice(app, monkeypatch):
    """The subscription notice is the subscription API's; never dial it from a test."""
    monkeypatch.setattr(sys.modules["blueprints.entity.routes.list"], "fetch_notice", lambda *a, **k: None)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return owner, entity


def today():
    from models.db import tz

    return datetime.now(tz).date()


def add_report(app, entity, owner, day, *, status="submitted", **columns):
    from blueprints.report.models.report import Report
    from models.db import db

    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=day, status=status, created_by=owner.id,
                     opening_balance=columns.pop("opening_balance", 1000), **columns)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


def page(client, owner, entity):
    F.login(client, owner)
    resp = client.get(f"{F.co(client, entity.id)}/petty-cash")
    assert resp.status_code == 200, resp.data[:300]
    return resp.get_data(as_text=True)


def primaries(html):
    """Primary buttons on the page itself (not inside an overlay)."""
    body = html.split('<main class="pc-main"', 1)[1].split("</main>", 1)[0]
    return re.findall(r'class="pc-btn pc-btn--primary[^"]*"[^>]*>([^<]*)<', body)


def test_first_use_offers_todays_closing(client, shop):
    owner, entity = shop
    html = page(client, owner, entity)

    assert "Your first Daily Closing" in html
    assert primaries(html) == ["Start today's Daily Closing"]
    assert f"transaction_date={today().isoformat()}" in html
    assert "No reports yet" in html
    assert html.count("<h1") == 1 and "Petty Cash</h1>" in html
    # retired by 15.6a, and the page no longer styles itself from the Tailwind CDN
    for gone in ("calendarDates", "Quick Actions", "Current balance", "cdn.tailwindcss.com", "Start New Report"):
        assert gone not in html


def test_an_open_draft_continues_where_it_stopped(app, client, shop):
    owner, entity = shop
    draft = add_report(app, entity, owner, today(), status="draft", current_section="deposit",
                       completed_sections=["opening", "sales", "expenses"])
    html = page(client, owner, entity)

    assert "Today's Daily Closing" in html
    assert re.search(r"3 of 5 done</span> · Next: Cash Count", html)
    assert primaries(html) == ["Continue Daily Closing"]
    assert f"draft_id={draft}" in html
    # Step progress: done stages are links, the current one is marked, upcoming are not links
    current = re.search(r'<li aria-current="step">\s*<a href="[^"]*" class="pc-step pc-step--current" data-stage="(\w+)"', html)
    assert current and current.group(1) == "cash_count"
    assert re.search(r'<div class="pc-step pc-step--upcoming" data-stage="close"', html)
    assert "Saved " in html
    assert not GATE.search(html)  # today's own draft: no gate


def test_an_earlier_day_still_open_is_the_gate(app, client, shop):
    owner, entity = shop
    add_report(app, entity, owner, today() - timedelta(days=3), closing_balance=500)
    html = page(client, owner, entity)
    gate = today() - timedelta(days=2)

    assert re.search(rf"Finish \w+ {gate.day} {gate:%b %Y} first", html)
    assert primaries(html) == [f"Start Daily Closing for {gate.day} {gate:%b %Y}"]
    assert f"transaction_date={gate.isoformat()}" in html


def test_the_day_after_yesterday_is_today(app, client, shop):
    owner, entity = shop
    add_report(app, entity, owner, today() - timedelta(days=1), closing_balance=500)
    html = page(client, owner, entity)

    assert primaries(html) == ["Start today's Daily Closing"]
    assert not GATE.search(html)
    assert "0 of 5 done" in html


def test_todays_report_submitted_is_done(app, client, shop):
    owner, entity = shop
    rid = add_report(app, entity, owner, today(), closing_balance=500)
    html = page(client, owner, entity)

    assert "Today's report is submitted" in html
    assert primaries(html) == ["View report"]
    assert f"/petty-cash/reports/{rid}/summary" in html


def test_recent_reports_are_the_three_latest_submitted(app, client, shop):
    owner, entity = shop
    for back in range(1, 6):
        add_report(app, entity, owner, today() - timedelta(days=back), closing_balance=100 * back)
    add_report(app, entity, owner, today(), status="draft")
    html = page(client, owner, entity)

    rows = re.findall(r'class="pc-row__link"[^>]*>([^<]+)<', html)
    assert len(rows) == 3
    assert rows[0].endswith(f"{(today() - timedelta(days=1)).day} {(today() - timedelta(days=1)):%b %Y}")
    assert "HKD 100.00" in html and "HKD 300.00" in html and "HKD 400.00" not in html
    assert html.count('data-tone="info">Submitted<') == 3


def test_before_you_start_asks_only_after_a_deposit(app, client, shop):
    owner, entity = shop
    add_report(app, entity, owner, today() - timedelta(days=1), closing_balance=500, bank_deposit=0)
    assert 'id="beforeStartModal"' not in page(client, owner, entity)

    with app.app_context():
        from blueprints.report.models.report import Report
        from models.db import db

        Report.query.filter_by(entity_id=entity.id).update({"bank_deposit": 250})
        db.session.commit()
    html = page(client, owner, entity)
    assert 'id="beforeStartModal"' in html
    assert "HKD 250.00" in html
    # the mappings a correction needs are missing here, so change/remove are refused up front
    assert "This deposit cannot be corrected yet" in html


def test_correct_deposit_sits_on_the_latest_row_only_when_no_day_is_open(app, client, shop):
    owner, entity = shop
    add_report(app, entity, owner, today() - timedelta(days=1), closing_balance=500, bank_deposit=250)
    assert page(client, owner, entity).count("data-pc-correct-deposit>Correct deposit<") == 1

    add_report(app, entity, owner, today(), status="draft")
    assert page(client, owner, entity).count("data-pc-correct-deposit>Correct deposit<") == 0


def test_setup_required_is_shown_until_the_settings_are_complete(client, shop):
    owner, entity = shop
    html = page(client, owner, entity)

    assert 'id="setupSettingsModal"' in html and "data-pc-locked" in html
    assert "Set Up Settings" in html


def test_a_read_only_superuser_cannot_start(app, client, shop, db):
    _, entity = shop
    with app.app_context():
        boss = F.make_user(db, "boss@test.com", system_role="superadmin")
    html = page(client, boss, entity)

    assert re.search(r'<button type="button" class="pc-btn pc-btn--primary" disabled[^>]*>Start today', html)
    assert "Read-only access" in html
