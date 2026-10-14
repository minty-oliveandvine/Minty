"""Facts the Daily Report and the Close stage draw beyond the ending service's totals (Part 15.7,
15.15e): each expense line with its receipts, and the audit line (who submitted, when, Xero).

One call per page, three queries: the report, its expense lines, the submitter. Read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from blueprints.report.services.shared import normalize_expense_files
from models.db import Report, ShopExpense, User, tz


def _hk(moment):
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def report_facts(report_id) -> dict:
    report = Report.query.filter(Report.id == str(report_id)).first()
    if report is None:
        return {"expenses": [], "receipts": [], "submitted_by": None, "submitted_at": None,
                "published_at": None, "publishing_status": None, "today": datetime.now(tz).date()}
    expenses = []
    receipts = []
    for line in ShopExpense.query.filter_by(report_id=report.id).order_by(ShopExpense.created_at).all():
        files = normalize_expense_files(line.files, getattr(line, "s3_key", None))
        expenses.append({
            "id": str(line.id),
            "item": line.item,
            "contact_name": line.contact_name,
            "remarks": line.remarks,
            "amount": line.amount or 0,
            "receipts": len(files),
        })
        for f in files:
            receipts.append({"key": f["s3_key"], "name": f.get("display_name") or f["s3_key"].rsplit("/", 1)[-1],
                             "item": line.item, "amount": line.amount or 0})
    submitter = None
    if report.uploaded_by:
        user = User.query.filter_by(username=report.uploaded_by).first()
        if user:
            submitter = " ".join(p for p in ((user.first_name or "").strip(), (user.last_name or "").strip()) if p) or None
    status = getattr(report.publishing_status, "value", report.publishing_status)
    return {
        "expenses": expenses,
        "receipts": receipts,
        "submitted_by": submitter,
        "submitted_at": _hk(report.submitted_at),
        "published_at": _hk(report.published_at),
        "publishing_status": status,
        #: Hong Kong's today, for "Today's report ..." wording
        "today": datetime.now(tz).date(),
    }
