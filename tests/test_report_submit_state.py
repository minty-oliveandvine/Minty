"""What the report wizard's last step does when the day is submitted - ``report/services/submit.py``,
pinned before the submit moved into that service (minty-petty-cash-web's port, 2026-10-15). Driven
through the Jinja Close page's POST until Flask's HTML frontend was deleted (2026-10-20); now
through the Petty Cash API's ``POST /reports/submit``, which answers a refusal ``{error, to}`` (the
step that fixes it) where the page redirected with a flash.

Characterisation, green before and after the extraction. Tests marked
FIXED or RULE pin what the extraction changed deliberately: a failure during submit used to delete
a day with no expense lines (FIXED: nothing is ever deleted); a difference saved before a later
Deposit / Sales / Expenses change was submitted stale (RULE, the owner 2026-10-15: refused, back to
Cash Count).
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
ALL = ["opening", "sales", "expenses", "deposit", "cash_count"]


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
        owner = F.make_user(db, "owner@test.com", first_name="Olive")
        entity = F.make_entity(db, owner, currency=currency, country=country)
    return owner, entity


def _ready(app, db, entity, owner, *, counts=None, day=D3, item="Advertising", **fields):
    """A draft with every step done: opening 100 + 20 added + 50 cash sales - 15 expenses - 100
    deposit = 55 expected, counted as one 50 note and one 5 coin unless ``counts`` (face -> n)."""
    from blueprints.report.services.cash_denominations import (resolve_denominations_for_entity,
                                                               save_cash_count_details)
    from models.db import Report, ShopExpense

    values = {"opening_balance": 100, "cash_addition": 20, "adjusted_opening_balance": 120, "cashsale_total": 50,
              "expense_total": 15, "bank_deposit": 100, "closing_balance": 55, "safe_box_balance": 0,
              "discrepancy_amount": 0, "discrepancy_type": "none", "completed_sections": list(ALL),
              "current_section": "ending"}
    values.update(fields)
    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=day, status="draft", created_by=owner.id, **values)
        db.session.add(row)
        db.session.flush()
        if item is not None:  # None: a day with no expense lines
            db.session.add(ShopExpense(report_id=row.id, item=item, amount=15))
        by_face = {float(d.cash_value): d.cash_id for d in resolve_denominations_for_entity(entity.id)}
        save_cash_count_details(row.id, {by_face[f]: n for f, n in (counts or {50: 1, 5: 1}).items()})
        db.session.commit()
        return str(row.id)


def _row(app, report_id):
    from models.db import Report, db

    with app.app_context():
        row = db.session.get(Report, report_id)
        if row is None:
            return None
        return {"status": str(getattr(row.status, "value", row.status)), "closing": row.closing_balance,
                "submitted_at": row.submitted_at, "section": row.current_section,
                "completed": row.completed_sections, "created_by": str(row.created_by)}


def _stock(app, entity):
    """face value -> cash in stock (money) for the company."""
    from models.db import CashInfo, EntityCashDetail

    with app.app_context():
        rows = (EntityCashDetail.query.join(CashInfo, CashInfo.id == EntityCashDetail.cash_id)
                .filter(EntityCashDetail.entity_id == entity.id)
                .with_entities(CashInfo.cash_value, EntityCashDetail.cash_instock).all())
        return {float(v): float(m) for v, m in rows if m}


def _submit(client, who, entity, day=D3):
    """Submit the day as ``who`` through the Petty Cash API (``POST /reports/submit``)."""
    return client.post(f"/api/petty-cash/v1/companies/{entity.id}/reports/submit",
                       json={"transaction_date": F.iso(day)},
                       headers=F.petty_cash_headers(client.application, who.id))


def _refused(resp, error, to):
    assert resp.status_code == 409, resp.get_json()
    assert resp.get_json() == {"error": error, "to": to}


# --- submitting --------------------------------------------------------------------------------------


def test_submitting_posts_the_day_and_says_its_outcome_is_next(app, client, db, shop):
    owner, entity = shop
    report = _ready(app, db, entity, owner)

    resp = _submit(client, owner, entity)

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["report_id"] == report and resp.get_json()["next"] == "submitted"
    row = _row(app, report)
    assert row["status"] == "submitted" and row["submitted_at"] is not None
    assert row["closing"] == 55
    assert row["section"] == "submitted"
    assert set(ALL) <= set(row["completed"])
    assert _stock(app, entity) == {50: 50, 5: 5}  # the stock follows the submitted count


def test_a_short_count_closes_on_what_was_counted(app, client, db, shop):
    owner, entity = shop
    report = _ready(app, db, entity, owner, counts={50: 1}, discrepancy_amount=-5, discrepancy_type="short",
                    discrepancy_reason="Change")

    _submit(client, owner, entity)

    assert _row(app, report)["closing"] == 50  # 55 expected + (-5)


def test_the_submitter_becomes_the_reports_creator(app, client, db, shop):
    from models.db import UserEntity

    owner, entity = shop
    with app.app_context():
        clerk = F.make_user(db, "clerk@test.com")
        db.session.add(UserEntity(user_id=clerk.id, entity_id=entity.id, role="admin", approved=True))
        db.session.commit()
    report = _ready(app, db, entity, owner)

    _submit(client, clerk, entity)

    assert _row(app, report)["created_by"] == clerk.id


# --- refusals (a second submit: tests/test_petty_cash_api_close.py) -----------------------------------


def test_a_step_not_done_is_refused_and_sent_to_that_step(app, client, db, shop):
    owner, entity = shop
    report = _ready(app, db, entity, owner, completed_sections=["opening", "sales", "expenses", "cash_count"])

    _refused(_submit(client, owner, entity), "Finish Cash Count before you submit the day.", "cash_count")
    assert _row(app, report)["status"] == "draft"


def test_a_negative_expected_cash_is_refused(app, client, db, shop):
    owner, entity = shop
    report = _ready(app, db, entity, owner, bank_deposit=500)

    _refused(_submit(client, owner, entity),
             "Hmm, it looks like your cash balance is negative. Could you fix that first?", "cash_count")
    assert _row(app, report)["status"] == "draft"


def test_fixed_a_failure_during_submit_leaves_the_draft_as_it_was(app, client, db, shop, monkeypatch):
    """FIXED: any failure inside the submit was followed by a "clean-up" that deleted a day with no
    expense lines - its sales and counts with it - and the person was only told to try again."""
    owner, entity = shop
    report = _ready(app, db, entity, owner, item=None, expense_total=0, bank_deposit=115)  # expected 55

    def fail(*_args, **_kwargs):
        raise RuntimeError("the closing could not be worked out")

    # Patched where nothing binds it at import (the conftest re-import trap).
    monkeypatch.setattr("blueprints.report.services.submit.closing_at_submit", fail)
    resp = _submit(client, owner, entity)

    assert resp.status_code == 500
    row = _row(app, report)
    assert row["status"] == "draft" and row["closing"] == 55 and row["completed"] == ALL


def test_fixed_an_expense_line_without_an_item_is_refused_and_sent_to_expenses(app, client, db, shop):
    """FIXED: it used to raise inside the submit, and only a failing clean-up kept the draft."""
    owner, entity = shop
    report = _ready(app, db, entity, owner, item="")

    _refused(_submit(client, owner, entity),
             "An expense has no account or no amount. Fix it in Expenses, then submit.", "expenses")
    assert _row(app, report)["status"] == "draft"


def test_rule_a_difference_saved_before_a_later_deposit_change_is_refused(app, client, db, shop):
    """RULE (owner, 2026-10-15): Flask kept the count's difference although the deposit changed
    after it, so the closing (and Xero) were wrong. Back to Cash Count instead."""
    owner, entity = shop
    report = _ready(app, db, entity, owner, bank_deposit=90)  # expected is 65 now; 55 was counted

    _refused(_submit(client, owner, entity),
             "The figures changed after the cash count. Check the cash count again, then submit.", "cash_count")
    assert _row(app, report)["status"] == "draft"


def test_rule_a_difference_without_its_reason_is_refused(app, client, db, shop):
    """RULE (owner, 2026-10-15): a difference needs a reason - at submit too."""
    owner, entity = shop
    report = _ready(app, db, entity, owner, counts={50: 1}, discrepancy_amount=-5, discrepancy_type="short")

    _refused(_submit(client, owner, entity),
             "The count has a difference with no reason. Add the reason in Cash Count.", "cash_count")
    assert _row(app, report)["status"] == "draft"


def test_the_submitted_sections_are_stored(app, client, db, shop):
    """Flask appended "submitted" in place without flag_modified; the service stores it."""
    owner, entity = shop
    report = _ready(app, db, entity, owner)

    _submit(client, owner, entity)

    assert _row(app, report)["completed"] == ALL + ["ending", "submitted"]
