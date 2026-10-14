"""What the report wizard's Opening step (``report/routes/opening.py``) shows and saves - pinned
before its logic moves into a service that the Jinja page and the Petty Cash API share
(minty-petty-cash-web's port of the step, 2026-10-14).

Characterisation: today's behaviour, quirks included - read off the template context for the
page (GET) and off the database and the flashed message for a save (POST).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

import char_factories as F
import pytest
from flask import template_rendered

pytestmark = pytest.mark.char


def _hk_today():
    from models.db import tz

    return datetime.now(tz).date()


TODAY = _hk_today()
D1, D2, D3 = TODAY - timedelta(days=3), TODAY - timedelta(days=2), TODAY - timedelta(days=1)


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return owner, entity


def _report(app, db, entity, owner, day, *, status="submitted", **fields):
    from models.db import Report

    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=day, status=status, created_by=owner.id, **fields)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


def _onboarded(app, db, entity, *, opening=None, start=None):
    """What onboarding saves for the first report (entity_pettycash_settings)."""
    from models.db import EntityPettycashSettings

    with app.app_context():
        db.session.add(EntityPettycashSettings(entity_id=entity.id, opening_balance=opening, start_date=start))
        db.session.commit()


def _row(app, entity, day):
    from models.db import Report

    with app.app_context():
        row = Report.query.filter_by(entity_id=entity.id, transaction_date=day).first()
        if row is None:
            return None
        return {c: getattr(row, c) for c in (
            "id", "status", "opening_balance", "cash_addition", "adjusted_opening_balance", "closing_balance",
            "next_transaction_date", "current_section", "completed_sections", "cash_addition_type", "created_by",
        )}


@contextmanager
def _captured(app):
    seen = []

    def record(_sender, template, context, **_extra):
        seen.append((template.name, context))

    template_rendered.connect(record, app)
    try:
        yield seen
    finally:
        template_rendered.disconnect(record, app)


def _page(app, client, owner, entity, day):
    F.login(client, owner)
    with _captured(app) as seen:
        resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/opening", query_string={"transaction_date": F.iso(day)})
    assert resp.status_code == 200, resp.data[:300]
    pages = [ctx for name, ctx in seen if name == "report/opening.html"]
    assert len(pages) == 1
    return pages[0]


def _save(client, owner, entity, day, *, opening="0", addition="0", action="save_next", withdrawal=None, draft_id=None):
    F.login(client, owner)
    form = {"entity_id": entity.id, "transaction_date": F.iso(day), "opening_balance": opening,
            "cash_addition": addition, "action_type": action}
    if withdrawal:
        form["withdrawal"] = withdrawal
    if draft_id:
        form["draft_id"] = draft_id
    return client.post("/report/opening", data=form)


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _cat, m in sess.get("_flashes", [])]


# --- the page ---------------------------------------------------------------------------------------


def test_a_first_report_starts_from_nothing(app, client, shop):
    owner, entity = shop
    ctx = _page(app, client, owner, entity, D3)

    assert ctx["current_draft"] is None and ctx["draft_id"] is None
    assert ctx["opening_balance"] == 0
    assert ctx["yesterday_closing_balance"] == 0 and ctx["safebox_balance"] == 0
    assert ctx["report"] == {"adjusted_opening_balance": 0, "cash_addition": 0, "withdrawal": "personal", "bank_account": ""}
    assert ctx["next_transaction_date"] == D3 and ctx["transaction_date"] == D3
    assert ctx["completed_sections"] == [] and ctx["current_section"] == "opening"


def test_the_next_day_opens_from_the_last_closing_and_its_safebox(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=120, safe_box_balance=20)

    ctx = _page(app, client, owner, entity, D3)

    assert ctx["opening_balance"] == 120
    assert ctx["yesterday_closing_balance"] == 120 and ctx["safebox_balance"] == 20
    assert ctx["report"]["adjusted_opening_balance"] == 120 and ctx["report"]["cash_addition"] == 0


def test_a_draft_for_the_day_brings_its_own_values(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=120, safe_box_balance=20)
    draft = _report(app, db, entity, owner, D3, status="draft", opening_balance=120, cash_addition=30,
                    adjusted_opening_balance=150, cash_addition_type="company", completed_sections=["opening"],
                    current_section="sales")

    ctx = _page(app, client, owner, entity, D3)

    assert str(ctx["draft_id"]) == draft
    assert ctx["opening_balance"] == 120
    assert ctx["report"] == {"adjusted_opening_balance": 150, "cash_addition": 30, "withdrawal": "company", "bank_account": ""}
    assert ctx["yesterday_closing_balance"] == 120 and ctx["safebox_balance"] == 20
    assert ctx["completed_sections"] == ["opening"] and ctx["current_section"] == "opening"


def test_only_a_draft_before_the_day_opens_from_its_closing(app, client, db, shop):
    """The opening chains off the previous report whatever its status; with nothing SUBMITTED
    before, the report counts as a first one and the box shows the opening it starts from."""
    owner, entity = shop
    _report(app, db, entity, owner, D2, status="draft", closing_balance=75, opening_balance=50)

    ctx = _page(app, client, owner, entity, D3)

    assert ctx["opening_balance"] == 75
    assert ctx["yesterday_closing_balance"] == 75


def test_a_first_report_opens_at_the_onboarding_balance(app, client, db, shop):
    owner, entity = shop
    _onboarded(app, db, entity, opening=500, start=D2)

    ctx = _page(app, client, owner, entity, D3)

    assert ctx["opening_balance"] == 500 and ctx["yesterday_closing_balance"] == 500


def test_a_first_report_is_saved_at_the_onboarding_balance_whatever_the_form_says(app, client, db, shop):
    owner, entity = shop
    _onboarded(app, db, entity, opening=500, start=D2)

    _save(client, owner, entity, D3, opening="1", addition="20")

    row = _row(app, entity, D3)
    assert (row["opening_balance"], row["adjusted_opening_balance"]) == (500, 520)


# --- saving ---------------------------------------------------------------------------------------


def test_save_next_creates_the_draft_and_moves_on_to_sales(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    resp = _save(client, owner, entity, D3, opening="1000.00", addition="250.50", withdrawal="company")

    assert resp.status_code == 302 and "/reports/new/sale" in resp.headers["Location"]
    row = _row(app, entity, D3)
    assert row["status"] == "draft"
    assert (row["opening_balance"], row["cash_addition"], row["adjusted_opening_balance"]) == (1000, 250.5, 1250.5)
    assert row["closing_balance"] == 1250.5
    assert row["next_transaction_date"] == TODAY
    assert row["current_section"] == "sales" and row["completed_sections"] == ["opening"]
    assert row["cash_addition_type"] == "company"
    assert str(row["created_by"]) == owner.id
    with app.app_context():
        history = ReportHistory.query.filter_by(report_id=row["id"]).all()
    assert [(h.action, h.field_changed, h.new_value) for h in history] == [
        ("created", "opening_entry", "Opening: 1000.0, Addition: 250.5, Adjusted: 1250.5")
    ]


def test_save_exit_keeps_the_draft_on_opening_and_goes_home(app, client, db, shop):
    owner, entity = shop
    resp = _save(client, owner, entity, D3, opening="10", action="save_exit")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    row = _row(app, entity, D3)
    assert row["current_section"] == "opening" and row["completed_sections"] == ["opening"]


def test_saving_again_updates_the_draft_without_touching_its_closing(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    draft = _report(app, db, entity, owner, D3, status="draft", opening_balance=100, cash_addition=0,
                    adjusted_opening_balance=100, closing_balance=999, current_section="expenses",
                    completed_sections=["opening", "sales"])

    _save(client, owner, entity, D3, opening="100", addition="40", withdrawal="personal", draft_id=draft)

    row = _row(app, entity, D3)
    assert (row["cash_addition"], row["adjusted_opening_balance"]) == (40, 140)
    assert row["closing_balance"] == 999  # not recomputed by this step
    assert row["current_section"] == "sales"  # save_next moves an advanced draft back
    assert row["completed_sections"] == ["opening", "sales"]
    assert row["cash_addition_type"] == "personal"
    with app.app_context():
        assert [h.action for h in ReportHistory.query.filter_by(report_id=draft).all()] == ["updated"]


def test_a_day_out_of_sequence_is_refused(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D1, closing_balance=1)

    resp = _save(client, owner, entity, D3)

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    assert _flashes(client) == [
        f"Reports go one day at a time - this one needs to be {D2}, the day after your last submitted report ({D1})."
    ]
    assert _row(app, entity, D3) is None


def test_a_future_day_is_refused(app, client, db, shop):
    owner, entity = shop
    resp = _save(client, owner, entity, TODAY + timedelta(days=1))

    assert resp.status_code == 302
    assert _flashes(client) == [
        f"Transaction date cannot be in the future. You can only create reports for dates up to {TODAY}."
    ]


def test_a_first_report_before_the_onboarding_date_is_refused(app, client, db, shop):
    owner, entity = shop
    _onboarded(app, db, entity, start=D2)  # the onboarding start date: the floor

    resp = _save(client, owner, entity, D1)

    assert resp.status_code == 302
    assert _flashes(client) == [f"Transaction date must be on or after your onboarding date ({D2})."]
    assert _row(app, entity, D1) is None


def test_a_negative_opening_is_refused(app, client, db, shop):
    owner, entity = shop
    resp = _save(client, owner, entity, D3, opening="10", addition="-20")

    assert resp.status_code == 302 and "/reports/new/opening" in resp.headers["Location"]
    assert _flashes(client) == ["Hmm, it looks like your cash balance is negative. Could you fix that first?"]
    assert _row(app, entity, D3) is None


def test_a_submitted_day_cannot_be_opened_again(app, client, db, shop):
    """The date rule answers first: after a submitted D3 the only day that may open is the next."""
    owner, entity = shop
    _report(app, db, entity, owner, D3, closing_balance=5)

    _save(client, owner, entity, D3, opening="5")

    assert _flashes(client) == [
        f"Reports go one day at a time - this one needs to be {TODAY}, the day after your last submitted report ({D3})."
    ]
