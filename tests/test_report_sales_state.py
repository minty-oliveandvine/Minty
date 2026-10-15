"""What the report wizard's Sales step (``report/routes/sales.py``) shows and saves - pinned
before its logic moves into a service that the Jinja page and the Petty Cash API share
(minty-petty-cash-web's port of the step, 2026-10-14).

Characterisation: today's behaviour, quirks included - read off the template context for the
page (GET) and off the database and the flashed message for a save (POST).
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


TODAY = _hk_today()
D2, D3 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)

# the methods a new company starts with (entity/services/shared.py::create_default_entity_settings)
ELECTRONIC = ["Visa", "Alipay", "WeChat Pay", "Mastercard", "UnionPay", "Amex", "Octopus"]
DELIVERY = ["Food Panda", "Keeta", "OpenRice"]


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


@contextmanager
def _captured(app):
    seen = []

    def record(_sender, template, context, **_extra):
        # the method rows are ORM objects that detach with the request: read them while bound
        context = dict(context)
        context["sale_info"] = [
            {"sale_name": s.sale_name, "value_name": s.value_name, "type": str(s.type), "amount": s.amount}
            for s in context.get("sale_info") or []
        ]
        seen.append((template.name, context))

    template_rendered.connect(record, app)
    try:
        yield seen
    finally:
        template_rendered.disconnect(record, app)


def _page(app, client, owner, entity, day=None, *, report_id=None):
    F.login(client, owner)
    base = f"{F.co(client, entity.id)}/petty-cash/reports"
    url = f"{base}/{report_id}/sale" if report_id else f"{base}/new/sale"
    with _captured(app) as seen:
        resp = client.get(url, query_string={"transaction_date": F.iso(day)} if day else None)
    assert resp.status_code == 200, resp.data[:300]
    pages = [ctx for name, ctx in seen if name == "report/sales.html"]
    assert len(pages) == 1
    return pages[0]


def _save(client, owner, entity, day, *, cash=None, shop=None, delivery=None, action="save_next"):
    """``shop`` / ``delivery`` map the form's short name ('visa', 'foodpanda') to the typed text."""
    F.login(client, owner)
    form = {"entity_id": entity.id, "transaction_date": F.iso(day), "action_type": action}
    if cash is not None:
        form["sales[shop_sales][cash]"] = cash
    for short, amount in (shop or {}).items():
        form[f"sales[shop_sales][{short}]"] = amount
    for short, amount in (delivery or {}).items():
        form[f"sales[delivery_sales][{short}]"] = amount
    return client.post("/report/sale", data=form)


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _cat, m in sess.get("_flashes", [])]


def _names(ctx, mtype):
    return [s["sale_name"] for s in ctx["sale_info"] if s["type"] == mtype]


# --- the page ---------------------------------------------------------------------------------------


def test_the_page_lists_the_companys_methods_in_settings_order(app, client, db, shop):
    owner, entity = shop
    _draft(app, db, entity, owner, D3)

    ctx = _page(app, client, owner, entity, D3)

    assert _names(ctx, "electronic") == ELECTRONIC
    assert _names(ctx, "delivery") == DELIVERY
    assert [s["value_name"] for s in ctx["sale_info"] if s["type"] == "other"] == ["cash_sales"]


def test_a_switched_off_method_is_not_shown(app, client, db, shop):
    owner, entity = shop
    with app.app_context():
        F.seed_sales_methods(db, owner, entity, electronic=("Visa",), delivery=("Keeta",))
    _draft(app, db, entity, owner, D3)

    ctx = _page(app, client, owner, entity, D3)

    assert _names(ctx, "electronic") == ["Visa"] and _names(ctx, "delivery") == ["Keeta"]


def test_with_no_draft_the_page_is_empty(app, client, db, shop):
    owner, entity = shop
    ctx = _page(app, client, owner, entity, D3)

    assert ctx["is_draft"] is False and ctx["draft_id"] is None and ctx["current_draft"] is None
    assert set(ctx["sales_amounts"].values()) == {0.0}
    assert all(s["amount"] is None for s in ctx["sale_info"])
    assert ctx["completed_sections"] == ["opening"] and ctx["current_section"] == "sales"
    assert ctx["transaction_date"] == D3


