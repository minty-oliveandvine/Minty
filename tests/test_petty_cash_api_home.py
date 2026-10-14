"""The Petty Cash API's dashboard routes (``blueprints/petty_cash_api/routes/home.py``):
``GET /home`` answers what the Jinja dashboard computes - from the same service - and
``POST /deposit-correction`` is the "Before You Start" correction, behind REPORT_EDIT_ENTITY and
input checks, delegating to the same function the Jinja page's route calls.
"""
from __future__ import annotations

from datetime import date, timedelta

import char_factories as F
import pytest

pytestmark = pytest.mark.char

TODAY = date.today()
WEB = "http://localhost:3010"


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
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Tan")
        entity = F.make_entity(db, owner, name="Vine Café Central", currency=currency, country=country)
    return {"owner": owner, "entity": entity}


def _member(app, db, shop, email, role):
    from models.db import UserEntity

    with app.app_context():
        person = F.make_user(db, email)
        db.session.add(UserEntity(user_id=person.id, entity_id=shop["entity"].id, role=role, approved=True))
        db.session.commit()
    return person


def _report(app, db, shop, day, *, status="submitted", **fields):
    from models.db import Report

    with app.app_context():
        row = Report(entity_id=shop["entity"].id, transaction_date=day, status=status,
                     created_by=shop["owner"].id, **fields)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


def _url(shop, path):
    return f"/api/petty-cash/v1/companies/{shop['entity'].id}{path}"


def _get_home(app, client, shop, user_id=None):
    resp = client.get(_url(shop, "/home"), headers=F.petty_cash_headers(app, user_id or shop["owner"].id, origin=WEB))
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


# --- GET /home ------------------------------------------------------------------------------------


def test_a_new_company(app, client, shop):
    home = _get_home(app, client, shop)

    assert home["currency_code"] == "HKD"
    assert len(home["server_today"]) == 10
    assert home["user_count"] == 1
    assert home["latest"] == {
        "date": None,
        "closing_balance": 0.0,
        "deposit": 0.0,
        "deposit_bank_name": "No deposit",
        "deposit_bank_number": "",
        "deposit_correction_missing_settings": [],
        "can_correct_deposit": True,
        "submitter_first_name": None,
    }
    assert home["draft"] is None and home["draft_date"] is None
    assert home["published"] == {}
    assert home["today_has_report"] is False and home["today_is_latest_report"] is False
    assert home["xero_settings"]["complete"] is False and home["xero_settings"]["missing"]
    assert home["permissions"] == {"read_only": False, "correct_deposit": True}


def test_a_draft_after_submitted_days_reads_as_the_page_does(app, client, db, shop):
    yesterday = TODAY - timedelta(days=1)
    submitted = _report(app, db, shop, yesterday, closing_balance=120, bank_deposit=50, xero_integrated=True)
    draft = _report(app, db, shop, TODAY, status="draft", closing_balance=150,
                    current_section="sales", completed_sections=["opening"])

    home = _get_home(app, client, shop)

    assert home["latest"]["date"] == TODAY.isoformat() and home["latest"]["closing_balance"] == 150.0
    assert home["latest"]["submitter_first_name"] == "Olive"
    assert home["draft"]["id"] == draft
    assert home["draft"]["current_section"] == "sales" and home["draft"]["completed_sections"] == ["opening"]
    assert 0 <= home["draft"]["last_edit_seconds"] < 600
    assert home["draft_date"] == TODAY.isoformat()
    assert home["published"] == {
        yesterday.isoformat(): {
            "id": submitted,
            "closing_balance": 120.0,
            "bank_deposit": 50.0,
            "xero_integrated": True,
            "submitter_first_name": "Olive",
        }
    }
    assert home["today_is_latest_report"] is True and home["today_has_report"] is False


def test_a_deposit_that_cannot_be_corrected_says_why(app, client, db, shop):
    _report(app, db, shop, TODAY - timedelta(days=1), closing_balance=10, bank_deposit=25)

    latest = _get_home(app, client, shop)["latest"]

    assert latest["deposit"] == 25.0
    assert latest["deposit_bank_name"] == "Unknown Bank" and latest["deposit_bank_number"] == "****"
    assert latest["can_correct_deposit"] is False
    assert latest["deposit_correction_missing_settings"] == ["Deposit Bank Account", "Petty Cash Account"]


