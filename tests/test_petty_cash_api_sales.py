"""The Petty Cash API's Sales step (``blueprints/petty_cash_api/routes/sales.py``): the page's read
and its save, through the same service the Jinja page uses (``report/services/sales.py``; that
page's behaviour is pinned by tests/test_report_sales_state.py). The door (token, membership,
module, CORS) is tests/test_petty_cash_api_door.py's.
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
    from blueprints.entity.services.shared import create_default_entity_settings

    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        create_default_entity_settings(entity.id)
        db.session.commit()
    return owner, entity


def _draft(app, db, entity, owner, day, **fields):
    from models.db import Report

    values = {"opening_balance": 100, "cash_addition": 20, "adjusted_opening_balance": 120,
              "closing_balance": 120, "completed_sections": ["opening"], "current_section": "sales"}
    values.update(fields)
    with app.app_context():
        row = Report(entity_id=entity.id, transaction_date=day, status=values.pop("status", "draft"),
                     created_by=owner.id, **values)
        db.session.add(row)
        db.session.commit()
        return str(row.id)


def _set_amounts(app, db, report_id, amounts):
    from models.db import ReportSaleDetail, SaleInfo

    with app.app_context():
        for value_name, amount in amounts.items():
            db.session.add(ReportSaleDetail(report_id=report_id, sale_id=SaleInfo.by_value_name(value_name).id,
                                            amount=amount))
        db.session.commit()


def _amounts(app, report_id):
    from models.db import ReportSaleDetail, SaleInfo

    with app.app_context():
        return dict(ReportSaleDetail.query.join(SaleInfo, SaleInfo.id == ReportSaleDetail.sale_id)
                    .filter(ReportSaleDetail.report_id == report_id)
                    .with_entities(SaleInfo.value_name, ReportSaleDetail.amount).all())


def _row(app, report_id):
    from models.db import Report, db

    with app.app_context():
        row = db.session.get(Report, report_id)
        return {"cash": row.cash_sales, "total": row.total_sales, "closing": row.closing_balance,
                "section": row.current_section, "completed": row.completed_sections}


def _url(entity):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/sales"


def _get(app, client, who, entity, day=D3):
    query = {"transaction_date": F.iso(day)} if day else {}
    return client.get(_url(entity), query_string=query, headers=F.petty_cash_headers(app, who.id, origin=WEB))


def _put(app, client, who, entity, body):
    return client.put(_url(entity), json=body, headers=F.petty_cash_headers(app, who.id, origin=WEB))


def _body(day=D3, *, cash=0, amounts=None, action="next"):
    return {"transaction_date": F.iso(day), "cash_sales": cash, "amounts": amounts or {}, "action": action}


# --- GET ---------------------------------------------------------------------------------------------


def test_the_methods_come_in_settings_order_with_the_days_amounts(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3, cashsale_total=50)
    _set_amounts(app, db, draft, {"cash_sales": 50, "visa_sales": 30, "keeta_sales": 4.5})

    resp = _get(app, client, owner, entity)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["transaction_date"] == F.iso(D3) and body["currency_code"] == "HKD"
    assert body["draft"]["id"] == draft and body["draft"]["completed_sections"] == ["opening"]
    by_type = lambda t: [m["name"] for m in body["methods"] if m["type"] == t]  # noqa: E731
    assert by_type("electronic") == ["Visa", "Alipay", "WeChat Pay", "Mastercard", "UnionPay", "Amex", "Octopus"]
    assert by_type("delivery") == ["Food Panda", "Keeta", "OpenRice"]
    assert {m["type"] for m in body["methods"]} == {"electronic", "delivery"}  # Cash is cash_sales
    amounts = {m["value_name"]: m["amount"] for m in body["methods"]}
    assert amounts["visa_sales"] == 30 and amounts["keeta_sales"] == 4.5 and amounts["alipay_sales"] is None
    assert body["cash_sales"] == 50


def test_with_no_draft_the_page_reads_empty(app, client, db, shop):
    owner, entity = shop
    body = _get(app, client, owner, entity).get_json()

    assert body["draft"] is None and body["cash_sales"] is None
    assert all(m["amount"] is None for m in body["methods"])


def test_a_bad_date_and_a_member_without_the_right_are_refused(app, client, db, shop):
    from models.db import UserEntity

    owner, entity = shop
    assert _get(app, client, owner, entity, day=None).status_code == 422
    with app.app_context():
        base = F.make_user(db, "base@test.com")
        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    assert _get(app, client, base, entity).status_code == 403
    assert _put(app, client, base, entity, _body()).status_code == 403


# --- PUT ---------------------------------------------------------------------------------------------


def test_save_next_writes_the_amounts_and_moves_on_to_expenses(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3, expense_total=15)
    _set_amounts(app, db, draft, {"alipay_sales": 80})

    resp = _put(app, client, owner, entity, _body(cash=1000.5, amounts={"visa_sales": 200, "foodpanda_sales": 33.25}))

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body == {"draft_id": draft, "transaction_date": F.iso(D3), "current_section": "expenses",
                    "completed_sections": ["opening", "sales"], "next": "expenses"}
    amounts = _amounts(app, draft)
    assert amounts["cash_sales"] == 1000.5 and amounts["visa_sales"] == 200 and amounts["foodpanda_sales"] == 33.25
    assert amounts["alipay_sales"] == 0  # left out = emptied
    row = _row(app, draft)
    assert row["cash"] == 1000.5 and row["total"] == 1233.75
    assert row["closing"] == 100 + 20 + 1000.5 - 15


def test_save_exit_stays_on_sales(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner, D3)

    body = _put(app, client, owner, entity, _body(cash=5, action="exit")).get_json()

    assert body["next"] == "dashboard" and body["current_section"] == "sales"


def test_with_no_draft_the_save_goes_back_to_opening(app, client, db, shop):
    owner, entity = shop
    resp = _put(app, client, owner, entity, _body(cash=5))

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "I don't see a draft yet - let's start with the opening entry.", "to": "opening"}


@pytest.mark.parametrize("body, message", [
    ({"transaction_date": "14/10/2026", "action": "next"}, "That date doesn't look quite right!"),
    ({"cash_sales": -1}, "Enter the cash sales as an amount of 0 or more."),
    ({"cash_sales": "12"}, "Enter the cash sales as an amount of 0 or more."),
    ({"amounts": {"visa_sales": -3}}, "Enter the Visa sales as an amount of 0 or more."),
    ({"amounts": {"visa_sales": 100_000_000_000}}, "Enter the Visa sales as an amount of 0 or more."),
    ({"amounts": {"cash_sales": 3}}, "isn't switched on for this company"),
    ({"amounts": {"made_up_sales": 3}}, "isn't switched on for this company"),
    ({"amounts": [1]}, "Send the amounts as one per sales method."),
    ({"action": "later"}, "Choose Save & Next or Save & Exit."),
])
def test_bad_input_is_a_422(app, client, db, shop, body, message):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3)

    resp = _put(app, client, owner, entity, {**_body(), **body})

    assert resp.status_code == 422
    assert message in resp.get_json()["error"]
    assert _amounts(app, draft) == {}
