"""The Petty Cash API's Bank Deposit and Cash Count steps (``blueprints/petty_cash_api/routes/cash.py``),
through the service the Jinja pages use (``report/services/cash.py``; those pages are pinned by
tests/test_report_deposit_cash_count_state.py). The door is tests/test_petty_cash_api_door.py's.
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


D3 = _hk_today() - timedelta(days=1)


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
        currency = F.seed_currency(db)  # HKD 1000 .. 0.1
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return owner, entity


def _draft(app, db, entity, owner, **fields):
    """Cash on hand 155 (100 + 20 + 50 - 15)."""
    from models.db import Report

    values = {"opening_balance": 100, "cash_addition": 20, "adjusted_opening_balance": 120, "cashsale_total": 50,
              "expense_total": 15, "closing_balance": 155, "completed_sections": ["opening", "sales", "expenses"],
              "current_section": "deposit"}
    values.update(fields)
    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=D3, status=values.pop("status", "draft"),
                     created_by=owner.id, **values)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


def _counted(app, db, entity, owner, **fields):
    """Deposit 100 made: expected cash 55."""
    values = {"bank_deposit": 100, "closing_balance": 55, "current_section": "cash_count",
              "completed_sections": ["opening", "sales", "expenses", "deposit"]}
    values.update(fields)
    return _draft(app, db, entity, owner, **values)


def _row(app, report_id):
    from models.db import Report, db

    with app.app_context():
        row = db.session.get(Report, report_id)
        return {c: getattr(row, c) for c in (
            "bank_deposit", "closing_balance", "safe_box_balance", "discrepancy_amount", "discrepancy_type",
            "discrepancy_reason", "current_section", "completed_sections")}


def _counts(app, report_id):
    from models.db import CashInfo, ReportCashCount

    with app.app_context():
        rows = (ReportCashCount.query.join(CashInfo, CashInfo.id == ReportCashCount.cash_id)
                .filter(ReportCashCount.report_id == report_id)
                .with_entities(CashInfo.cash_value, ReportCashCount.quantity).all())
        return {float(v): q for v, q in rows if q}


def _ids(app, client, owner, entity):
    """face value -> denomination id, as the page's read hands them out."""
    body = _get(app, client, owner, entity, "cash-count").get_json()
    return {d["value"]: d["id"] for d in body["denominations"]}


def _headers(app, who):
    return F.petty_cash_headers(app, who.id, origin=WEB)


def _url(entity, step):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/{step}"


def _get(app, client, who, entity, step, day=D3):
    return client.get(_url(entity, step), query_string={"transaction_date": F.iso(day)}, headers=_headers(app, who))


def _put(app, client, who, entity, step, body):
    return client.put(_url(entity, step), json={"transaction_date": F.iso(D3), "action": "next", **body},
                      headers=_headers(app, who))


# --- Deposit -----------------------------------------------------------------------------------------


def test_the_deposit_read_brings_the_cash_on_hand_and_what_it_is_made_of(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, bank_deposit=30)

    resp = _get(app, client, owner, entity, "deposit")

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["draft"]["id"] == draft and body["currency_code"] == "HKD"
    assert {k: body[k] for k in ("opening_balance", "cash_addition", "cash_sales", "expenses", "bank_deposit",
                                 "cash_on_hand", "expected_cash")} == {
        "opening_balance": 100, "cash_addition": 20, "cash_sales": 50, "expenses": 15, "bank_deposit": 30,
        "cash_on_hand": 155, "expected_cash": 125}


def test_the_reads_refuse_no_draft_a_bad_date_and_a_member_without_the_right(app, client, db, shop):
    from models.db import UserEntity

    owner, entity = shop
    for step in ("deposit", "cash-count"):
        resp = _get(app, client, owner, entity, step)
        assert resp.status_code == 409 and resp.get_json()["to"] == "opening"
        assert client.get(_url(entity, step), headers=_headers(app, owner)).status_code == 422
    with app.app_context():
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    _draft(app, db, entity, owner)
    assert _get(app, client, base, entity, "deposit").status_code == 403
    assert _put(app, client, base, entity, "deposit", {"bank_deposit": 1}).status_code == 403
    assert _put(app, client, base, entity, "cash-count", {"counts": {}}).status_code == 403


