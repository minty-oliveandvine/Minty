"""The report wizard's Opening step for minty-petty-cash-web: what the page shows and its save -
``blueprints/report/services/opening.py``, the same functions the Jinja page uses.

- ``GET /reports/opening?transaction_date=YYYY-MM-DD``: the day's draft, or what the day opens
  from; ``REPORT_EDIT_OWN``, as the page asks.
- ``PUT /reports/opening`` ``{transaction_date, cash_addition, withdrawal, action}``: the save. The
  opening balance is the server's own "Starting Cash Balance" - the Jinja page takes it from a
  hidden field the browser could change; this route takes nothing it can work out itself.

A date rule's refusal is a 409 whose sentence the app shows on the dashboard (where the Jinja page
sends it); a negative balance and a submitted day are refusals too; bad input is a 422.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from flask import request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOT_ALLOWED = "You do not have permission to edit reports for this entity."
#: What the amount field accepts (Flask's currency.js): at most 11 whole digits and 2 decimals.
MAX_AMOUNT = 99_999_999_999.99


def _day(raw) -> date | None:
    if not isinstance(raw, str) or not _ISO_DATE.match(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _money(value) -> float:
    return float(value or 0)


def _text(value) -> str | None:
    """An enum or a string as its word; None stays None."""
    return None if value is None else str(getattr(value, "value", value))


def _may_edit(entity_id) -> bool:
    from services.permission_policy import Permission, has_permission

    return has_permission(user(), Permission.REPORT_EDIT_OWN, entity_id)


def _currency_code(entity_id) -> str | None:
    """The company's ISO currency code (what every amount on the page is written with)."""
    from models.db import CurrencyInfo, Entity, db

    org = db.session.get(Entity, entity_id)
    currency = db.session.get(CurrencyInfo, org.currency_id) if org is not None and org.currency_id else None
    return currency.currency_code.strip() if currency is not None and currency.currency_code else None


def opening_payload(entity_id, selected: date | None) -> dict:
    from blueprints.report.services.opening import opening_state, starting_cash_balance
    from blueprints.report.services.shared import header_publishing_status_for

    state = opening_state(entity_id, selected)
    draft = state["draft"]
    # The page's date: the chosen day, else the draft's, else the server's today (Flask's datenow).
    day = selected or state["next_transaction_date"] or datetime.now().date()
    cash_addition = (draft.cash_addition if draft and draft.cash_addition else None) or state["report"]["cash_addition"] or None
    return {
        "transaction_date": day.isoformat(),
        "currency_code": _currency_code(entity_id),
        "draft": (
            {
                "id": str(draft.id),
                "status": _text(draft.status),
                "current_section": draft.current_section,
                "completed_sections": list(draft.completed_sections or []),
                "xero_integrated": bool(draft.xero_integrated),
                "publishing_status": _text(header_publishing_status_for(report_id=draft.id)),
            }
            if draft
            else None
        ),
        "starting_cash_balance": _money(starting_cash_balance(state)),
        "yesterday_closing_balance": _money(state["yesterday_closing_balance"]),
        "safebox_balance": _money(state["safebox_balance"]),
        "cash_addition": float(cash_addition) if cash_addition is not None else None,
        "withdrawal": state["report"]["withdrawal"],
    }


@petty_cash_api_bp.get("/reports/opening")
def opening_page():
    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    raw = request.args.get("transaction_date")
    selected = _day(raw) if raw else None
    if raw and selected is None:
        return refuse("That date doesn't look quite right! Please check the format and try again.", 422)
    return respond(opening_payload(entity_id, selected))


def _valid_save(body) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, "Send the opening as JSON."
    day = _day(body.get("transaction_date"))
    if day is None:
        return None, "That date doesn't look quite right! Please check the format and try again."
    amount = body.get("cash_addition", 0)
    if amount is None:
        amount = 0
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0 or amount > MAX_AMOUNT:
        return None, "Enter the cash added to the drawer as an amount of 0 or more."
    withdrawal = body.get("withdrawal")
    if withdrawal not in ("company", "personal", None):
        return None, "That withdrawal type doesn't look quite right to me."
    action = body.get("action")
    if action not in ("next", "exit"):
        return None, "Choose Save & Next or Save & Exit."
    return {"day": day, "cash_addition": round(float(amount), 2), "withdrawal": withdrawal,
            "action_type": "save_next" if action == "next" else "save_exit"}, None


@petty_cash_api_bp.put("/reports/opening")
def save_opening_step():
    from blueprints.report.services.opening import (NEGATIVE, OpeningRefused, find_draft,
                                                    first_report_opening,
                                                    new_report_date_problem, opening_state,
                                                    save_opening, starting_cash_balance,
                                                    submitted_report_for)

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    save, problem = _valid_save(request.get_json(silent=True))
    if problem:
        return refuse(problem, 422)
    day = save["day"]

    problem = new_report_date_problem(entity_id, day)
    if problem:
        return respond({"error": problem, "to": "dashboard"}, 409)

    opening_balance = float(starting_cash_balance(opening_state(entity_id, day)))
    # A company's FIRST report opens at its onboarding balance, as the Jinja page saves it.
    onboarding_opening = first_report_opening(entity_id, day)
    if onboarding_opening is not None:
        opening_balance = float(onboarding_opening)
    if opening_balance + save["cash_addition"] < 0:
        return respond({"error": NEGATIVE, "to": "opening"}, 409)
    if submitted_report_for(entity_id, day):
        return respond({"error": f"A report for {day} already exists. Please delete it first.", "to": "dashboard"}, 409)

    try:
        draft = save_opening(
            entity_id,
            user(),
            day,
            opening_balance,
            save["cash_addition"],
            save["withdrawal"],
            save["action_type"],
            existing_draft=find_draft(entity_id, day),
        )
    except OpeningRefused as refused:
        return respond({"error": refused.message, "to": refused.to}, 409)
    except ValueError as exc:
        return respond({"error": str(exc), "to": "dashboard"}, 409)

    return respond(
        {
            "draft_id": str(draft.id),
            "transaction_date": day.isoformat(),
            "current_section": draft.current_section,
            "completed_sections": list(draft.completed_sections or []),
            "next": "sales" if save["action_type"] == "save_next" else "dashboard",
        }
    )
