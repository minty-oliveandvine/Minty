"""What the Petty Cash dashboard (``entity/routes/list.py::report_dashboard``) computes - pinned
before it is extracted into a service that the HTML page and the Petty Cash API's ``/home`` both
read (minty-petty-cash-web's port of this page, 2026-10-14).

Characterisation: these assert what the page is handed TODAY, quirks included, read off the
template context - so the extraction can be proved to change nothing.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

import char_factories as F
import pytest
from flask import template_rendered

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


def _dashboard(app, client, shop) -> dict:
    F.login(client, shop["owner"])
    with _captured(app) as seen:
        resp = client.get(f"{F.co(client, shop['entity'].id)}/petty-cash")
    assert resp.status_code == 200, resp.data[:300]
    pages = [ctx for name, ctx in seen if name == "entity/entity_dashboard_v2.html"]
    assert len(pages) == 1
    return pages[0]


def test_a_new_company(app, client, shop):
    ctx = _dashboard(app, client, shop)
    org = ctx["org"]

    assert org.is_new_user is True
    assert org.has_existing_draft is False and org.draft_id is None
    assert org.draft_current_section is None and org.draft_completed_sections == []
    assert org.draft_progress_completed == 0 and org.draft_date is None
    assert org.transaction_date is None and org.closing_balance == 0 and org.latest_deposit == 0
    assert org.latest_deposit_bank_name == "No deposit" and org.latest_deposit_bank_number == ""
    assert org.can_correct_latest_deposit is True and org.deposit_correction_missing_settings == []
    assert ctx["published_dates"] == [] and ctx["published_reports_dict"] == {}
    assert ctx["today_has_report"] is False and ctx["today_report_id"] is None
    assert ctx["today_is_latest_report"] is False
    assert ctx["currency_symbol"] == "HKD"
    assert ctx["server_today_hk"] == ctx["server_today_hk"][:10] and len(ctx["server_today_hk"]) == 10
    assert ctx["has_deposit"] is None
    assert ctx["latest_report_submitter_first_name"] is None
    assert ctx["bank_accounts"] == []  # no Xero connection
    assert ctx["has_complete_xero_settings"] is False
    assert ctx["missing_settings_fields"]  # names what is missing


def test_a_draft_in_progress_after_two_submitted_days(app, client, db, shop):
    yesterday, before = TODAY - timedelta(days=1), TODAY - timedelta(days=2)
    first = _report(app, db, shop, before, closing_balance=80, bank_deposit=0)
    second = _report(app, db, shop, yesterday, closing_balance=120, bank_deposit=50, xero_integrated=True)
    draft = _report(app, db, shop, TODAY, status="draft", closing_balance=150,
                    current_section="sales", completed_sections=["opening"])

    ctx = _dashboard(app, client, shop)
    org = ctx["org"]

    # the latest report INCLUDES the draft
    assert org.is_new_user is False
    assert org.transaction_date == TODAY and org.closing_balance == 150
    assert org.has_existing_draft is True and str(org.draft_id) == str(draft)
    assert org.draft_current_section == "sales"
    assert org.draft_completed_sections == ["opening"] and org.draft_progress_completed == 1
    assert org.draft_date == TODAY
    assert 0 <= org.draft_last_edit_seconds < 600
    # published = everything but drafts
    assert sorted(ctx["published_dates"]) == [before.isoformat(), yesterday.isoformat()]
    assert ctx["published_reports_dict"][yesterday.isoformat()] == {
        "id": second,
        "closing_balance": 120,
        "bank_deposit": 50,
        "xero_integrated_yes": True,
        "submitter_first_name": "Olive",
    }
    assert ctx["published_reports_dict"][before.isoformat()]["id"] == first
    assert ctx["today_has_report"] is False
    assert ctx["today_is_latest_report"] is True  # the draft is today's
    assert ctx["latest_report_submitter_first_name"] == "Olive"
    assert ctx["has_deposit"] is not None


def test_the_earliest_draft_is_the_calendar_floor(app, client, db, shop):
    _report(app, db, shop, TODAY, status="draft")
    _report(app, db, shop, TODAY - timedelta(days=3), status="draft")

    org = _dashboard(app, client, shop)["org"]

    assert org.draft_date == TODAY - timedelta(days=3)
    assert org.transaction_date == TODAY  # the newest draft drives the card


def test_today_submitted(app, client, db, shop):
    today_id = _report(app, db, shop, TODAY, closing_balance=10)

    ctx = _dashboard(app, client, shop)

    assert ctx["today_has_report"] is True and str(ctx["today_report_id"]) == str(today_id)
    assert ctx["today_is_latest_report"] is True
    assert ctx["org"].has_existing_draft is False


def test_a_deposit_without_the_accounts_to_correct_it(app, client, db, shop):
    _report(app, db, shop, TODAY - timedelta(days=1), closing_balance=10, bank_deposit=25)

    org = _dashboard(app, client, shop)["org"]

    assert org.latest_deposit == 25
    assert org.latest_deposit_bank_name == "Unknown Bank" and org.latest_deposit_bank_number == "****"
    assert org.deposit_correction_missing_settings == ["Deposit Bank Account", "Petty Cash Account"]
    assert org.can_correct_latest_deposit is False
