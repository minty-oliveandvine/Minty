"""The Cash Count stage with Bank Deposit folded in (Part 15.15d, D15-05) - through the routes.

- the old deposit step's page goes on to Cash Count, carrying the day;
- the Cash Count POST saves the deposit and the count together, and marks both wizard sections;
- a negative drawer before the deposit is refused there too, and nothing is saved;
- any difference needs a reason before Save & Next (the user's decision, 2026-10-14): without one
  the count is still saved but the day stays on Cash Count (a page post is sent back with
  ?reason=needed, an XHR gets 422); Save & Exit is never refused for it;
- the stage page draws the deposit, the count, the Check block and the reason.
"""
from __future__ import annotations

from datetime import date

import pytest

import char_factories as F
from test_char_report_lifecycle import count_exactly, draft_totals, money, open_report, post_expenses, post_sales

pytestmark = pytest.mark.char

DAY = date(2026, 9, 1)


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity, electronic=("Visa",), delivery=())
    return owner, entity


def walk_to_cash_count(client, entity, *, opening="1000.00", cash="300.00", expenses=(("Tape", "25.00"),)):
    """Opening -> sales -> expenses (whose Save & Next names the deposit step)."""
    open_report(client, entity, DAY, opening=opening)
    post_sales(client, entity, DAY, cash=cash)
    post_expenses(client, entity, DAY, list(expenses))
    return money(opening) + money(cash) - sum(money(a) for _, a in expenses)


def stage_post(client, entity, counts, *, deposit="0", reason="", action="save_next", xhr=False, safe_box="0"):
    fields = F.denomination_fields(client.application, entity.id)
    form = {"entity_id": entity.id, "transaction_date": F.iso(DAY), "action_type": action,
            "bank_deposit": deposit, "safe_box_balance": safe_box, "discrepancy_reason": reason}
    for field, face in fields.items():
        form[f"actual_cash[{field}]"] = str(counts.get(face, 0))
    headers = {"X-Requested-With": "XMLHttpRequest"} if xhr else {}
    return client.post("/report/cash_count", data=form, headers=headers, follow_redirects=False)


def draft(app, entity):
    from models.db import Report

    with app.app_context():
        r = Report.query.filter_by(entity_id=entity.id, transaction_date=DAY).one()
        return F.snapshot(r, "current_section", "completed_sections", "bank_deposit", "closing_balance",
                          "discrepancy_type", "discrepancy_reason", "actual_cash_total")


def faces(client, entity):
    return F.denomination_fields(client.application, entity.id).values()


def test_the_deposit_step_goes_on_to_cash_count(shop, client):
    owner, entity = shop
    F.login(client, owner)
    walk_to_cash_count(client, entity)

    resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/deposit?transaction_date={F.iso(DAY)}")

    assert resp.status_code == 302
    assert "/petty-cash/reports/new/cash-count" in resp.headers["Location"]
    assert f"transaction_date={F.iso(DAY)}" in resp.headers["Location"]


def test_deposit_and_count_are_saved_together(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    before = walk_to_cash_count(client, entity)
    closing = before - money("500.00")

    resp = stage_post(client, entity, count_exactly(closing, faces(client, entity)), deposit="500.00")

    assert resp.status_code == 302 and "/ending" in resp.headers["Location"]
    totals = draft_totals(client, entity, DAY)
    assert money(totals["bank_deposit"]) == money("500.00")
    assert money(totals["closing_balance"]) == closing
    row = draft(app, entity)
    assert {"deposit", "cash_count"} <= set(row.completed_sections)
    assert row.current_section == "ending"
    assert str(row.discrepancy_type) in ("none", "DiscrepancyType.NONE")


def test_a_negative_drawer_before_the_deposit_is_refused(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    walk_to_cash_count(client, entity, opening="0.00", cash="0.00", expenses=(("Tape", "25.00"),))

    resp = stage_post(client, entity, {}, deposit="10.00")

    assert resp.status_code == 302 and "/cash-count" in resp.headers["Location"]
    row = draft(app, entity)
    assert money(row.bank_deposit or 0) == money("0")
    assert "cash_count" not in (row.completed_sections or [])


def test_a_difference_without_a_reason_stays_on_cash_count_but_keeps_the_count(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    before = walk_to_cash_count(client, entity)
    counted = before - money("20.00")

    resp = stage_post(client, entity, count_exactly(counted, faces(client, entity)))

    assert resp.status_code == 302
    assert "/cash-count" in resp.headers["Location"] and "reason=needed" in resp.headers["Location"]
    row = draft(app, entity)
    assert row.current_section == "cash_count"
    assert "cash_count" not in (row.completed_sections or [])
    assert money(row.actual_cash_total) == counted  # nothing typed is lost
    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Add a reason for the difference to continue." in page


def test_an_xhr_without_a_reason_gets_422(shop, client):
    owner, entity = shop
    F.login(client, owner)
    before = walk_to_cash_count(client, entity)

    resp = stage_post(client, entity, count_exactly(before - money("20.00"), faces(client, entity)), xhr=True)

    assert resp.status_code == 422
    body = resp.get_json()
    assert body["field"] == "discrepancy_reason"
    assert "20.00 short" in body["message"]


def test_a_difference_with_a_reason_moves_on(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    before = walk_to_cash_count(client, entity)

    resp = stage_post(client, entity, count_exactly(before + money("10.00"), faces(client, entity)), reason="float swap")

    assert resp.status_code == 302 and "/ending" in resp.headers["Location"]
    row = draft(app, entity)
    assert row.discrepancy_reason == "float swap"
    assert "cash_count" in row.completed_sections


def test_save_and_exit_is_never_refused_for_the_reason(shop, client, app):
    owner, entity = shop
    F.login(client, owner)
    before = walk_to_cash_count(client, entity)

    resp = stage_post(client, entity, count_exactly(before - money("20.00"), faces(client, entity)), action="save_exit")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    assert draft(app, entity).current_section == "cash_count"


def test_the_stage_page_draws_deposit_count_check_and_reason(shop, client):
    owner, entity = shop
    F.login(client, owner)
    walk_to_cash_count(client, entity)

    html = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/new/cash-count?transaction_date={F.iso(DAY)}").get_data(as_text=True)

    assert 'name="bank_deposit"' in html
    # one task at a time (Daily Closing Phase 1): the deposit, the count in its sheet, the safe box
    assert "Cash taken to the bank" in html and 'id="countSheet"' in html and "Save count" in html
    assert 'id="expected_cash_count_balance"' in html and 'id="variance"' in html and "The numbers match" in html
    assert 'id="discrepancyDescription"' in html
    assert 'aria-current="step"' in html and 'data-stage="cash_count"' in html
    assert "cdn.tailwindcss.com" not in html
