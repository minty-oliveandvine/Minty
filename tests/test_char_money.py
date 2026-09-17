"""Characterisation: money is exact, in every figure the report stores or shows.

C4 turns every ``Float`` money column into ``numeric(14,2)``. These tests pin the arithmetic
the user sees: a figure derived from cents must BE cents - not ``0.30000000000000004`` that
a display filter happens to round. ``exact()`` therefore checks the raw value the endpoint
returned, not a quantised copy of it (which ``test_char_report_lifecycle.money`` does, and
which would hide the drift).

Written before the model change (B3 group "money exactness"); the cases that only hold with
``numeric`` are exact since C4: the columns are numeric(14,2) and every figure the code computes
from them goes through ``cents()`` on its way out, so SQLite (which has no numeric type) agrees.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import char_factories as F
from test_char_report_lifecycle import (draft_totals, open_report, post_cash_count, post_deposit,
                                        post_expenses, post_sales, walk_to_cash_count)

pytestmark = pytest.mark.char


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
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity, electronic=("Visa", "Alipay"), delivery=("Foodpanda",))
    return owner, entity


DAY = date(2026, 9, 1)


def exact(value) -> Decimal:
    """The value as the endpoint returned it, as a Decimal - and it must already be cents."""
    d = Decimal(str(value))
    assert d == d.quantize(Decimal("0.01")), f"{value!r} is not an exact amount of cents"
    return d


# ---- the figures a day accumulates -------------------------------------------------------------


def test_ten_dimes_of_expenses_are_exactly_one_dollar(shop, client):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, DAY, opening="1000.00")
    post_sales(client, entity, DAY, cash="100")
    post_expenses(client, entity, DAY, [(f"Item {i}", "0.10") for i in range(10)])

    totals = draft_totals(client, entity, DAY)
    assert exact(totals["total_expenses"]) == Decimal("1.00")
    assert exact(totals["closing_balance"]) == Decimal("1099.00")


def test_sales_of_a_dime_and_two_dimes_are_thirty_cents(shop, client):
    """Holds today only because the totals are rounded on the way out; pinned so it keeps
    holding once the rounding goes with the Float columns."""
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, DAY, opening="0.00")
    post_sales(client, entity, DAY, cash="0.10", by_method={"visa_sales": "0.20", "foodpanda_sales": "0.70"})

    totals = draft_totals(client, entity, DAY)
    assert exact(totals["total_sales"]) == Decimal("1.00")
    assert exact(totals["cash_sales"]) == Decimal("0.10")


def test_a_deposit_with_cents_closes_the_balance_to_the_cent(shop, client):
    owner, entity = shop
    F.login(client, owner)
    open_report(client, entity, DAY, opening="1234.56", addition="0.44")
    post_sales(client, entity, DAY, cash="765.43")
    post_expenses(client, entity, DAY, [("Tape", "0.99"), ("Milk", "10.01")])
    post_deposit(client, entity, DAY, "1000.00")

    totals = draft_totals(client, entity, DAY)
    # 1234.56 + 0.44 + 765.43 - 11.00 - 1000.00
    assert exact(totals["closing_balance"]) == Decimal("989.43")
    assert exact(totals["total_expenses"]) == Decimal("11.00")


def test_a_cash_count_in_small_coins_adds_exactly(shop, client, app):
    """Three 10-cent coins are 0.30, and a count that matches the balance has no discrepancy."""
    owner, entity = shop
    F.login(client, owner)
    walk_to_cash_count(client, entity, DAY, opening="0.00", cash="0.30", expenses=(), deposit="0.00")
    assert 0.1 in F.denomination_fields(app, entity.id).values(), "the currency has no 10-cent coin"

    post_cash_count(client, entity, DAY, {0.1: "3"})  # face value -> quantity

    totals = draft_totals(client, entity, DAY)
    assert exact(totals.get("discrepancy_amount", 0)) == Decimal("0.00")
    assert exact(totals["closing_balance"]) == Decimal("0.30")


def test_the_report_detail_repeats_the_totals_to_the_cent(shop, client):
    """What the detail page prints is what the wizard computed - the same Decimal, not a
    re-summed float."""
    from test_char_report_lifecycle import dollar_figures, post_report

    owner, entity = shop
    F.login(client, owner)
    report_id, closing = post_report(client, entity, DAY, opening="500.50", cash="249.50",
                                     expenses=(("Tape", "0.10"),), deposit="100.00")

    page = client.get(f"/report/{report_id}")
    assert page.status_code == 200, page.data[:300]
    figures = dollar_figures(page.get_data(as_text=True))
    for figure in ("500.50", "249.50", "0.10", "100.00", str(closing)):
        assert Decimal(figure) in figures, (figure, sorted(figures)[:12])
