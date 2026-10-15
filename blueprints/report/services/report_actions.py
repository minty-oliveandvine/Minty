"""What can be done to a report after it is submitted - reopening it as a draft and deleting it -
shared by the Jinja routes (``POST /report/<id>/convert-to-draft``, ``POST /report/delete/<id>``)
and the Petty Cash API (``POST /reports/<id>/reopen``, ``DELETE /reports/<id>``).

Extracted 2026-10-15 under ``tests/test_report_actions_state.py``. Flask's rules are kept: only the
latest report (by day, any status) may be reopened or deleted; reopening needs ``REPORT_EDIT_OWN``
and keeps the report's figures and its Xero markers (so a republish can warn); deleting needs
``can_delete_report`` and takes the report's lines, receipts, sales, counts and Xero publish record
with it; both refresh the company's cash in stock.

Changed, deliberately:
- a draft can't be "reopened" (it wiped the draft's progress);
- nothing is reopened or deleted while Xero is publishing the report (the worker then marked a
  draft as published, or found no report);
- a deleted report's receipts leave storage only AFTER the rows are gone - they went first, so a
  failed delete lost the files of a report that stayed;
- a refusal is an exception the caller answers as it likes (the Jinja delete answered every
  refusal with a redirect that its fetch took for success).
The owner's rule (2026-10-15): a report already in Xero CAN be deleted; the pages warn that Xero
keeps its entries, a new publish of that day adds a second copy, and Edit report is the better way.
"""
from __future__ import annotations

from loguru import logger

PUBLISHING = "publishing"
NEWER_REOPEN = "You can only edit the most recent report. Delete or edit the newer reports first."
NEWER_DELETE = "I can only delete the most recent report, and there's a newer one after this."


class ReportActionRefused(Exception):
    """A reopen or delete the rules refuse: the sentence and the HTTP status to answer with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def _word(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def was_published(report) -> bool:
    """Whether the report has ever gone to Xero (fully or not): its Xero entries may exist."""
    return bool(report.xero_integrated) or _word(report.publishing_status) not in (None, "unpublished")


def _newer_exists(report) -> bool:
    from models.db import Report

    return (
        Report.query.filter(Report.company == report.company, Report.transaction_date > report.transaction_date)
        .first()
        is not None
    )


def reopen_report(report, user):
    """Turn the latest submitted (or published) report back into a draft at Opening, figures kept.
    Commits; returns the report."""
    from blueprints.report.services.cash_denominations import refresh_cash_stock
    from models.db import db
    from services.permission_policy import Permission, has_permission

    if not has_permission(user, Permission.REPORT_EDIT_OWN, report.company):
        raise ReportActionRefused("You do not have permission to edit this report.", 403)
    if _word(report.status) == "draft":
        raise ReportActionRefused("This report is already a draft. Carry on with the Daily Closing.", 409)
    if _word(report.publishing_status) == PUBLISHING:
        raise ReportActionRefused("Xero is still publishing this report. Wait until it finishes, then edit it.", 409)
    if _newer_exists(report):
        raise ReportActionRefused(NEWER_REOPEN, 400)

    published, publishing_status = report.xero_integrated, report.publishing_status
    try:
        report.status = "draft"
        report.current_section = "opening"
        report.completed_sections = []
        # Kept: the record that this report is (or was) in Xero, so a republish can warn.
        report.xero_integrated = published
        report.publishing_status = publishing_status
        db.session.flush()
        refresh_cash_stock(report.company)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    logger.info(f"Report {report.id} reopened as a draft (was_published={bool(published)})")
    return report


def delete_report(report, user):
    """Delete the latest report with its lines, receipts, sales, counts and Xero publish record, then
    remove its receipt files. Commits. Returns the company id."""
    from blueprints.report.models.shop_expense import ReportExpenseAttachment
    from blueprints.report.services.cash_denominations import refresh_cash_stock
    from blueprints.report.services.s3_storage import delete_files_from_s3
    from models.db import (Report, ReportSaleDetail, ShopExpense, XeroBankTransaction, XeroBankTransfer,
                           XeroReportSync, db)
    from services.permission_policy import can_delete_report

    if not can_delete_report(user, report):
        raise ReportActionRefused("You are not authorized to delete this report.", 403)
    if _word(report.publishing_status) == PUBLISHING:
        raise ReportActionRefused(
            "Xero is still publishing this report. Wait until it finishes before deleting it.", 409
        )
    if _newer_exists(report):
        raise ReportActionRefused(NEWER_DELETE, 400)

    entity_id, report_id = report.company, report.id
    files = []
    try:
        previous = (
            Report.query.filter(Report.company == entity_id, Report.transaction_date < report.transaction_date)
            .order_by(Report.transaction_date.desc())
            .first()
        )
        if previous is not None:
            previous.next_transaction_date = None
        for line in ShopExpense.query.filter_by(report_id=report_id).all():
            attachments = list(line.attachments)
            db.session.delete(line)
            db.session.flush()
            for attachment in attachments:
                if db.session.query(ReportExpenseAttachment.id).filter_by(attachment_id=attachment.id).first() is None:
                    if attachment.file_path:
                        files.append(attachment.file_path)
                    db.session.delete(attachment)
        ReportSaleDetail.query.filter_by(report_id=report_id).delete()
        XeroReportSync.query.filter_by(report_id=report_id).delete()
        XeroBankTransfer.query.filter_by(sync_report_id=report_id).delete()
        XeroBankTransaction.query.filter_by(sync_report_id=report_id).delete()
        db.session.delete(report)
        db.session.flush()
        refresh_cash_stock(entity_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    # Only now: a failed delete above leaves the report AND its files.
    delete_files_from_s3(files)
    logger.info(f"Report {report_id} deleted with {len(files)} receipt file(s)")
    return entity_id