def test_save_next_stores_the_deposit_and_moves_on(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _put(app, client, owner, entity, "deposit", {"bank_deposit": 100.5})

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["next"] == "cash_count" and resp.get_json()["current_section"] == "cash_count"
    row = _row(app, draft)
    assert row["bank_deposit"] == 100.5 and row["closing_balance"] == 54.5
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit"]


def test_save_exit_stores_the_deposit_without_moving_on(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    body = _put(app, client, owner, entity, "deposit", {"bank_deposit": 10, "action": "exit"}).get_json()

    assert body["next"] == "dashboard" and _row(app, draft)["completed_sections"] == ["opening", "sales", "expenses"]


def test_a_deposit_above_the_cash_on_hand_is_a_422_on_the_field(app, client, db, shop):
    """The owner's rule, 2026-10-15."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _put(app, client, owner, entity, "deposit", {"bank_deposit": 155.01})

    assert resp.status_code == 422
    assert resp.get_json() == {"error": "The deposit can't be more than the cash on hand. Enter HKD155.00 or less.",
                               "field": "bank_deposit"}
    assert _row(app, draft)["bank_deposit"] in (None, 0)


def test_a_negative_cash_on_hand_is_a_409(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner, expense_total=500)

    resp = _put(app, client, owner, entity, "deposit", {"bank_deposit": 0})

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "Hmm, it looks like your cash balance is negative. Could you fix that first?"}


@pytest.mark.parametrize("body, status", [
    ({"bank_deposit": -1}, 422), ({"bank_deposit": "12"}, 422), ({"bank_deposit": 100_000_000_000}, 422),
    ({"bank_deposit": 1, "action": "later"}, 422), ({"bank_deposit": 1, "transaction_date": "15/10/2026"}, 422),
])
def test_bad_deposit_input_is_refused(app, client, db, shop, body, status):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    assert _put(app, client, owner, entity, "deposit", body).status_code == status
    assert _row(app, draft)["bank_deposit"] in (None, 0)


# --- Cash Count --------------------------------------------------------------------------------------


def test_the_count_read_brings_the_denominations_the_expected_cash_and_the_saved_count(app, client, db, shop):
    owner, entity = shop
    _counted(app, db, entity, owner, safe_box_balance=5, discrepancy_amount=-10, discrepancy_type="short",
             discrepancy_reason="Change")
    ids = _ids(app, client, owner, entity)
    _put(app, client, owner, entity, "cash-count",
         {"counts": {ids[20]: 2}, "safe_box_balance": 5, "discrepancy_reason": "Change", "action": "exit"})

    body = _get(app, client, owner, entity, "cash-count").get_json()

    assert [d["value"] for d in body["denominations"]] == [1000, 500, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1]
    assert {d["value"]: d["count"] for d in body["denominations"] if d["count"]} == {20: 2}
    assert body["expected_cash"] == 55 and body["safe_box_balance"] == 5
    assert body["discrepancy"] == {"amount": -10, "kind": "short", "reason": "Change"}


def test_an_exact_count_moves_on_to_ending(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)
    ids = _ids(app, client, owner, entity)

    resp = _put(app, client, owner, entity, "cash-count", {"counts": {ids[50]: 1, ids[5]: 1}})

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["next"] == "ending" and body["discrepancy"] == {"amount": 0, "kind": "none"}
    assert _counts(app, draft) == {50: 1, 5: 1}
    assert _row(app, draft)["completed_sections"] == ["opening", "sales", "expenses", "deposit", "cash_count"]


def test_a_difference_needs_a_reason_on_save_next_but_not_on_save_exit(app, client, db, shop):
    """The owner's rule, 2026-10-15."""
    owner, entity = shop
    draft = _counted(app, db, entity, owner)
    ids = _ids(app, client, owner, entity)

    refused = _put(app, client, owner, entity, "cash-count", {"counts": {ids[50]: 1}})
    assert refused.status_code == 422
    assert refused.get_json() == {"error": "The count is HKD5.00 short. Add the reason to continue.",
                                  "field": "discrepancy_reason"}
    assert _counts(app, draft) == {}

    kept = _put(app, client, owner, entity, "cash-count", {"counts": {ids[50]: 1}, "action": "exit"})
    assert kept.status_code == 200 and kept.get_json()["discrepancy"] == {"amount": -5, "kind": "short"}

    done = _put(app, client, owner, entity, "cash-count", {"counts": {ids[50]: 1}, "discrepancy_reason": " Float "})
    assert done.status_code == 200 and _row(app, draft)["discrepancy_reason"] == "Float"


def test_a_single_cent_is_a_difference(app, client, db, shop):
    """The owner's rule, 2026-10-15."""
    owner, entity = shop
    _counted(app, db, entity, owner, expense_total=14.99)  # expected 55.01
    ids = _ids(app, client, owner, entity)

    resp = _put(app, client, owner, entity, "cash-count", {"counts": {ids[50]: 1, ids[5]: 1}})

    assert resp.status_code == 422 and resp.get_json()["error"] == "The count is HKD0.01 short. Add the reason to continue."


@pytest.mark.parametrize("change, status", [
    ({"counts": {"not-a-denomination": 1}}, 422),
    ({"counts": "fifty"}, 422),
    ({"safe_box_balance": -1}, 422),
    ({"discrepancy_reason": 7}, 422),
    ({"discrepancy_reason": "x" * 301}, 422),
])
def test_bad_count_input_is_refused(app, client, db, shop, change, status):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    assert _put(app, client, owner, entity, "cash-count", {"counts": {}, **change}).status_code == status
    assert _row(app, draft)["current_section"] == "cash_count"


@pytest.mark.parametrize("quantity", [2.5, -1, True, "3"])
def test_a_count_must_be_a_whole_number_of_zero_or_more(app, client, db, shop, quantity):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)
    ids = _ids(app, client, owner, entity)

    resp = _put(app, client, owner, entity, "cash-count", {"counts": {ids[50]: quantity}})

    assert resp.status_code == 422 and resp.get_json()["field"] == ids[50]
    assert _counts(app, draft) == {}


# --- the deposit and the count together (Part 15's Cash Count stage) ---------------------------------


def test_the_deposit_and_the_count_are_saved_together(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)  # no deposit yet: cash on hand 155
    ids = _ids(app, client, owner, entity)

    resp = _put(app, client, owner, entity, "cash-count", {"bank_deposit": 100, "counts": {ids[50]: 1, ids[5]: 1}})

    assert resp.status_code == 200, resp.get_json()
    row = _row(app, draft)
    assert row["bank_deposit"] == 100 and row["discrepancy_type"] == "none"
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit", "cash_count"]
    assert row["current_section"] == "ending"


def test_a_refused_count_leaves_the_deposit_unsaved_too(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    ids = _ids(app, client, owner, entity)

    resp = _put(app, client, owner, entity, "cash-count", {"bank_deposit": 100, "counts": {ids[50]: 1}})  # 5 short

    assert resp.status_code == 422 and resp.get_json()["field"] == "discrepancy_reason"
    row = _row(app, draft)
    assert row["bank_deposit"] in (None, 0) and row["completed_sections"] == ["opening", "sales", "expenses"]
    assert _counts(app, draft) == {}


def test_a_deposit_above_the_cash_on_hand_refuses_the_whole_save(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)
    ids = _ids(app, client, owner, entity)

    resp = _put(app, client, owner, entity, "cash-count", {"bank_deposit": 200, "counts": {ids[50]: 1}})

    assert resp.status_code == 422 and resp.get_json()["field"] == "bank_deposit"
    assert _counts(app, draft) == {}
