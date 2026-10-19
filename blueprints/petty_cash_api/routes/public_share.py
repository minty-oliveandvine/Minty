"""``GET /api/petty-cash/v1/public/share/<initials>/<date>/<secret>``: the read-only Daily Report a
share link shows, for the petty-cash web apps' public ``/share/<path>`` page - the JSON twin of
Flask's ``/Minty_Report/<path>/`` (``report/services/ending.py`` with ``is_shared_link``).

UNAUTHENTICATED, so it lives on ``petty_cash_public_bp``, not behind the bearer guard, and answers
only what the shared page shows: the company's name, the day, the status pill, the KPIs, sales by
method, the expense lines (item, supplier, amount, receipt names - the shared page shows no
description and no receipt's View), the cash with the difference and its reason, the closing
balance, who submitted it and when, and when the link expires. No ids, no permissions, no options
and no file access.

``share.resolve_share`` decides, as for Flask's page. Every refusal reads the same to a visitor -
404 with one sentence - except an expired link, 410 (its row is deleted). The secret is in the
address, so the answer is ``no-store`` and ``no-referrer``, and the secret is never logged (the
access log blanks ``share_path``: ``pettycash/core/http_hardening.py``).

No rate limit: Flask ships no limiter (``report/services/expense_ai.py`` §8.6). The secret is 24
random bytes, so guessing is not the risk a limit would answer.
"""
from __future__ import annotations

from datetime import timezone

from loguru import logger
from werkzeug.exceptions import HTTPException

from blueprints.petty_cash_api import petty_cash_public_bp
from blueprints.petty_cash_api.api import FAILED, refuse, respond
from blueprints.shared import bearer_api, preview_origin

GONE = "This link doesn't work. Ask the person who shared it for a new link."
EXPIRED = "This link has expired. Ask the person who shared it for a new link."


@petty_cash_public_bp.get("/share/<path:share_path>")
def shared_report(share_path):
    from blueprints.report.services.share import ShareRefused, resolve_share

    try:
        link, entity, report = resolve_share(share_path)
    except ShareRefused as refused:
        if refused.reason == "expired":
            return refuse(EXPIRED, 410)
        if refused.reason == "misconfigured":
            return refuse(FAILED, 500)
        return refuse(GONE, 404)
    return respond(shared_payload(link, entity, report))


def shared_payload(link, entity, report) -> dict:
    from blueprints.petty_cash_api.routes.opening import _currency_code
    from blueprints.petty_cash_api.routes.expenses import _receipt_name
    from blueprints.petty_cash_api.routes.report import _iso, _money, _word, report_figures
    from blueprints.report.services.daily_closing import report_status
    from blueprints.report.services.expenses import lines
    from blueprints.report.services.report_page import report_facts

    entity_id = str(entity.id)
    facts = report_facts(report.id)
    label, tone = report_status(report.status, report.publishing_status, report.xero_integrated)
    figures = report_figures(report, entity_id)
    expense_lines = lines(report.id)
    expires_at = link.expires_at if link.expires_at.tzinfo else link.expires_at.astimezone()
    return {
        "company_name": entity.name,
        "transaction_date": report.transaction_date.isoformat(),
        "currency_code": _currency_code(entity_id),
        "status": _word(report.status),
        "status_label": label,
        "status_tone": tone,
        "publishing_status": _word(report.publishing_status),
        "submitted_at": _iso(facts["submitted_at"]),
        "submitted_by": facts["submitted_by"],
        "kpis": figures["kpis"],
        # sale_id is the company's own row: the page needs the name, kind and amount alone
        "sales": {**figures["sales"], "methods": [
            {"name": m["name"], "value_name": m["value_name"], "type": m["type"], "amount": m["amount"]}
            for m in figures["sales"]["methods"]]},
        "expenses": {
            "lines": [{"item": line.item or "", "supplier_name": line.contact_name if line.contact is not None else None,
                       "amount": _money(line.amount),
                       "receipts": [{"name": _receipt_name(a)} for a in line.attachments]}
                      for line in expense_lines],
            "total": _money(sum(line.amount or 0 for line in expense_lines)),
        },
        "cash": figures["cash"],
        "closing_balance": figures["closing_balance"],
        "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
    }


@petty_cash_public_bp.after_request
def _stamp(resp):
    origin = preview_origin.cors_origin((bearer_api.petty_cash_web_origin(),), ("pettycash",))
    bearer_api.cors(resp, origin, methods="GET, OPTIONS")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@petty_cash_public_bp.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    return refuse(exc.description or exc.name, exc.code or 500)


@petty_cash_public_bp.errorhandler(Exception)
def _failure(exc: Exception):
    """Logged with its type and the frames' source lines only: the address holds the secret, and
    both a database error's message (its bound parameters) and loguru's ``diagnose`` (the frames'
    variables) would print it. Answered generically."""
    import traceback

    from models.db import db

    db.session.rollback()
    frames = "".join(traceback.format_tb(exc.__traceback__))
    logger.error(f"Petty Cash public share failure: {type(exc).__name__}\n{frames}")
    return refuse(FAILED, 500)
