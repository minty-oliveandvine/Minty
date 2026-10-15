"""What the report wizard's Bank Deposit and Cash Count steps (``report/routes/deposit.py``,
``report/routes/cash_count.py``) show and save - pinned before their logic moves into a service that
the Jinja pages and the Petty Cash API share (minty-petty-cash-web's port, 2026-10-15).

Characterisation: today's behaviour, quirks included. Tests marked RULE pin Flask's behaviour where
the owner chose a different rule on 2026-10-15 (a deposit above the cash on hand is refused at
Deposit; any 1-cent difference counts; a difference needs a reason on Save & Next); the extraction
changes them deliberately.
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


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _cat, m in sess.get("_flashes", [])]


@contextmanager
def _captured(app, name):
    seen = []

    def record(_sender, template, context, **_extra):
        if template.name == name:
            seen.append(context)

    template_rendered.connect(record, app)
    try:
        yield seen
    finally:
        template_rendered.disconnect(record, app)


def _deposit(client, owner, entity, amount, action="save_next"):
    F.login(client, owner)
    return client.post("/report/deposit", data={"entity_id": entity.id, "transaction_date": F.iso(D3),
                                                "bank_deposit": amount, "action_type": action})


def _count(client, owner, entity, counts, *, safe_box="0", reason="", action="save_next"):
    F.login(client, owner)
    form = {"entity_id": entity.id, "transaction_date": F.iso(D3), "action_type": action,
            "safe_box_balance": safe_box, "discrepancy_amount": "999", "discrepancy_type": "over",
            "discrepancy_reason": reason}
    for field, face in F.denomination_fields(client.application, entity.id).items():
        form[f"actual_cash[{field}]"] = str(counts.get(face, 0))
    return client.post("/report/cash_count", data=form)


# --- Deposit: the page -------------------------------------------------------------------------------


def test_the_deposit_page_shows_the_cash_on_hand(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner, bank_deposit=30)
    F.login(client, owner)

    resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/deposit",
                      query_string={"transaction_date": F.iso(D3)})

    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'id="currentBalanceDisplay">HKD155.00<' in html  # before the deposit
    assert 'value="30.00"' in html  # the saved deposit


def test_with_no_draft_the_deposit_page_sends_you_to_opening(app, client, db, shop):
    owner, entity = shop
    F.login(client, owner)

    resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/deposit",
                      query_string={"transaction_date": F.iso(D3)})

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/report/opening")
    assert _flashes(client) == ["I don't see a draft yet - let's start with the opening entry."]


# --- Deposit: the save -------------------------------------------------------------------------------


def test_save_next_stores_the_deposit_and_moves_on_to_the_cash_count(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _deposit(client, owner, entity, "1,00.50")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/petty-cash/reports/new/cash-count?transaction_date={F.iso(D3)}")
    row = _row(app, draft)
    assert row["bank_deposit"] == 100.5
    assert row["closing_balance"] == 155 - 100.5
    assert row["current_section"] == "cash_count"
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit"]
    assert _history(app, draft) == [("bank_deposit", "Bank Deposit: $100.5")]


def test_save_exit_stores_the_deposit_and_goes_home_without_moving_on(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _deposit(client, owner, entity, "10", action="save_exit")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    row = _row(app, draft)
    assert row["bank_deposit"] == 10
    assert row["current_section"] == "deposit" and row["completed_sections"] == ["opening", "sales", "expenses"]


def test_a_negative_cash_on_hand_is_refused_before_the_deposit(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, expense_total=500)  # 120 + 50 - 500 < 0

    resp = _deposit(client, owner, entity, "10")

    assert resp.status_code == 302 and "/reports/new/deposit" in resp.headers["Location"]
    assert _flashes(client) == ["Hmm, it looks like your cash balance is negative. Could you fix that first?"]
    assert _row(app, draft)["bank_deposit"] in (None, 0)


def test_rule_a_deposit_above_the_cash_on_hand_is_refused(app, client, db, shop):
    """RULE (owner, 2026-10-15): refused at Deposit, naming what is allowed. Flask took it here
    and only blocked at Cash Count."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner)

    resp = _deposit(client, owner, entity, "155.01")

    assert resp.status_code == 302 and "/reports/new/deposit" in resp.headers["Location"]
    assert _flashes(client) == ["The deposit can't be more than the cash on hand. Enter HKD155.00 or less."]
    assert _row(app, draft)["bank_deposit"] in (None, 0)
    _deposit(client, owner, entity, "155")  # all of it is fine
    assert _row(app, draft)["bank_deposit"] == 155


# --- Cash Count: the page ----------------------------------------------------------------------------


