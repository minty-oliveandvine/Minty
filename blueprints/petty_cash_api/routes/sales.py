"""The report wizard's Sales step for minty-petty-cash-web: the company's methods with the day's
amounts, and the save - ``blueprints/report/services/sales.py``, the same functions the Jinja page
uses.

- ``GET /reports/sales?transaction_date=YYYY-MM-DD``: the day's draft (None before Opening made
  one), the electronic and delivery methods in Settings order with its amounts, and its cash sales.
- ``PUT /reports/sales`` ``{transaction_date, cash_sales, amounts: {value_name: amount}, action}``:
  the save. A method left out is zero, as an emptied field is on the Jinja page.

``REPORT_EDIT_OWN``, as the page asks. With no draft for the day the save is a 409 that sends the
app back to Opening (where the Jinja page goes); bad input is a 422.
"""
from __future__ import annotations

from flask import request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user
from blueprints.petty_cash_api.routes.opening import (MAX_AMOUNT, NOT_ALLOWED, _currency_code,
                                                      _day, _may_edit, draft_payload)

NO_DRAFT = "I don't see a draft yet - let's start with the opening entry."
BAD_DATE = "That date doesn't look quite right! Please check the format and try again."


def _cash(draft, methods) -> float | None:
    """What the page's cash field shows: the Cash method's row, else the report's cash column."""
    from models.db import SaleInfo

    row = next((m["amount"] for m in methods if m["value_name"] == SaleInfo.CASH_VALUE_NAME), None)
    if row:
        return float(row)
    return float(draft.cash_sales) if draft is not None and draft.cash_sales else None


def sales_payload(entity_id, day) -> dict:
    from blueprints.report.services.opening import find_draft
    from blueprints.report.services.sales import page_methods
    from models.db import SaleInfo

    draft = find_draft(entity_id, day)
    methods = page_methods(entity_id, draft.id if draft is not None else None)
    return {
        "transaction_date": day.isoformat(),
        "currency_code": _currency_code(entity_id),
        "draft": draft_payload(draft),
        "methods": [
            {**m, "amount": float(m["amount"]) if m["amount"] else None}
            for m in methods
            if m["value_name"] != SaleInfo.CASH_VALUE_NAME
        ],
        "cash_sales": _cash(draft, methods),
    }


@petty_cash_api_bp.get("/reports/sales")
def sales_page():
    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    day = _day(request.args.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    return respond(sales_payload(entity_id, day))


def _amount(value) -> float | None:
    """A typed amount: 0 to MAX_AMOUNT, at most 2 decimals; None when it is not one."""
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_AMOUNT:
        return None
    return round(float(value), 2)


def _valid_save(body, value_names) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, "Send the sales as JSON."
    day = _day(body.get("transaction_date"))
    if day is None:
        return None, BAD_DATE
    cash = _amount(body.get("cash_sales"))
    if cash is None:
        return None, "Enter the cash sales as an amount of 0 or more."
    raw = body.get("amounts") or {}
    if not isinstance(raw, dict):
        return None, "Send the amounts as one per sales method."
    amounts = {}
    for value_name, value in raw.items():
        if value_name not in value_names:
            return None, "One of those sales methods isn't switched on for this company. Reload the page to see its methods."
        amount = _amount(value)
        if amount is None:
            return None, f"Enter the {value_names[value_name]} sales as an amount of 0 or more."
        amounts[value_name] = amount
    action = body.get("action")
    if action not in ("next", "exit"):
        return None, "Choose Save & Next or Save & Exit."
    return {"day": day, "cash": cash, "amounts": amounts,
            "action_type": "save_next" if action == "next" else "save_exit"}, None


@petty_cash_api_bp.put("/reports/sales")
def save_sales_step():
    from blueprints.report.services.opening import find_draft
    from blueprints.report.services.sales import page_methods, save_sales
    from models.db import SaleInfo

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    value_names = {
        m["value_name"]: m["name"] for m in page_methods(entity_id) if m["value_name"] != SaleInfo.CASH_VALUE_NAME
    }
    save, problem = _valid_save(request.get_json(silent=True), value_names)
    if problem:
        return refuse(problem, 422)

    draft = find_draft(entity_id, save["day"])
    if draft is None:
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)

    amounts = {**save["amounts"], SaleInfo.CASH_VALUE_NAME: save["cash"]}
    draft = save_sales(entity_id, user(), draft, amounts, save["action_type"])
    return respond(
        {
            "draft_id": str(draft.id),
            "transaction_date": save["day"].isoformat(),
            "current_section": draft.current_section,
            "completed_sections": list(draft.completed_sections or []),
            "next": "expenses" if save["action_type"] == "save_next" else "dashboard",
        }
    )
