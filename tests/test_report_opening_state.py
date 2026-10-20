"""The report wizard's Opening step (``report/services/opening.py``), pinned through the Jinja page
(``report/routes/opening.py``) before its logic moved into that service (minty-petty-cash-web's
port, 2026-10-14). Flask's HTML frontend was deleted 2026-10-20: the step's read and save are
tests/test_petty_cash_api_opening.py's now; what is left here is what that file does not pin (a
draft before the day, the history a save writes, a save that leaves the closing alone, the future
and an already submitted day), driven through the Petty Cash API's ``/reports/opening``.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import char_factories as F
import pytest

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


def _url(entity):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/opening"


def _page(app, client, owner, entity, day):
    resp = client.get(_url(entity), query_string={"transaction_date": F.iso(day)},
                      headers=F.petty_cash_headers(app, owner.id))
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _save(client, owner, entity, day, *, addition=0, action="next", withdrawal="personal"):
    return client.put(_url(entity), json={"transaction_date": F.iso(day), "cash_addition": addition,
                                          "withdrawal": withdrawal, "action": action},
                      headers=F.petty_cash_headers(client.application, owner.id))


def _refused(resp, error):
    assert resp.status_code == 409, resp.get_json()
    assert resp.get_json() == {"error": error, "to": "dashboard"}


# --- the read ----------------------------------------------------------------------------------------


def test_only_a_draft_before_the_day_opens_from_its_closing(app, client, db, shop):
    """The opening chains off the previous report whatever its status; with nothing SUBMITTED
    before, the report counts as a first one and the box shows the opening it starts from."""
    owner, entity = shop
    _report(app, db, entity, owner, D2, status="draft", closing_balance=75, opening_balance=50)

    page = _page(app, client, owner, entity, D3)

    assert page["starting_cash_balance"] == 75
    assert page["yesterday_closing_balance"] == 75


# --- saving ---------------------------------------------------------------------------------------


def test_save_next_creates_the_draft_and_writes_its_history(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=1000)

    resp = _save(client, owner, entity, D3, addition=250.5, withdrawal="company")

    assert resp.status_code == 200, resp.get_json()
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


def test_saving_again_updates_the_draft_without_touching_its_closing(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=100)
    draft = _report(app, db, entity, owner, D3, status="draft", opening_balance=100, cash_addition=0,
                    adjusted_opening_balance=100, closing_balance=999, current_section="expenses",
                    completed_sections=["opening", "sales"])

    _save(client, owner, entity, D3, addition=40, withdrawal="personal")

    row = _row(app, entity, D3)
    assert (row["cash_addition"], row["adjusted_opening_balance"]) == (40, 140)
    assert row["closing_balance"] == 999  # not recomputed by this step
    assert row["current_section"] == "sales"  # save_next moves an advanced draft back
    assert row["completed_sections"] == ["opening", "sales"]
    assert row["cash_addition_type"] == "personal"
    with app.app_context():
        assert [h.action for h in ReportHistory.query.filter_by(report_id=draft).all()] == ["updated"]


def test_a_future_day_is_refused(app, client, db, shop):
    owner, entity = shop
    resp = _save(client, owner, entity, TODAY + timedelta(days=1))

    _refused(resp, f"Transaction date cannot be in the future. You can only create reports for dates up to {TODAY}.")


def test_a_submitted_day_cannot_be_opened_again(app, client, db, shop):
    """The date rule answers first: after a submitted D3 the only day that may open is the next."""
    owner, entity = shop
    _report(app, db, entity, owner, D3, closing_balance=5)

    resp = _save(client, owner, entity, D3)

    _refused(resp, f"Reports go one day at a time - this one needs to be {TODAY}, the day after your last "
                   f"submitted report ({D3}).")
