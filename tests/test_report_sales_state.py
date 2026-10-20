"""The report wizard's Sales step (``report/services/sales.py``), pinned through the Jinja page
(``report/routes/sales.py``) before its logic moved into that service (minty-petty-cash-web's port,
2026-10-14). Flask's HTML frontend was deleted 2026-10-20: the step's read and save are
tests/test_petty_cash_api_sales.py's now; what is left here is what that file does not pin (a
switched-off method, the totals and history a save writes, a second save, a method with no field,
the saver, a submitted day), driven through the Petty Cash API's ``/reports/sales``.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import char_factories as F
import pytest

pytestmark = pytest.mark.char


def _hk_today():
    from models.db import tz

    return datetime.now(tz).date()


TODAY = _hk_today()
D2, D3 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)


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
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
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


def _amounts(app, report_id):
    """value_name -> amount of the report's report_sale_detail rows."""
    from models.db import ReportSaleDetail, SaleInfo

    with app.app_context():
        rows = (ReportSaleDetail.query.join(SaleInfo, SaleInfo.id == ReportSaleDetail.sale_id)
                .filter(ReportSaleDetail.report_id == report_id)
                .with_entities(SaleInfo.value_name, ReportSaleDetail.amount).all())
        return {v: a for v, a in rows}


def _set_amounts(app, db, report_id, amounts):
    from models.db import ReportSaleDetail, SaleInfo

    with app.app_context():
        for value_name, amount in amounts.items():
            sale = SaleInfo.by_value_name(value_name)
            db.session.add(ReportSaleDetail(report_id=report_id, sale_id=sale.id, amount=amount))
        db.session.commit()


def _row(app, report_id):
    from models.db import Report

    with app.app_context():
        row = Report.query.get(report_id)
        return {c: getattr(row, c) for c in (
            "status", "cash_sales", "nocashsale_total", "total_sales", "shop_sales", "delivery_sales",
            "closing_balance", "current_section", "completed_sections", "created_by",
        )}


def _url(entity):
    return f"/api/petty-cash/v1/companies/{entity.id}/reports/sales"


def _page(app, client, owner, entity, day):
    resp = client.get(_url(entity), query_string={"transaction_date": F.iso(day)},
                      headers=F.petty_cash_headers(app, owner.id))
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _save(client, owner, entity, day, *, cash=0, amounts=None, action="next"):
    """``amounts``: value_name -> amount for the Electronic / Delivery methods."""
    return client.put(_url(entity), json={"transaction_date": F.iso(day), "cash_sales": cash,
                                          "amounts": amounts or {}, "action": action},
                      headers=F.petty_cash_headers(client.application, owner.id))


def _names(page, mtype):
    return [m["name"] for m in page["methods"] if m["type"] == mtype]


# --- the read ----------------------------------------------------------------------------------------


def test_a_switched_off_method_is_not_shown(app, client, db, shop):
    owner, entity = shop
    with app.app_context():
        F.seed_sales_methods(db, owner, entity, electronic=("Visa",), delivery=("Keeta",))
    _draft(app, db, entity, owner, D3)

    page = _page(app, client, owner, entity, D3)

    assert _names(page, "electronic") == ["Visa"] and _names(page, "delivery") == ["Keeta"]


# --- saving ---------------------------------------------------------------------------------------


def test_save_next_writes_every_method_its_totals_and_its_history(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3, expense_total=15, bank_deposit=5)

    resp = _save(client, owner, entity, D3, cash=1000.5, amounts={"visa_sales": 200, "foodpanda_sales": 33.25})

    assert resp.status_code == 200, resp.get_json()
    amounts = _amounts(app, draft)
    assert amounts["cash_sales"] == 1000.5 and amounts["visa_sales"] == 200 and amounts["foodpanda_sales"] == 33.25
    assert amounts["alipay_sales"] == 0 and amounts["openrice_sales"] == 0  # every shown method gets a row
    row = _row(app, draft)
    assert (row["cash_sales"], row["nocashsale_total"], row["total_sales"]) == (1000.5, 233.25, 1233.75)
    assert (row["shop_sales"], row["delivery_sales"]) == (1200.5, 33.25)
    assert row["closing_balance"] == 100 + 20 + 1000.5 - 15 - 5
    assert row["current_section"] == "expenses" and row["completed_sections"] == ["opening", "sales"]
    with app.app_context():
        history = ReportHistory.query.filter_by(report_id=draft).all()
    assert [(h.action, h.field_changed) for h in history] == [("updated", "sales_entry")]


def test_saving_again_closes_on_the_cash_just_typed(app, client, db, shop):
    """Fixed in the service extraction: the closing balance was computed before the cash row was
    rewritten, so a second save closed on the cash typed the time before (170 here)."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3)

    _save(client, owner, entity, D3, cash=50)
    assert _row(app, draft)["closing_balance"] == 170
    _save(client, owner, entity, D3, cash=80)

    row = _row(app, draft)
    assert row["cash_sales"] == 80
    assert row["closing_balance"] == 200  # 100 + 20 + 80


def test_a_method_the_page_does_not_show_keeps_its_amount(app, client, db, shop):
    """Fixed in the service extraction: an ``other`` method that is not Cash has no field on the
    page, and every save used to zero it."""
    from models.db import EntitySaleSetting, SaleInfo
    from blueprints.shared.enums import SaleType

    owner, entity = shop
    with app.app_context():
        tips = SaleInfo.ensure("Tips", SaleType.OTHER, value_name="tips_sales")
        db.session.add(EntitySaleSetting(entity_id=entity.id, sale_id=tips.id, is_active=True, display_order=9))
        db.session.commit()
    draft = _draft(app, db, entity, owner, D3)
    _set_amounts(app, db, draft, {"tips_sales": 7})

    _save(client, owner, entity, D3, cash=5)

    assert _amounts(app, draft)["tips_sales"] == 7


def test_a_save_makes_the_saver_the_reports_creator(app, client, db, shop):
    owner, entity = shop
    with app.app_context():
        from models.db import UserEntity

        clerk = F.make_user(db, "clerk@test.com")
        db.session.add(UserEntity(user_id=clerk.id, entity_id=entity.id, role="admin", approved=True))
        db.session.commit()
    draft = _draft(app, db, entity, owner, D3)

    _save(client, clerk, entity, D3, cash=1)

    assert str(_row(app, draft)["created_by"]) == clerk.id


def test_a_submitted_report_for_the_day_is_not_saved_over(app, client, db, shop):
    owner, entity = shop
    report = _draft(app, db, entity, owner, D3, status="submitted", cashsale_total=40, closing_balance=160)

    resp = _save(client, owner, entity, D3, cash=999)

    assert resp.status_code == 409
    assert resp.get_json() == {"error": "I don't see a draft yet - let's start with the opening entry.", "to": "opening"}
    row = _row(app, report)
    assert row["cash_sales"] == 40 and row["closing_balance"] == 160
