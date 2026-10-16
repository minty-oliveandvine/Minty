"""Report history for minty-petty-cash-web, through the list the Jinja history page uses
(``report/services/history_query.py``).

``GET /reports?status=&start_date=&end_date=&page=&per_page=``: one page of the company's reports,
newest day first, each with its Status pill, its figures, who submitted it, a failed publish's
reasons and what this person may do to it. The Jinja page quietly falls back on a bad filter;
this refuses it (422), so the app never shows a list it did not ask for.
"""
from __future__ import annotations

from datetime import date

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user
from blueprints.petty_cash_api.routes.opening import _currency_code

PER_PAGE = (10, 25, 50, 100)


def _money(value) -> float:
    return float(value or 0)


def _word(value):
    return None if value is None else str(getattr(value, "value", value))


def _iso(moment):
    return moment.isoformat() if moment is not None else None


def _filters(args):
    """The query's filters, or (None, the sentence that refuses them)."""
    from blueprints.report.services.history_query import STATUS_FILTERS

    status = args.get("status") or None
    if status is not None and status not in STATUS_FILTERS:
        return None, "That status filter isn't one I know. Choose Draft, Submitted, Published or Failed."
    try:
        page = int(args.get("page") or 1)
        per_page = int(args.get("per_page") or 10)
    except ValueError:
        return None, "The page or the page size isn't a whole number. Choose a page from the list."
    if page < 1:
        return None, "Pages start at 1. Choose a page from the list."
    if per_page not in PER_PAGE:
        return None, "Show 10, 25, 50 or 100 reports a page."
    start, end = args.get("start_date") or "", args.get("end_date") or ""
    if bool(start) != bool(end):
        return None, "Choose both dates to see the reports between them."
    try:
        days = [date.fromisoformat(d) for d in (start, end) if d]
    except ValueError:
        return None, "A date isn't in the YYYY-MM-DD form. Choose it from the calendar."
    if days and days[0] > days[1]:
        return None, "The start date is after the end date. Choose a start on or before the end."
    return {"status": status, "page": page, "per_page": per_page, "start_date": start, "end_date": end}, None


@petty_cash_api_bp.get("/reports")
def report_history():
    from flask import request

    from blueprints.report.services.daily_closing import report_status
    from blueprints.report.services.history_query import get_entity_report_history
    from models.db import Report, db
    from services.permission_policy import Permission, can_delete_report, has_permission

    filters, problem = _filters(request.args)
    if problem:
        return refuse(problem, 422)
    entity_id = company()["id"]
    data = get_entity_report_history(entity_id, **filters)
    person = user()
    may_edit = has_permission(person, Permission.REPORT_EDIT_OWN, entity_id)
    latest_id = str(data["latest_report_id"]) if data["latest_report_id"] else None

    reports = []
    for row in data["report_history"]:
        draft = str(getattr(row.status, "value", row.status)) == "draft"
        latest = str(row.id) == latest_id
        label, tone = report_status(row.status, row.publishing_status, row.xero_integrated_yes)
        reports.append({
            "id": str(row.id),
            "transaction_date": row.transaction_date.isoformat(),
            "status": str(getattr(row.status, "value", row.status)),
            "status_label": label,
            "status_tone": tone,
            # where a draft resumes (opening .. ending), as the dashboard's draft has it
            "current_section": row.current_section,
            "total_sales": _money(row.total_sales),
            "total_expenses": _money(row.expenses),
            "submitted_by": row.first_name or None,
            "created_at": _iso(row.date),  # when the day was started - a draft's only time
            "submitted_at": _iso(row.submitted_at),
            "published_at": _iso(row.published_at),
            # it has been to Xero, even if edited since: the delete warns (as GET /reports/<id>)
            "was_published": bool(row.xero_integrated_yes) or _word(row.publishing_status) not in (None, "unpublished"),
            "publish_reasons": [{"text": r["text"], "resolved": bool(r["resolved"])} for r in row.publish_reasons],
            "permissions": {
                "edit": latest and not draft and may_edit,
                "delete": latest and not draft and can_delete_report(person, db.session.get(Report, row.id)),
            },
        })
    return respond({
        "reports": reports,
        "page": filters["page"],
        "per_page": filters["per_page"],
        "total_pages": data["total_pages"],
        "total_count": data["total_count"],
        "latest_report_id": latest_id,
        "currency_code": _currency_code(entity_id),
        "can_publish": has_permission(person, Permission.REPORT_PUBLISH, entity_id),
    })
