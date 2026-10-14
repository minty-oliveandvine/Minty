"""The Petty Cash dashboard's reads and its one write, for minty-petty-cash-web's port of
``entity/entity_dashboard_v2.html``.

- ``GET /home``: everything the page computes (``entity/services/dashboard.py`` - the same
  function the Jinja page reads), plus what this person may do there.
- ``POST /deposit-correction``: the "Before You Start" correction of the previous day's bank
  deposit (``report/routes/legacy.py::correct_previous_deposit``, which the Jinja page's
  ``/api/check-dept-bank-yest`` calls too). It can reverse a deposit in Xero, so it asks
  ``REPORT_EDIT_ENTITY`` and takes nothing it has not checked.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from flask import request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOT_ALLOWED = "You don't have permission to change this company's reports."


def _money(value) -> float:
    return float(value or 0)


def home_payload(entity_id: str, person) -> dict:
    from blueprints.entity.services.dashboard import dashboard_state, iso
    from models.db import UserEntity, db
    from services.permission_policy import Permission, has_permission, is_superuser_readonly

    state = dashboard_state(entity_id)
    # Quick Actions' "N users". The Jinja page counts `org.users|length + 1`, but entities have no
    # `users`, so it always says "1 user" - this is the count it meant: the company's members.
    user_count = (
        db.session.query(db.func.count(UserEntity.user_id))
        .filter(UserEntity.entity_id == entity_id, UserEntity.approved.is_(True))
        .scalar()
    )
    latest, draft = state["latest"], state["draft"]
    return {
        "server_today": state["server_today_hk"],
        "user_count": int(user_count or 0),
        "currency_code": state["currency_code"],
        "latest": {
            "date": iso(latest["date"]),
            "closing_balance": _money(latest["closing_balance"]),
            "deposit": _money(latest["deposit"]),
            "deposit_bank_name": latest["deposit_bank_name"],
            "deposit_bank_number": latest["deposit_bank_number"],
            "deposit_correction_missing_settings": latest["deposit_correction_missing_settings"],
            "can_correct_deposit": latest["can_correct_deposit"],
            "submitter_first_name": state["latest_submitter_first_name"],
        },
        "draft": (
            {
                "id": str(draft["id"]),
                "current_section": draft["current_section"],
                "completed_sections": list(draft["completed_sections"]),
                "last_edit_seconds": draft["last_edit_seconds"],
            }
            if draft
            else None
        ),
        # The EARLIEST draft's date: the calendar's onboarding floor and the Continue date.
        "draft_date": iso(state["draft_date"]),
        "published": {
            day: {
                "id": str(row["id"]),
                "closing_balance": _money(row["closing_balance"]),
                "bank_deposit": _money(row["bank_deposit"]),
                "xero_integrated": bool(row["xero_integrated_yes"]),
                "submitter_first_name": row["submitter_first_name"],
            }
            for day, row in state["published"].items()
        },
        "today_has_report": state["today_has_report"],
        "today_is_latest_report": state["today_is_latest_report"],
        "xero_settings": {
            "complete": state["has_complete_xero_settings"],
            "missing": list(state["missing_settings_fields"]),
        },
        "permissions": {
            # A superuser looking at a company they do not belong to sees it, and changes nothing.
            "read_only": is_superuser_readonly(person, entity_id),
            "correct_deposit": has_permission(person, Permission.REPORT_EDIT_ENTITY, entity_id),
        },
    }


@petty_cash_api_bp.get("/home")
def home():
    return respond(home_payload(company()["id"], user()))


def _valid_correction(body) -> tuple[dict | None, str | None]:
    """The correction the body asks for, or the sentence saying what is wrong with it."""
    if not isinstance(body, dict):
        return None, "Send the correction as JSON."
    kind = body.get("kind")
    if kind not in ("change", "no"):
        return None, "Choose whether the deposit changed or there was no deposit."
    day = body.get("date")
    if not isinstance(day, str) or not _ISO_DATE.match(day):
        return None, "The report date is missing. Reload the page and try again."
    try:
        date.fromisoformat(day)
    except ValueError:
        return None, "The report date is missing. Reload the page and try again."
    amount = body.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
        return None, "Enter the amount deposited, 0 or more."
    if kind == "no" and amount != 0:
        return None, "No deposit means an amount of 0."
    return {"kind": kind, "date": day, "amount": float(amount)}, None


@petty_cash_api_bp.post("/deposit-correction")
def deposit_correction():
    from blueprints.report.routes import legacy
    from services.permission_policy import Permission, has_permission

    entity_id = company()["id"]
    if not has_permission(user(), Permission.REPORT_EDIT_ENTITY, entity_id):
        return refuse(NOT_ALLOWED, 403)
    correction, problem = _valid_correction(request.get_json(silent=True))
    if problem:
        return refuse(problem, 422)

    payload, status = legacy.correct_previous_deposit(entity_id, correction)
    if status >= 400:
        return refuse(payload.get("message") or "That deposit didn't save. Try again.", status)
    # The Jinja page's next stop is a Flask URL; this app opens the next day's report itself.
    payload.pop("redirect_url", None)
    payload["next_transaction_date"] = (date.fromisoformat(correction["date"]) + timedelta(days=1)).isoformat()
    if "id" in payload:
        payload["id"] = str(payload["id"])
    return respond(payload, status)
