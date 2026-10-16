"""A report after it is submitted, for minty-petty-cash-web - the Daily Report and what can be done
to it - through the services the Jinja pages use (``report/services/report_actions.py``,
``report_page.py``, ``share.py``).

- ``GET /reports/<id>``: the Daily Report - status, the figures, sales by method, the expense
  lines with their receipts, the cash, the audit facts and what this person may do.
- ``POST /reports/<id>/reopen``: back to a draft at Opening (the latest report only).
- ``DELETE /reports/<id>``: the latest report, with its lines, receipts and counts. A report in
  Xero may be deleted (the owner, 2026-10-15) - the app warns, using ``was_published``.
- ``POST /reports/<id>/share-link``: a read-only link to the day, valid 30 days.
- ``PUT /reports/<id>/difference-reason``, ``PUT /reports/<id>/withdrawal`` and
  ``PATCH /reports/<id>/expense-lines/<line id>``: a submitted report's details that move no
  balance (``report/services/report_edits.py``, the Jinja Daily Report's too). Any submitted
  report may be edited this way, not only the latest; each answers the Daily Report again.

Another company's or an unknown report is 404, as for the outcome.
"""
from __future__ import annotations

import uuid

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user
from blueprints.petty_cash_api.routes.opening import _currency_code

NOT_FOUND = "Hmm, I couldn't find that report."


def _money(value) -> float:
    return float(value or 0)


def _iso(moment):
    return moment.isoformat() if moment is not None else None


def _word(value):
    return None if value is None else str(getattr(value, "value", value))


def _report(report_id):
    """This company's report by id, if the person may see it - else None."""
    from models.db import Report, db
    from services.permission_policy import can_view_report

    try:
        uuid.UUID(str(report_id))
    except ValueError:
        return None
    report = db.session.get(Report, str(report_id))
    if report is None or str(report.company) != str(company()["id"]) or not can_view_report(user(), report):
        return None
    return report


@petty_cash_api_bp.get("/reports/<report_id>")
def daily_report(report_id):
    report = _report(report_id)
    if report is None:
        return refuse(NOT_FOUND, 404)
    return respond(report_payload(report))


def report_payload(report) -> dict:
    """The Daily Report as ``GET /reports/<id>`` answers it (the edits answer it too)."""
    from blueprints.petty_cash_api.routes.close import _sales_history
    from blueprints.petty_cash_api.routes.expenses import line_payload
    from blueprints.report.services.cash import expected_cash
    from blueprints.report.services.cash_denominations import cash_summary
    from blueprints.report.services.daily_closing import report_status
    from blueprints.report.services.expenses import lines
    from blueprints.report.services.report_actions import _newer_exists, was_published
    from blueprints.report.services.report_page import report_facts
    from blueprints.report.services.sales import report_methods
    from blueprints.report.services.shared import get_cash_sales_from_detail
    from blueprints.report.services.expenses import expense_accounts, suppliers
    from services.permission_policy import Permission, can_delete_report, has_permission

    entity_id = company()["id"]
    facts = report_facts(report.id)
    label, tone = report_status(report.status, report.publishing_status, report.xero_integrated)
    counted, cash_position = cash_summary(report.id)
    expense_lines = lines(report.id)
    status = _word(report.status)
    latest = not _newer_exists(report)
    history, yesterday = _sales_history(entity_id, report.transaction_date, report.total_sales)
    # the details that move no balance (report_edits.check_editable's rules)
    edit_details = (status != "draft" and _word(report.publishing_status) != "publishing"
                    and has_permission(user(), Permission.REPORT_EDIT_OWN, entity_id))
    return (
        {
            "report_id": str(report.id),
            "transaction_date": report.transaction_date.isoformat(),
            "currency_code": _currency_code(entity_id),
            "company_name": company().get("name"),
            "status": status,
            "status_label": label,
            "status_tone": tone,
            "is_latest": latest,
            "submitted_at": _iso(facts["submitted_at"]),
            "submitted_by": facts["submitted_by"],
            "published_at": _iso(facts["published_at"]),
            "publishing_status": _word(report.publishing_status),
            "xero_integrated": bool(report.xero_integrated),
            "was_published": was_published(report),
            "kpis": {
                "total_sales": _money(report.total_sales),
                "total_expenses": _money(report.expenses),
                "cash_position": _money(cash_position if cash_position is not None else report.closing_balance),
            },
            "sales": {
                "methods": [{**m, "amount": _money(m["amount"])} for m in report_methods(entity_id, report.id)],
                "cash": _money(get_cash_sales_from_detail(report.id, fallback_value=report.cash_sales or 0.0)),
                "total": _money(report.total_sales),
                "yesterday_total": yesterday,
                "history": history,
            },
            "expenses": {
                "lines": [line_payload(line) for line in expense_lines],
                "total": _money(sum(line.amount or 0 for line in expense_lines)),
            },
            "cash": {
                "opening_balance": _money(report.opening_balance),
                "cash_addition": _money(report.cash_addition),
                "cash_addition_type": _word(report.cash_addition_type),
                "cash_sales": _money(report.cash_sales),
                "expenses": _money(report.expenses),
                "bank_deposit": _money(report.bank_deposit),
                "expected": _money(expected_cash(report)),
                "counted": _money(counted),
                "safe_box": _money(report.safe_box_balance),
                "difference": {"amount": _money(report.discrepancy_amount), "kind": report.discrepancy_type or "none",
                               "reason": report.discrepancy_reason or ""},
            },
            "closing_balance": _money(report.closing_balance),
            "permissions": {
                "edit": status != "draft" and latest and has_permission(user(), Permission.REPORT_EDIT_OWN, entity_id),
                "delete": latest and can_delete_report(user(), report),
                "publish": has_permission(user(), Permission.REPORT_PUBLISH, entity_id),
                "share": status != "draft",
                "edit_details": edit_details,
            },
            # what an expense line may be changed to - only when it may be
            "options": {
                "suppliers": [{"id": c.xero_contact_id, "name": c.name} for c in suppliers(entity_id)],
                "accounts": [{"id": a.xero_account_id, "code": a.xero_code or "", "name": a.name}
                             for a in expense_accounts(entity_id)],
            } if edit_details else None,
        }
    )


