"""The report wizard's Bank Deposit and Cash Count steps for minty-petty-cash-web -
``blueprints/report/services/cash.py``, the same functions the Jinja pages use.

- ``GET /reports/deposit?transaction_date=``: the day's draft, the figures the cash on hand is made
  of, the cash on hand and the saved deposit.
- ``PUT /reports/deposit`` ``{transaction_date, bank_deposit, action}``.
- ``GET /reports/cash-count?transaction_date=``: the figures, the expected cash, the company's
  denominations with the saved counts, the safebox and the saved difference.
- ``PUT /reports/cash-count`` ``{transaction_date, counts: {<denomination id>: n}, safe_box_balance,
  discrepancy_reason, action, bank_deposit?}``: the count; with ``bank_deposit`` the deposit is saved
  first in the same transaction (Part 15's Cash Count stage, where the deposit is its first section).

``REPORT_EDIT_OWN``, as the pages ask. No draft for the day is 409 ``to: "opening"``; a rule's
refusal about one input is 422 ``{error, field}`` (the owner's rules of 2026-10-15: a deposit above
the cash on hand, a difference with no reason on Save & Next); a refusal no input can fix (the cash
on hand is already negative, a report no longer a draft) is 409 ``{error}``.
"""
from __future__ import annotations

from flask import request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user
from blueprints.petty_cash_api.routes.opening import (MAX_AMOUNT, NOT_ALLOWED, _currency_code,
                                                      _day, _may_edit, draft_payload)

NO_DRAFT = "I don't see a draft yet - let's start with the opening entry."
BAD_DATE = "That date doesn't look quite right! Please check the format and try again."
BAD_ACTION = "Choose Save & Next or Save & Exit."
MAX_COUNT = 1_000_000


def _money(value) -> float:
    return float(value or 0)


def _figures(report) -> dict:
    """What the cash on hand and the expected cash are made of, as the pages show them."""
    from blueprints.report.services.cash import cash_on_hand, expected_cash

    return {
        "opening_balance": _money(report.opening_balance),
        "cash_addition": _money(report.cash_addition),
        "cash_sales": _money(report.cash_sales),
        "expenses": _money(report.expenses),
        "bank_deposit": _money(report.bank_deposit),
        "cash_on_hand": _money(cash_on_hand(report)),
        "expected_cash": _money(expected_cash(report)),
    }


def _read(entity_id):
    """``(day, draft)`` or a refusal response."""
    from blueprints.report.services.opening import find_draft

    if not _may_edit(entity_id):
        return None, refuse(NOT_ALLOWED, 403)
    day = _day(request.args.get("transaction_date"))
    if day is None:
        return None, refuse(BAD_DATE, 422)
    draft = find_draft(entity_id, day)
    if draft is None:
        return None, respond({"error": NO_DRAFT, "to": "opening"}, 409)
    return (day, draft), None


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_AMOUNT:
        return None
    return round(float(value), 2)


def _refused(refused):
    from models.db import db

    db.session.rollback()
    if refused.field:
        return respond({"error": refused.message, "field": refused.field}, 422)
    return respond({"error": refused.message}, 409)


def _saved(draft, day, next_step: str) -> dict:
    return {
        "draft_id": str(draft.id),
        "transaction_date": day.isoformat(),
        "current_section": draft.current_section,
        "completed_sections": list(draft.completed_sections or []),
        "next": next_step,
    }


# --- Deposit -----------------------------------------------------------------------------------------


@petty_cash_api_bp.get("/reports/deposit")
def deposit_page():
    entity_id = company()["id"]
    found, refusal = _read(entity_id)
    if refusal is not None:
        return refusal
    day, draft = found
    return respond({"transaction_date": day.isoformat(), "currency_code": _currency_code(entity_id),
                    "draft": draft_payload(draft), **_figures(draft)})


