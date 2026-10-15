"""The report wizard's Sales step: the company's methods and what saving the step writes - shared
by the Jinja page (``report/routes/sales.py``) and the Petty Cash API
(``petty_cash_api/routes/sales.py``, minty-petty-cash-web's port), so the two cannot disagree.

Extracted 2026-10-14 under ``tests/test_report_sales_state.py`` (characterisation, green before
and after). Flask's rules, quirks included: a save needs the day's draft (Opening makes it); every
method the page shows gets a ``report_sale_detail`` row, a method left empty a zero; a save makes
the saver the report's creator (``uploaded_by``, "track last editor"). Two bugs were fixed on the
way out, deliberately: the closing balance was computed BEFORE the cash row was rewritten (so a
second save closed on the cash typed the time before), and a method the page never shows (an
``other`` one that is not Cash) was zeroed by every save.
"""
from __future__ import annotations

from loguru import logger

#: A method the Sales page lists but the save has always skipped (the old Deliveroo column).
SKIPPED = "deliveroo_sales"


def sales_methods(entity_id):
    """The company's enabled sales methods, in Settings-page order.

    Returns the ``EntitySaleSetting`` links (each with its catalogue row joined, so
    ``.sale_name`` / ``.value_name`` / ``.type`` read through). One link per catalogue row is
    the table's key since C3, so there is nothing to de-duplicate any more.
    """
    from models.db import EntitySaleSetting, SaleInfo

    return (
        EntitySaleSetting.query.join(SaleInfo, SaleInfo.id == EntitySaleSetting.sale_id)
        .filter(
            EntitySaleSetting.entity_id == entity_id,
            EntitySaleSetting.is_active.is_(True),
        )
        .order_by(EntitySaleSetting.display_order.asc(), SaleInfo.sale_name.asc())
        .all()
    )


def shown(method) -> bool:
    """Whether the Sales page has a field for ``method``: the electronic and delivery ones, and
    Cash (the ``other`` row keyed ``cash_sales``)."""
    from blueprints.shared.enums import SaleType
    from models.db import SaleInfo

    return method.type in (SaleType.ELECTRONIC, SaleType.DELIVERY) or method.value_name == SaleInfo.CASH_VALUE_NAME


def form_key(value_name: str) -> str:
    """The short name the page's field carries (``sales[shop_sales][visa]`` for ``visa_sales``)."""
    return value_name.replace("_sales", "")


def page_methods(entity_id, report_id=None) -> list[dict]:
    """The methods the page shows, in order, each with the report's amount (None when the report
    has no row for it, or there is no report)."""
    from models.db import ReportSaleDetail

    amounts = {}
    if report_id is not None:
        amounts = {
            str(sale_id): amount
            for sale_id, amount in ReportSaleDetail.query.filter_by(report_id=report_id)
            .with_entities(ReportSaleDetail.sale_id, ReportSaleDetail.amount)
            .all()
        }
    return [
        {
            "sale_id": str(m.sale_id),
            "name": m.sale_name,
            "value_name": m.value_name,
            "type": str(getattr(m.type, "value", m.type)),
            "amount": amounts.get(str(m.sale_id)),
        }
        for m in sales_methods(entity_id)
        if m.value_name and shown(m)
    ]


def save_sales(entity_id, user, draft, amounts: dict, action_type: str):
    """Write the Sales step onto ``draft``: one ``report_sale_detail`` row per method the page
    shows (``amounts`` maps value_name -> amount; a missing method is zero), the cash and sales
    totals, the closing balance, the wizard's progress and a history line. Returns the draft."""
    from blueprints.report.services.history import log_history
    from blueprints.report.services.shared import (get_cash_sales_from_detail,
                                                   update_draft_progress,
                                                   update_report_draft_sales_from_detail)
    from blueprints.shared.enums import SaleType
    from models.db import ReportSaleDetail, SaleInfo, db

    draft.uploaded_by = user.username
    cash = float(amounts.get(SaleInfo.CASH_VALUE_NAME) or 0.0)
    draft.cash_sales = cash

    shop_total, delivery_total = cash, 0.0
    for method in sales_methods(entity_id):
        field = method.value_name
        if not field or field == SKIPPED or not shown(method):
            continue
        amount = float(amounts.get(field) or 0.0)
        if field != SaleInfo.CASH_VALUE_NAME:
            if method.type == SaleType.DELIVERY:
                delivery_total += amount
            else:
                shop_total += amount
        row = ReportSaleDetail.query.filter_by(sale_id=method.sale_id, report_id=draft.id).first()
        if row is None:
            db.session.add(ReportSaleDetail(sale_id=method.sale_id, report_id=draft.id, amount=amount))
        else:
            row.amount = amount
    db.session.flush()

    update_report_draft_sales_from_detail(draft)
    # After the rows are written, so the cash is the one just saved.
    draft.closing_balance = (
        (draft.opening_balance or 0)
        + (draft.cash_addition or 0)
        + get_cash_sales_from_detail(draft.id, fallback_value=draft.cash_sales or 0.0)
        - (draft.expenses or 0)
        - (draft.bank_deposit or 0)
    )
    update_draft_progress(draft, action_type, "sales", "expenses")
    db.session.commit()
    logger.info(f"Sales saved on draft {draft.id}: total={draft.total_sales} closing={draft.closing_balance}")

    log_history(
        report_id=draft.id,
        company=entity_id,
        user_id=user.id,
        action="updated",
        field_changed="sales_entry",
        old_value="previous_sales_state",
        new_value=(
            f"Sales: Shop={shop_total}, Delivery={delivery_total}, Total={shop_total + delivery_total}, "
            f"Closing Balance={draft.closing_balance}"
        ),
    )
    return draft


def report_methods(entity_id, report_id) -> list[dict]:
    """``page_methods`` for a report already filled in: the methods the company has on, then any
    method switched off or removed since that still holds an amount on this report (a submitted
    report keeps what it said - Flask's Daily Report listed them too). Deliveroo stays out."""
    from models.db import ReportSaleDetail, SaleInfo

    methods = page_methods(entity_id, report_id)
    listed = {m["sale_id"] for m in methods}
    extra = (
        ReportSaleDetail.query.join(SaleInfo, SaleInfo.id == ReportSaleDetail.sale_id)
        .filter(ReportSaleDetail.report_id == report_id)
        .with_entities(SaleInfo.id, SaleInfo.sale_name, SaleInfo.value_name, SaleInfo.type, ReportSaleDetail.amount)
        .all()
    )
    for sale_id, name, value_name, kind, amount in extra:
        if str(sale_id) in listed or not amount or value_name in (SKIPPED, SaleInfo.CASH_VALUE_NAME):
            continue
        methods.append({"sale_id": str(sale_id), "name": name, "value_name": value_name,
                        "type": str(getattr(kind, "value", kind)), "amount": amount})
    return methods