@petty_cash_api_bp.post("/reports/<report_id>/reopen")
def reopen(report_id):
    from blueprints.report.services.report_actions import ReportActionRefused, reopen_report

    report = _report(report_id)
    if report is None:
        return refuse(NOT_FOUND, 404)
    try:
        reopen_report(report, user())
    except ReportActionRefused as refused:
        return refuse(refused.message, refused.status)
    return respond({"report_id": str(report.id), "transaction_date": report.transaction_date.isoformat(),
                    "status": "draft", "next": "opening"})


@petty_cash_api_bp.delete("/reports/<report_id>")
def delete(report_id):
    from blueprints.report.services.report_actions import ReportActionRefused, delete_report

    report = _report(report_id)
    if report is None:
        return refuse(NOT_FOUND, 404)
    day = report.transaction_date.isoformat()
    try:
        delete_report(report, user())
    except ReportActionRefused as refused:
        return refuse(refused.message, refused.status)
    return respond({"deleted": str(report_id), "transaction_date": day, "next": "dashboard"})


@petty_cash_api_bp.post("/reports/<report_id>/share-link")
def share_link(report_id):
    from blueprints.report.services.share import create_share_link_for_report

    report = _report(report_id)
    if report is None:
        return refuse(NOT_FOUND, 404)
    if _word(report.status) == "draft":
        return refuse("A draft can't be shared. Submit the day first.", 409)
    body, status = create_share_link_for_report(
        user().id, {"entity_id": str(report.company), "transaction_date": report.transaction_date.isoformat()}
    )
    if status != 200:
        return refuse(body.get("error") or "The link could not be made. Try again in a moment.", status)
    return respond({"url": body["url"]})


def _edit(report_id, change):
    """Run one of report_edits' changes on this company's report; answer the Daily Report."""
    from blueprints.report.services.report_edits import EditRefused

    report = _report(report_id)
    if report is None:
        return refuse(NOT_FOUND, 404)
    try:
        change(report)
    except EditRefused as refused:
        return refuse(refused.message, refused.status)
    return respond(report_payload(report))


@petty_cash_api_bp.put("/reports/<report_id>/difference-reason")
def edit_reason(report_id):
    from flask import request

    from blueprints.report.services.report_edits import edit_difference_reason

    body = request.get_json(silent=True) or {}
    return _edit(report_id, lambda report: edit_difference_reason(report, user(), body.get("reason")))


@petty_cash_api_bp.put("/reports/<report_id>/withdrawal")
def edit_report_withdrawal(report_id):
    from flask import request

    from blueprints.report.services.report_edits import edit_withdrawal

    body = request.get_json(silent=True) or {}
    return _edit(report_id, lambda report: edit_withdrawal(report, user(), body.get("withdrawal_type")))


@petty_cash_api_bp.patch("/reports/<report_id>/expense-lines/<line_id>")
def edit_report_line(report_id, line_id):
    """multipart: ``remarks``, ``supplier_id``, ``account_id`` (each only when it changes) and one
    ``receipt`` that replaces the line's."""
    from flask import request

    from blueprints.petty_cash_api.routes.expenses import _company_line
    from blueprints.report.services.report_edits import edit_expense_line

    line, line_report = _company_line(company()["id"], line_id)
    if line is None or str(line_report.id) != str(report_id):
        return refuse("Hmm, I couldn't find that expense.", 404)
    form = request.form
    receipts = [f for f in request.files.getlist("receipt") if f and (f.filename or "").strip()]
    if len(receipts) > 1:
        return refuse("Attach one receipt per expense.", 422)

    def change(report):
        edit_expense_line(line, user(), remarks=form.get("remarks") if "remarks" in form else None,
                          supplier_id=form.get("supplier_id") or None, account_id=form.get("account_id") or None,
                          receipts=receipts)

    return _edit(report_id, change)