@petty_cash_api_bp.put("/reports/deposit")
def save_deposit_step():
    from blueprints.report.services.cash import CashRefused, save_deposit
    from blueprints.report.services.opening import find_draft

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return refuse("Send the deposit as JSON.", 422)
    day = _day(body.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    amount = _amount(body.get("bank_deposit", 0) if body.get("bank_deposit") is not None else 0)
    if amount is None:
        return respond({"error": "Enter the deposit as an amount of 0 or more.", "field": "bank_deposit"}, 422)
    action = body.get("action")
    if action not in ("next", "exit"):
        return refuse(BAD_ACTION, 422)
    draft = find_draft(entity_id, day)
    if draft is None:
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)
    try:
        save_deposit(draft, user(), amount, "save_next" if action == "next" else "save_exit")
    except CashRefused as refused:
        return _refused(refused)
    return respond(_saved(draft, day, "cash_count" if action == "next" else "dashboard"))


# --- Cash Count --------------------------------------------------------------------------------------


@petty_cash_api_bp.get("/reports/cash-count")
def cash_count_page():
    from blueprints.report.services.cash_denominations import build_denomination_rows

    entity_id = company()["id"]
    found, refusal = _read(entity_id)
    if refusal is not None:
        return refusal
    day, draft = found
    return respond(
        {
            "transaction_date": day.isoformat(),
            "currency_code": _currency_code(entity_id),
            "draft": draft_payload(draft),
            **_figures(draft),
            "denominations": [
                {"id": str(row["cash_id"]), "value": row["value"], "kind": str(row["type"] or ""),
                 "count": int(row["count"] or 0)}
                for row in build_denomination_rows(entity_id, draft.id)
            ],
            "safe_box_balance": _money(draft.safe_box_balance),
            "discrepancy": {
                "amount": _money(draft.discrepancy_amount),
                "kind": draft.discrepancy_type or "none",
                "reason": draft.discrepancy_reason or "",
            },
        }
    )


@petty_cash_api_bp.put("/reports/cash-count")
def save_cash_count_step():
    from blueprints.report.services.cash import CashRefused, save_cash_count, save_deposit_and_count
    from blueprints.report.services.cash_denominations import resolve_denominations_for_entity
    from blueprints.report.services.opening import find_draft

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return refuse("Send the count as JSON.", 422)
    day = _day(body.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    action = body.get("action")
    if action not in ("next", "exit"):
        return refuse(BAD_ACTION, 422)
    raw_counts = body.get("counts") or {}
    if not isinstance(raw_counts, dict):
        return refuse("Send the counts as one number per denomination.", 422)
    known = {str(d.cash_id) for d in resolve_denominations_for_entity(entity_id)}
    counts = {}
    for cash_id, quantity in raw_counts.items():
        if cash_id not in known:
            return refuse("One of those denominations isn't used by this company. Reload the page to see them.", 422)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= MAX_COUNT:
            return respond({"error": "Enter each count as a whole number of 0 or more.", "field": cash_id}, 422)
        counts[cash_id] = quantity
    safe_box = _amount(body.get("safe_box_balance") if body.get("safe_box_balance") is not None else 0)
    if safe_box is None:
        return respond({"error": "Enter the safebox cash as an amount of 0 or more.", "field": "safe_box_balance"}, 422)
    reason = body.get("discrepancy_reason") or ""
    if not isinstance(reason, str):
        return respond({"error": "Write the reason as text.", "field": "discrepancy_reason"}, 422)
    deposit = None
    if "bank_deposit" in body and body["bank_deposit"] is not None:
        deposit = _amount(body["bank_deposit"])
        if deposit is None:
            return respond({"error": "Enter the deposit as an amount of 0 or more.", "field": "bank_deposit"}, 422)

    draft = find_draft(entity_id, day)
    if draft is None:
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)
    action_type = "save_next" if action == "next" else "save_exit"
    try:
        if deposit is None:
            save_cash_count(draft, user(), counts, safe_box, reason, action_type)
        else:
            save_deposit_and_count(draft, user(), deposit, counts, safe_box, reason, action_type)
    except CashRefused as refused:
        return _refused(refused)
    answer = _saved(draft, day, "ending" if action == "next" else "dashboard")
    answer["discrepancy"] = {"amount": _money(draft.discrepancy_amount), "kind": draft.discrepancy_type or "none"}
    return respond(answer)
