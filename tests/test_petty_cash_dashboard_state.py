"""What the Petty Cash dashboard's figures are (``entity/services/dashboard.py::dashboard_state``) -
what the Petty Cash API's ``GET /home`` hands minty-petty-cash-web's two ported dashboards.

Pinned 2026-10-14 off the old Jinja dashboard's template context, before the figures were
extracted into this service. The Part 15 redesign (development, 2026-10-15) replaced that page
with the launch page, which reads its own facts; these now read the service directly, so the API's
figures stay pinned. The old page's two page-only facts (the Xero bank-account list and whether
the company ever deposited) went with it.
"""
from __future__ import annotations

from datetime import date, timedelta

import char_factories as F
import pytest

pytestmark = pytest.mark.char

TODAY = date.today()


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def no_notice(monkeypatch):
    """The subscription notice asks minty-subscription-api over HTTP; not this test's business."""
    import blueprints.entity.routes.list as list_routes

    monkeypatch.setattr(list_routes, "fetch_notice", lambda *_a, **_k: None)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Tan")
        entity = F.make_entity(db, owner, name="Vine Café Central", currency=currency, country=country)
    return {"owner": owner, "entity": entity}


def _report(app, db, shop, day, *, status="submitted", **fields):
    from models.db import Report

    with app.app_context():
        row = Report(entity_id=shop["entity"].id, transaction_date=day, status=status,
                     created_by=shop["owner"].id, **fields)
        db.session.add(row)
        db.session.commit()
        return row.id


def _state(app, shop) -> dict:
    from blueprints.entity.services.dashboard import dashboard_state

    with app.app_context():
        return dashboard_state(shop["entity"].id)


def test_a_new_company(app, client, shop):
    state = _state(app, shop)
    latest = state["latest"]

    assert state["is_new_user"] is True
    assert state["draft"] is None and state["draft_date"] is None
    assert latest["date"] is None and latest["closing_balance"] == 0 and latest["deposit"] == 0
    assert latest["deposit_bank_name"] == "No deposit" and latest["deposit_bank_number"] == ""
    assert latest["can_correct_deposit"] is True and latest["deposit_correction_missing_settings"] == []
    assert state["published"] == {}
    assert state["today_has_report"] is False and state["today_report_id"] is None
    assert state["today_is_latest_report"] is False
    assert state["currency_code"] == "HKD"
    assert len(state["server_today_hk"]) == 10
    assert state["latest_submitter_first_name"] is None
    assert state["has_complete_xero_settings"] is False
    assert state["missing_settings_fields"]  # names what is missing


def test_a_draft_in_progress_after_two_submitted_days(app, client, db, shop):
    yesterday, before = TODAY - timedelta(days=1), TODAY - timedelta(days=2)
    first = _report(app, db, shop, before, closing_balance=80, bank_deposit=0)
    second = _report(app, db, shop, yesterday, closing_balance=120, bank_deposit=50, xero_integrated=True)
    draft = _report(app, db, shop, TODAY, status="draft", closing_balance=150,
                    current_section="sales", completed_sections=["opening"])

    state = _state(app, shop)
    latest, current = state["latest"], state["draft"]

    # the latest report INCLUDES the draft
    assert state["is_new_user"] is False
    assert latest["date"] == TODAY and latest["closing_balance"] == 150
    assert str(current["id"]) == str(draft)
    assert current["current_section"] == "sales" and current["completed_sections"] == ["opening"]
    assert state["draft_date"] == TODAY
    assert 0 <= current["last_edit_seconds"] < 600
    # published = everything but drafts
    assert sorted(state["published"]) == [before.isoformat(), yesterday.isoformat()]
    assert state["published"][yesterday.isoformat()] == {
        "id": second,
        "closing_balance": 120,
        "bank_deposit": 50,
        "xero_integrated_yes": True,
        "submitter_first_name": "Olive",
    }
    assert state["published"][before.isoformat()]["id"] == first
    assert state["today_has_report"] is False
    assert state["today_is_latest_report"] is True  # the draft is today's
    assert state["latest_submitter_first_name"] == "Olive"


def test_the_earliest_draft_is_the_calendar_floor(app, client, db, shop):
    _report(app, db, shop, TODAY, status="draft")
    _report(app, db, shop, TODAY - timedelta(days=3), status="draft")

    state = _state(app, shop)

    assert state["draft_date"] == TODAY - timedelta(days=3)
    assert state["latest"]["date"] == TODAY  # the newest draft drives the card


def test_today_submitted(app, client, db, shop):
    today_id = _report(app, db, shop, TODAY, closing_balance=10)

    state = _state(app, shop)

    assert state["today_has_report"] is True and str(state["today_report_id"]) == str(today_id)
    assert state["today_is_latest_report"] is True
    assert state["draft"] is None


def test_a_deposit_without_the_accounts_to_correct_it(app, client, db, shop):
    _report(app, db, shop, TODAY - timedelta(days=1), closing_balance=10, bank_deposit=25)

    latest = _state(app, shop)["latest"]

    assert latest["deposit"] == 25
    assert latest["deposit_bank_name"] == "Unknown Bank" and latest["deposit_bank_number"] == "****"
    assert latest["deposit_correction_missing_settings"] == ["Deposit Bank Account", "Petty Cash Account"]
    assert latest["can_correct_deposit"] is False
