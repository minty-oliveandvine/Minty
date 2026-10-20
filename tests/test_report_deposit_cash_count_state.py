"""The report wizard's Bank Deposit and Cash Count steps (``report/services/cash.py``), pinned through
the Jinja pages (``report/routes/deposit.py``, ``report/routes/cash_count.py``) before their logic
moved into that service (minty-petty-cash-web's port, 2026-10-15). Flask's HTML frontend was deleted
2026-10-20: the steps' reads, saves and the owner's rules of 2026-10-15 are
tests/test_petty_cash_api_cash.py's now; what is left here is what that file does not pin (the
history each save writes, the closing the count leaves alone, the safebox, an over count, Save &
Exit's count, a negative expected cash), driven through the Petty Cash API.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import char_factories as F
import pytest

pytestmark = pytest.mark.char


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
    """Cash on hand before the deposit: 100 + 20 + 50 - 15 = 155."""
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


def _row(app, report_id):
    from models.db import Report, db

    with app.app_context():
        row = db.session.get(Report, report_id)
        return {c: getattr(row, c) for c in (
            "bank_deposit", "closing_balance", "safe_box_balance", "discrepancy_amount", "discrepancy_type",
            "discrepancy_reason", "current_section", "completed_sections")}


def _counts(app, report_id):
    """face value -> quantity of the report's cash-count rows."""
    from models.db import CashInfo, ReportCashCount

    with app.app_context():
        rows = (ReportCashCount.query.join(CashInfo, CashInfo.id == ReportCashCount.cash_id)
                .filter(ReportCashCount.report_id == report_id)
                .with_entities(CashInfo.cash_value, ReportCashCount.quantity).all())
        return {float(v): q for v, q in rows if q}


def _history(app, report_id):
    from models.db import ReportHistory

    with app.app_context():
        return [(h.field_changed, h.new_value) for h in ReportHistory.query.filter_by(report_id=report_id).all()]


def _put(client, owner, entity, step, body, action="next"):
    return client.put(f"/api/petty-cash/v1/companies/{entity.id}/reports/{step}",
                      json={"transaction_date": F.iso(D3), "action": action, **body},
                      headers=F.petty_cash_headers(client.application, owner.id))


def _deposit(client, owner, entity, amount, action="next"):
    return _put(client, owner, entity, "deposit", {"bank_deposit": amount}, action)


def _count(client, owner, entity, counts, *, safe_box=0, reason="", action="next"):
    """``counts``: face value -> quantity."""
    from blueprints.report.services.cash_denominations import resolve_denominations_for_entity

    with client.application.app_context():
        ids = {float(d.cash_value): str(d.cash_id) for d in resolve_denominations_for_entity(entity.id)}
    return _put(client, owner, entity, "cash-count",
                {"counts": {ids[face]: n for face, n in counts.items()}, "safe_box_balance": safe_box,
                 "discrepancy_reason": reason}, action)


# --- Deposit -----------------------------------------------------------------------------------------


def test_save_next_stores_the_deposit_and_writes_its_history(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _deposit(client, owner, entity, 100.5)

    assert resp.status_code == 200, resp.get_json()
    row = _row(app, draft)
    assert row["bank_deposit"] == 100.5
    assert row["closing_balance"] == 155 - 100.5
    assert _history(app, draft) == [("bank_deposit", "Bank Deposit: $100.5")]


# --- Cash Count --------------------------------------------------------------------------------------


def _counted(app, db, entity, owner, **fields):
    """Expected cash after the 100 deposit: 155 - 100 = 55."""
    values = {"bank_deposit": 100, "closing_balance": 55, "current_section": "cash_count",
              "completed_sections": ["opening", "sales", "expenses", "deposit"]}
    values.update(fields)
    return _draft(app, db, entity, owner, **values)


def test_an_exact_count_records_no_difference_leaves_the_closing_and_writes_its_history(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    resp = _count(client, owner, entity, {50: 1, 5: 1})

    assert resp.status_code == 200, resp.get_json()
    assert _counts(app, draft) == {50: 1, 5: 1}
    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (0, "none")
    assert row["current_section"] == "ending"
    assert row["closing_balance"] == 55  # the cash count never writes it; submit adds the difference
    assert _history(app, draft) == [("cash_count", "Cash Count: $55.0")]


def test_a_short_count_is_a_negative_difference_and_the_safebox_counts_towards_it(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    _count(client, owner, entity, {20: 2}, safe_box=5, reason="Gave change twice")  # 40 + 5 vs 55

    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (-10, "short")
    assert row["safe_box_balance"] == 5 and row["discrepancy_reason"] == "Gave change twice"


def test_an_over_count_is_a_positive_difference(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    _count(client, owner, entity, {50: 1, 10: 1}, reason="Tip left in the till")

    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (5, "over")


def test_save_exit_keeps_the_count_and_puts_the_report_back_on_cash_count(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    resp = _count(client, owner, entity, {50: 1, 5: 1}, action="exit")

    assert resp.status_code == 200, resp.get_json()
    assert _counts(app, draft) == {50: 1, 5: 1}
    row = _row(app, draft)
    assert row["current_section"] == "cash_count"
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit"]


def test_a_negative_expected_cash_is_refused(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner, bank_deposit=500)  # 155 - 500 < 0

    resp = _count(client, owner, entity, {50: 1})

    assert resp.status_code == 409, resp.get_json()
    assert resp.get_json()["error"] == "Hmm, it looks like your cash balance is negative. Could you fix that first?"
    assert _counts(app, draft) == {}