def test_a_draft_brings_back_its_amounts(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3, cashsale_total=50, completed_sections=["opening", "sales"],
                   current_section="expenses")
    _set_amounts(app, db, draft, {"cash_sales": 50, "visa_sales": 30, "foodpanda_sales": 12.5})

    ctx = _page(app, client, owner, entity, D3)

    assert str(ctx["draft_id"]) == draft and ctx["is_draft"] is True
    assert ctx["sales_amounts"]["cash_sales"] == 50
    assert ctx["sales_amounts"]["visa_sales"] == 30 and ctx["sales_amounts"]["foodpanda_sales"] == 12.5
    assert ctx["sales_amounts"]["alipay_sales"] == 0.0  # a method with no row reads as zero
    amounts = {s["value_name"]: s["amount"] for s in ctx["sale_info"]}
    assert amounts["visa_sales"] == 30 and amounts["alipay_sales"] is None
    assert ctx["completed_sections"] == ["opening", "sales"]


def test_a_report_opened_by_id_shows_its_amounts(app, client, db, shop):
    owner, entity = shop
    report = _draft(app, db, entity, owner, D3, status="submitted", cashsale_total=40)
    _set_amounts(app, db, report, {"cash_sales": 40, "keeta_sales": 9})

    ctx = _page(app, client, owner, entity, report_id=report)

    assert ctx["sales_amounts"]["cash_sales"] == 40 and ctx["sales_amounts"]["keeta_sales"] == 9
    assert ctx["is_latest_report"] is True
    assert ctx["transaction_date"] == D3


# --- saving ---------------------------------------------------------------------------------------


def test_save_next_writes_every_method_and_moves_on_to_expenses(app, client, db, shop):
    from models.db import ReportHistory

    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3, expense_total=15, bank_deposit=5)

    resp = _save(client, owner, entity, D3, cash="1,000.50", shop={"visa": "200", "alipay": "0"},
                 delivery={"foodpanda": "33.25"})

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/petty-cash/reports/new/expense?transaction_date={F.iso(D3)}")
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


def test_save_exit_stays_on_sales_and_goes_home(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3)

    resp = _save(client, owner, entity, D3, cash="10", action="save_exit")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/petty-cash")
    row = _row(app, draft)
    assert row["current_section"] == "sales" and row["completed_sections"] == ["opening", "sales"]


def test_a_cleared_method_goes_back_to_zero(app, client, db, shop):
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3)
    _set_amounts(app, db, draft, {"visa_sales": 80})

    _save(client, owner, entity, D3, cash="5", shop={"visa": ""})

    assert _amounts(app, draft)["visa_sales"] == 0


def test_saving_again_closes_on_the_cash_just_typed(app, client, db, shop):
    """Fixed in the service extraction: the closing balance was computed before the cash row was
    rewritten, so a second save closed on the cash typed the time before (170 here)."""
    owner, entity = shop
    draft = _draft(app, db, entity, owner, D3)

    _save(client, owner, entity, D3, cash="50")
    assert _row(app, draft)["closing_balance"] == 170
    _save(client, owner, entity, D3, cash="80")

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

    _save(client, owner, entity, D3, cash="5")

    assert _amounts(app, draft)["tips_sales"] == 7


def test_a_save_makes_the_saver_the_reports_creator(app, client, db, shop):
    owner, entity = shop
    with app.app_context():
        from models.db import UserEntity

        clerk = F.make_user(db, "clerk@test.com")
        db.session.add(UserEntity(user_id=clerk.id, entity_id=entity.id, role="admin", approved=True))
        db.session.commit()
    draft = _draft(app, db, entity, owner, D3)

    _save(client, clerk, entity, D3, cash="1")

    assert str(_row(app, draft)["created_by"]) == clerk.id


def test_with_no_draft_the_save_sends_you_to_opening(app, client, db, shop):
    from models.db import Report

    owner, entity = shop
    resp = _save(client, owner, entity, D3, cash="10")

    assert resp.status_code == 302 and resp.headers["Location"].endswith("/report/opening")
    assert _flashes(client) == ["I don't see a draft yet - let's start with the opening entry."]
    with app.app_context():
        assert Report.query.filter_by(entity_id=entity.id).count() == 0


def test_a_submitted_report_for_the_day_is_not_saved_over(app, client, db, shop):
    owner, entity = shop
    report = _draft(app, db, entity, owner, D3, status="submitted", cashsale_total=40, closing_balance=160)

    _save(client, owner, entity, D3, cash="999")

    assert _flashes(client) == ["I don't see a draft yet - let's start with the opening entry."]
    row = _row(app, report)
    assert row["cash_sales"] == 40 and row["closing_balance"] == 160