def test_a_superuser_outside_the_company_reads_it_read_only(app, client, db, shop):
    with app.app_context():
        staff = F.make_user(db, "staff@test.com", system_role="superadmin")
    assert _get_home(app, client, shop, staff.id)["permissions"]["read_only"] is True


def test_a_cashier_may_read_but_not_correct_a_deposit(app, client, db, shop):
    cashier = _member(app, db, shop, "cashier@test.com", "cashier")
    assert _get_home(app, client, shop, cashier.id)["permissions"] == {"read_only": False, "correct_deposit": False}


def test_the_user_count_is_the_companys_approved_members(app, client, db, shop):
    from models.db import UserEntity

    _member(app, db, shop, "cashier@test.com", "cashier")
    pending = _member(app, db, shop, "pending@test.com", "cashier")
    with app.app_context():
        UserEntity.query.filter_by(user_id=pending.id).update({"approved": False})
        db.session.commit()
    assert _get_home(app, client, shop)["user_count"] == 2  # the owner and the cashier


# --- POST /deposit-correction -----------------------------------------------------------------------


@pytest.fixture
def delegate(monkeypatch):
    """Stand in for the shared correction (its own behaviour: tests/test_report_deposit_change.py)."""
    from blueprints.report.routes import legacy

    calls = []

    def fake(entity_id, correction):
        calls.append((entity_id, correction))
        return fake.answer

    fake.answer = ({"status": "success", "message": "Previous day's deposit updated successfully.", "id": 7,
                    "bank_deposit": 0.0, "redirect_url": "/flask/opening"}, 200)
    monkeypatch.setattr(legacy, "correct_previous_deposit", fake)
    fake.calls = calls
    return fake


def _post(app, client, shop, body, user_id=None):
    return client.post(_url(shop, "/deposit-correction"), json=body,
                       headers=F.petty_cash_headers(app, user_id or shop["owner"].id, origin=WEB))


def test_a_correction_is_delegated_and_names_the_next_day(app, client, shop, delegate):
    resp = _post(app, client, shop, {"kind": "change", "date": "2026-10-13", "amount": 12.5})

    assert resp.status_code == 200
    assert delegate.calls == [(shop["entity"].id, {"kind": "change", "date": "2026-10-13", "amount": 12.5})]
    body = resp.get_json()
    assert body["status"] == "success" and body["id"] == "7"
    assert body["next_transaction_date"] == "2026-10-14"
    assert "redirect_url" not in body  # a Flask address means nothing to the app


def test_a_refusal_from_the_correction_is_the_apis_refusal(app, client, shop, delegate):
    delegate.answer = ({"status": "error", "message": "That deposit is larger than the previous one."}, 400)
    resp = _post(app, client, shop, {"kind": "change", "date": "2026-10-13", "amount": 99})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "That deposit is larger than the previous one."}


def test_a_cashier_may_not_correct_a_deposit(app, client, db, shop, delegate):
    cashier = _member(app, db, shop, "cashier@test.com", "cashier")
    resp = _post(app, client, shop, {"kind": "no", "date": "2026-10-13", "amount": 0}, cashier.id)
    assert resp.status_code == 403
    assert delegate.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "maybe", "date": "2026-10-13", "amount": 0},
        {"kind": "change", "date": "13/10/2026", "amount": 1},
        {"kind": "change", "date": "2026-02-30", "amount": 1},
        {"kind": "change", "date": "2026-10-13", "amount": -1},
        {"kind": "change", "date": "2026-10-13", "amount": "1"},
        {"kind": "change", "date": "2026-10-13", "amount": True},
        {"kind": "no", "date": "2026-10-13", "amount": 5},
        ["not", "an", "object"],
    ],
)
def test_bad_input_is_refused_before_anything_changes(app, client, shop, delegate, body):
    resp = _post(app, client, shop, body)
    assert resp.status_code == 422
    assert resp.get_json()["error"]
    assert delegate.calls == []
