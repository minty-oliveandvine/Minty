"""The Petty Cash API's Opening step (``blueprints/petty_cash_api/routes/opening.py``): the page's
read and its save, through the same service the Jinja page uses (``report/services/opening.py``;
that page's behaviour is pinned by tests/test_report_opening_state.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import char_factories as F
import pytest

pytestmark = pytest.mark.char

WEB = "http://localhost:3010"


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
        owner = F.make_user(db, "owner@test.com")
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
        return None if row is None else {
            "status": str(getattr(row.status, "value", row.status)),
            "opening": row.opening_balance, "addition": row.cash_addition, "adjusted": row.adjusted_opening_balance,
            "section": row.current_section, "completed": row.completed_sections, "source": row.cash_addition_type,
        }


def _url(entity):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/opening"


def _get(app, client, owner, entity, day=None):
    query = {"transaction_date": F.iso(day)} if day else {}
    return client.get(_url(entity), query_string=query, headers=F.petty_cash_headers(app, owner.id, origin=WEB))


def _put(app, client, owner, entity, body):
    return client.put(_url(entity), json=body, headers=F.petty_cash_headers(app, owner.id, origin=WEB))


def _body(day, **over):
    return {"transaction_date": F.iso(day), "cash_addition": 0, "withdrawal": "personal", "action": "next", **over}


# --- GET ---------------------------------------------------------------------------------------------


def test_a_first_report_reads_as_nothing_yet(app, client, shop):
    owner, entity = shop
    resp = _get(app, client, owner, entity, D3)

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {
        "transaction_date": F.iso(D3),
        "currency_code": "HKD",
        "draft": None,
        "starting_cash_balance": 0.0,
        "yesterday_closing_balance": 0.0,
        "safebox_balance": 0.0,
        "cash_addition": None,
        "withdrawal": "personal",
    }


def test_the_next_day_starts_from_the_last_closing(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=120, safe_box_balance=20)

    page = _get(app, client, owner, entity, D3).get_json()

    assert page["starting_cash_balance"] == 120.0
    assert page["yesterday_closing_balance"] == 120.0 and page["safebox_balance"] == 20.0


def test_the_days_draft_brings_its_values(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=120)
    draft = _report(app, db, entity, owner, D3, status="draft", opening_balance=120, cash_addition=30,
                    cash_addition_type="company", completed_sections=["opening"], current_section="sales")

    page = _get(app, client, owner, entity, D3).get_json()

    assert page["draft"] == {
        "id": draft, "status": "draft", "current_section": "sales", "completed_sections": ["opening"],
        "xero_integrated": False, "publishing_status": "unpublished",
    }
    assert page["cash_addition"] == 30.0 and page["withdrawal"] == "company"


def test_an_onboarding_seeded_opening_shows_when_there_is_no_yesterday(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D3, status="draft", opening_balance=500)

    assert _get(app, client, owner, entity, D3).get_json()["starting_cash_balance"] == 500.0


def test_a_bad_date_and_a_member_without_the_right_are_refused(app, client, db, shop):
    owner, entity = shop
    assert client.get(_url(entity), query_string={"transaction_date": "2026-02-30"},
                      headers=F.petty_cash_headers(app, owner.id, origin=WEB)).status_code == 422
    from models.db import UserEntity

    with app.app_context():
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    assert _get(app, client, base, entity, D3).status_code == 403
    assert _put(app, client, base, entity, _body(D3)).status_code == 403


# --- PUT ---------------------------------------------------------------------------------------------


def test_save_next_creates_the_draft_from_the_servers_opening(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=120)

    resp = _put(app, client, owner, entity, _body(D3, cash_addition=30.5, withdrawal="company", opening_balance=99999))

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["next"] == "sales" and body["current_section"] == "sales" and body["completed_sections"] == ["opening"]
    row = _row(app, entity, D3)
    # the opening is the server's own (yesterday's 120) - a client's opening_balance is ignored
    assert (row["opening"], row["addition"], row["adjusted"]) == (120, 30.5, 150.5)
    assert row["status"] == "draft" and row["source"] == "company"


def test_save_exit_keeps_the_draft_on_opening(app, client, db, shop):
    owner, entity = shop
    body = _put(app, client, owner, entity, _body(D3, action="exit")).get_json()
    assert body["next"] == "dashboard" and body["current_section"] == "opening"


def test_saving_again_updates_the_same_draft(app, client, db, shop):
    owner, entity = shop
    first = _put(app, client, owner, entity, _body(D3, cash_addition=10)).get_json()
    second = _put(app, client, owner, entity, _body(D3, cash_addition=25)).get_json()

    assert second["draft_id"] == first["draft_id"]
    assert _row(app, entity, D3)["addition"] == 25


def test_a_day_out_of_sequence_is_a_409_for_the_dashboard(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D1, closing_balance=1)

    resp = _put(app, client, owner, entity, _body(D3))

    assert resp.status_code == 409
    assert resp.get_json() == {
        "error": f"Reports go one day at a time - this one needs to be {D2}, the day after your last submitted report ({D1}).",
        "to": "dashboard",
    }
    assert _row(app, entity, D3) is None


def test_a_negative_opening_is_refused_back_to_the_page(app, client, db, shop):
    owner, entity = shop
    _report(app, db, entity, owner, D2, closing_balance=-50)

    resp = _put(app, client, owner, entity, _body(D3, cash_addition=10))

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "Hmm, it looks like your cash balance is negative. Could you fix that first?", "to": "opening"}


@pytest.mark.parametrize(
    "over",
    [
        {"transaction_date": "14/10/2026"},
        {"cash_addition": -1},
        {"cash_addition": "10"},
        {"cash_addition": True},
        {"withdrawal": "friend"},
        {"action": "save"},
    ],
)
def test_bad_input_is_a_422(app, client, shop, over):
    owner, entity = shop
    resp = _put(app, client, owner, entity, _body(D3, **over))
    assert resp.status_code == 422 and resp.get_json()["error"]
    assert _row(app, entity, D3) is None


# --- a company's first report (onboarding) ----------------------------------------------------------


def _onboarded(app, db, entity, *, opening=None, start=None):
    from models.db import EntityPettycashSettings

    with app.app_context():
        db.session.add(EntityPettycashSettings(entity_id=entity.id, opening_balance=opening, start_date=start))
        db.session.commit()


def test_a_first_report_opens_and_is_saved_at_the_onboarding_balance(app, client, db, shop):
    owner, entity = shop
    _onboarded(app, db, entity, opening=500, start=D2)

    assert _get(app, client, owner, entity, D3).get_json()["starting_cash_balance"] == 500.0
    assert _put(app, client, owner, entity, _body(D3, cash_addition=20)).status_code == 200
    row = _row(app, entity, D3)
    assert (row["opening"], row["adjusted"]) == (500, 520)


def test_a_first_report_before_the_onboarding_start_is_a_409(app, client, db, shop):
    owner, entity = shop
    _onboarded(app, db, entity, start=D2)

    resp = _put(app, client, owner, entity, _body(D1))

    assert resp.status_code == 409
    assert resp.get_json() == {"error": f"Transaction date must be on or after your onboarding date ({D2}).", "to": "dashboard"}
