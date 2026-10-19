"""The report wizard's last step for minty-petty-cash-web - the day's summary, the submit and what
comes after it - through ``blueprints/report/services/submit.py`` (the same submit the Jinja Close
page posts to) and ``report/services/report_page.py`` (the facts the Jinja outcome page shows).

- ``GET /reports/close?transaction_date=``: the draft's figures as Submit will post them - the
  opening, sales by method, expense lines, the deposit, the expected and counted cash, the
  difference, the closing balance - and ``problem``, what would stop the submit now (or null).
- ``POST /reports/submit`` ``{transaction_date}``: posts the day. A rule's refusal is 409
  ``{error, to}`` naming the step that fixes it; nothing is written, and nothing is ever deleted.
- ``GET /reports/<report id>/outcome``: what the outcome page says once the day is submitted.

``REPORT_EDIT_OWN`` for the close and the submit (Flask asked only for viewing); viewing rights
for the outcome.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from flask import request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user
from blueprints.petty_cash_api.routes.opening import (NOT_ALLOWED, _currency_code, _day, _may_edit,
                                                      draft_payload)

NO_DRAFT = "I don't see a draft yet - let's start with the opening entry."
BAD_DATE = "That date doesn't look quite right! Please check the format and try again."
NOT_FOUND = "Hmm, I couldn't find that report."


def _money(value) -> float:
    return float(value or 0)


def _iso(moment):
    return moment.isoformat() if moment is not None else None


def _sales_history(entity_id, day, today_total) -> tuple[list, float | None]:
    """The 30 days up to ``day`` (``[{date, total}]``, the day itself with the draft's own total) and
    the day before's total sales, or None - Flask's "Compared to Yesterday" and "Sales History".
    Like Flask, a report of any status counts. One query (Flask ran 29)."""
    from models.db import Report

    first = day - timedelta(days=29)
    rows = (
        Report.query.with_entities(Report.transaction_date, Report.total_sales)
        .filter(Report.company == entity_id, Report.transaction_date >= first, Report.transaction_date < day)
        .all()
    )
    by_day = {d: float(t or 0) for d, t in rows}
    history = [{"date": (first + timedelta(days=i)).isoformat(), "total": by_day.get(first + timedelta(days=i), 0.0)}
               for i in range(29)]
    history.append({"date": day.isoformat(), "total": float(today_total or 0)})
    yesterday = by_day.get(day - timedelta(days=1))
    return history, (yesterday if yesterday else None)


def _submitted_for(entity_id, day):
    from blueprints.report.services.opening import submitted_report_for

    return submitted_report_for(entity_id, day)


@petty_cash_api_bp.get("/reports/close")
def close_page():
    from blueprints.report.services.cash import expected_cash
    from blueprints.report.services.opening import find_draft
    from blueprints.report.services.report_page import report_facts
    from blueprints.report.services.sales import page_methods
    from blueprints.report.services.shared import get_cash_sales_from_detail
    from blueprints.report.services.submit import closing_at_submit, submit_problem
    from models.db import SaleInfo

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    day = _day(request.args.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    draft = find_draft(entity_id, day)
    if draft is None:
        done = _submitted_for(entity_id, day)
        if done is not None:
            return respond({"error": "This day is already submitted.", "to": "submitted", "report_id": str(done.id)}, 409)
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)

    facts = report_facts(draft.id)
    methods = [m for m in page_methods(entity_id, draft.id) if m["value_name"] != SaleInfo.CASH_VALUE_NAME]
    lines = facts["expenses"]
    problem = submit_problem(draft)
    history, yesterday = _sales_history(entity_id, day, draft.total_sales)
    return respond(
        {
            "transaction_date": day.isoformat(),
            "currency_code": _currency_code(entity_id),
            "draft": draft_payload(draft),
            "opening_balance": _money(draft.opening_balance),
            "cash_addition": _money(draft.cash_addition),
            "sales": {
                "methods": [{**m, "amount": _money(m["amount"])} for m in methods],
                "cash": _money(get_cash_sales_from_detail(draft.id, fallback_value=draft.cash_sales or 0.0)),
                "total": _money(draft.total_sales),
                "yesterday_total": yesterday,
                "history": history,
            },
            "expenses": {
                "lines": [{"id": e["id"], "item": e["item"] or "", "supplier": e["contact_name"] or "",
                           "remarks": e["remarks"] or "", "amount": _money(e["amount"]), "receipts": e["receipts"]}
                          for e in lines],
                "total": _money(sum(e["amount"] or 0 for e in lines)),
            },
            "cash": {
                "bank_deposit": _money(draft.bank_deposit),
                "expected": _money(expected_cash(draft)),
                "counted": _money(draft.actual_cash_total),
                "safe_box": _money(draft.safe_box_balance),
                "difference": {"amount": _money(draft.discrepancy_amount), "kind": draft.discrepancy_type or "none",
                               "reason": draft.discrepancy_reason or ""},
            },
            "closing_balance": _money(closing_at_submit(draft)),
            "problem": {"error": problem.message, "to": problem.to} if problem else None,
        }
    )


@petty_cash_api_bp.post("/reports/submit")
def submit_day():
    from blueprints.report.services.opening import find_draft
    from blueprints.report.services.submit import SubmitRefused, submit_report

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    body = request.get_json(silent=True)
    day = _day(body.get("transaction_date")) if isinstance(body, dict) else None
    if day is None:
        return refuse(BAD_DATE, 422)
    draft = find_draft(entity_id, day)
    if draft is None:
        done = _submitted_for(entity_id, day)
        if done is not None:
            return respond({"error": "This day is already submitted.", "to": "submitted", "report_id": str(done.id)}, 409)
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)
    try:
        posted = submit_report(draft, user())
    except SubmitRefused as refused:
        body = {"error": refused.message, "to": refused.to}
        if refused.to == "submitted":
            body["report_id"] = str(draft.id)
        return respond(body, 409)
    return respond(
        {
            "report_id": str(posted.id),
            "transaction_date": day.isoformat(),
            "status": str(getattr(posted.status, "value", posted.status)),
            "submitted_at": _iso(posted.submitted_at),
            "closing_balance": _money(posted.closing_balance),
            "next": "submitted",
        }
    )


@petty_cash_api_bp.get("/reports/<report_id>/outcome")
def report_outcome(report_id):
    from blueprints.report.services.report_actions import was_published
    from blueprints.report.services.report_page import report_facts
    from models.db import Report, db, tz
    from services.permission_policy import Permission, can_view_report, has_permission

    entity_id = company()["id"]
    try:
        uuid.UUID(str(report_id))
    except ValueError:
        return refuse(NOT_FOUND, 404)
    report = db.session.get(Report, str(report_id))
    if report is None or str(report.company) != str(entity_id) or not can_view_report(user(), report):
        return refuse(NOT_FOUND, 404)
    facts = report_facts(report.id)
    status = str(getattr(report.status, "value", report.status))
    publishing = facts["publishing_status"]
    publishing = str(getattr(publishing, "value", publishing)) if publishing is not None else None
    kind = report.discrepancy_type or "none"

    return respond(
        {
            "report_id": str(report.id),
            "transaction_date": report.transaction_date.isoformat(),
            "currency_code": _currency_code(entity_id),
            "company_name": company().get("name"),
            "status": status,
            "submitted": status != "draft",
            "submitted_at": _iso(facts["submitted_at"]),
            "submitted_by": facts["submitted_by"],
            "cash_counted": _money((report.actual_cash_total or 0) + (report.safe_box_balance or 0)),
            "difference": {"amount": _money(report.discrepancy_amount), "kind": kind,
                           "has_reason": bool((report.discrepancy_reason or "").strip())},
            "xero": {"publishing_status": publishing, "published_at": _iso(facts["published_at"]),
                     "xero_integrated": bool(report.xero_integrated),
                     # it has been to Xero, even if changed since: a publish warns (report_actions)
                     "was_published": was_published(report)},
            "can_publish": has_permission(user(), Permission.REPORT_PUBLISH, entity_id),
            "is_today": report.transaction_date == datetime.now(tz).date(),
            "next_day": (report.transaction_date + timedelta(days=1)).isoformat(),
        }
    )