def test_the_cash_count_page_lists_the_currencys_denominations_with_the_saved_counts(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner, bank_deposit=100, current_section="cash_count",
           completed_sections=["opening", "sales", "expenses", "deposit"])
    _count(client, owner, entity, {50: 1, 5: 1})

    with _captured(app, "report/cash_count.html") as seen:
        resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/cash-count",
                          query_string={"transaction_date": F.iso(D3)})

    assert resp.status_code == 200
    rows = seen[0]["denomination_rows"]
    assert [r["value"] for r in rows] == [1000, 500, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1]
    assert {r["value"]: r["count"] for r in rows if r["count"]} == {50: 1, 5: 1}


def test_with_no_draft_the_cash_count_page_sends_you_to_opening(app, client, db, shop):
    owner, entity = shop
    F.login(client, owner)

    resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/cash-count",
                      query_string={"transaction_date": F.iso(D3)})

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/report/opening")
    assert _flashes(client) == ["I don't see a draft for today yet - let's start with the opening entry."]


# --- Cash Count: the save ----------------------------------------------------------------------------


def _counted(app, db, entity, owner, **fields):
    """Expected cash after the 100 deposit: 155 - 100 = 55."""
    values = {"bank_deposit": 100, "closing_balance": 55, "current_section": "cash_count",
              "completed_sections": ["opening", "sales", "expenses", "deposit"]}
    values.update(fields)
    return _draft(app, db, entity, owner, **values)


def test_an_exact_count_records_no_difference_and_moves_on_to_ending(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    resp = _count(client, owner, entity, {50: 1, 5: 1})

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/petty-cash/reports/new/ending?transaction_date={F.iso(D3)}")
    assert _counts(app, draft) == {50: 1, 5: 1}
    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (0, "none")
    assert row["current_section"] == "ending"
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit", "cash_count"]
    assert row["closing_balance"] == 55  # the cash count never writes it; submit adds the difference
    assert _history(app, draft) == [("cash_count", "Cash Count: $55.0")]


def test_a_short_count_is_a_negative_difference_and_the_safebox_counts_towards_it(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    _count(client, owner, entity, {20: 2}, safe_box="5", reason="Gave change twice")  # 40 + 5 vs 55

    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (-10, "short")
    assert row["safe_box_balance"] == 5 and row["discrepancy_reason"] == "Gave change twice"


def test_an_over_count_is_a_positive_difference(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    _count(client, owner, entity, {50: 1, 10: 1}, reason="Tip left in the till")

    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (5, "over")


def test_rule_a_one_cent_difference_counts(app, client, db, shop):
    """RULE (owner, 2026-10-15): any difference counts. Flask's check was "more than 0.01", so
    0.01 short was dropped and never reached Xero."""
    owner, entity = shop
    draft = _counted(app, db, entity, owner, expense_total=14.99)  # expected 55.01

    _count(client, owner, entity, {50: 1, 5: 1}, reason="Rounding")

    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (-0.01, "short")


def test_rule_save_next_with_a_difference_needs_a_reason(app, client, db, shop):
    """RULE (owner, 2026-10-15): checked on the server. Flask only asked in the browser, so a
    shortage with no reason could reach Xero."""
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    resp = _count(client, owner, entity, {50: 1})

    assert resp.status_code == 302 and "/reports/new/cash-count" in resp.headers["Location"]
    assert _flashes(client) == ["The count is HKD5.00 short. Add the reason to continue."]
    assert _counts(app, draft) == {}
    assert _row(app, draft)["current_section"] == "cash_count"


def test_save_exit_keeps_a_difference_without_a_reason_for_later(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    resp = _count(client, owner, entity, {50: 1}, action="save_exit")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    row = _row(app, draft)
    assert (row["discrepancy_amount"], row["discrepancy_type"]) == (-5, "short")
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit"]


def test_save_exit_keeps_the_count_and_puts_the_report_back_on_cash_count(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner)

    resp = _count(client, owner, entity, {50: 1, 5: 1}, action="save_exit")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    assert _counts(app, draft) == {50: 1, 5: 1}
    row = _row(app, draft)
    assert row["current_section"] == "cash_count"
    assert row["completed_sections"] == ["opening", "sales", "expenses", "deposit"]


def test_a_negative_expected_cash_is_refused(app, client, db, shop):
    owner, entity = shop
    draft = _counted(app, db, entity, owner, bank_deposit=500)  # 155 - 500 < 0

    resp = _count(client, owner, entity, {50: 1})

    assert resp.status_code == 302 and "/reports/new/cash-count" in resp.headers["Location"]
    assert _flashes(client) == ["Hmm, it looks like your cash balance is negative. Could you fix that first?"]
    assert _counts(app, draft) == {}


def test_with_no_draft_the_count_sends_you_to_opening(app, client, db, shop):
    owner, entity = shop
    resp = _count(client, owner, entity, {50: 1})

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/report/opening")
    assert _flashes(client) == ["I don't see a draft for today yet - let's start with the opening entry."]
