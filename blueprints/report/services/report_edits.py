"""Editing a SUBMITTED report without touching its balances - the difference reason, where an
addition to the drawer came from, and an expense line's details and receipt - shared by the Jinja
Daily Report's routes (``report/routes/api.py``) and the Petty Cash API
(``petty_cash_api/routes/report.py``), so the two cannot disagree.

Extracted 2026-10-16 under ``tests/test_report_edits_state.py`` (characterisation, green before
and after). Kept: any submitted report may be edited (not only the latest - none of this moves a
balance), an edit takes the report out of Xero (``mark_diverged_from_xero``) while
``publishing_status`` remembers it was sent. Fixed on the way out: a draft or a report Xero is
publishing is refused (409); a difference keeps its reason, and a reason over 300 characters is
refused rather than cut; a line's account and supplier must be the company's own (any id the
browser sent was stored); a new account renames the line (its item is its account's name); a
new receipt passes the Expenses step's checks, and the replaced file leaves the bucket after the
commit.
"""
from __future__ import annotations

from loguru import logger

MAX_REASON = 300
MAX_REMARKS = 300
WITHDRAWAL_TYPES = ("personal", "company")
NO_RIGHT = "It looks like you don't have permission to edit this report."
DRAFT = "This report is still a draft. Change it in the Daily Closing."
PUBLISHING = "Xero is still publishing this report. Wait until it finishes, then edit it."


class EditRefused(Exception):
    """An edit the rules refuse: the sentence to show and its HTTP status."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def _word(value):
    return None if value is None else str(getattr(value, "value", value))


def check_editable(report, user) -> None:
    from services.permission_policy import Permission, has_permission

    if not has_permission(user, Permission.REPORT_EDIT_OWN, report.company):
        raise EditRefused(NO_RIGHT, 403)
    if _word(report.status) == "draft":
        raise EditRefused(DRAFT, 409)
    if _word(report.publishing_status) == "publishing":
        raise EditRefused(PUBLISHING, 409)


def _save(report) -> None:
    from blueprints.report.services.shared import mark_diverged_from_xero
    from models.db import db

    mark_diverged_from_xero(report)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def edit_difference_reason(report, user, reason) -> str:
    check_editable(report, user)
    reason = str(reason or "").strip()
    if len(reason) > MAX_REASON:
        raise EditRefused(f"Keep the reason to {MAX_REASON} characters or fewer.", 422)
    kind = _word(report.discrepancy_type)
    if not reason and kind in ("short", "over"):
        raise EditRefused(f"The cash was {kind}, so the reason is still needed. Add the reason to save it.", 422)
    report.discrepancy_reason = reason
    _save(report)
    return reason


def edit_withdrawal(report, user, kind) -> str:
    check_editable(report, user)
    kind = str(kind or "").strip()
    if kind not in WITHDRAWAL_TYPES:
        raise EditRefused("That withdrawal type doesn't look quite right to me.", 400)
    # The bank account is not per report: a company withdrawal always comes from the main bank
    # account on entity_pettycash_settings (schema item 13).
    report.cash_addition_type = kind
    _save(report)
    return kind


def edit_expense_line(line, user, *, remarks=None, supplier_id=None, account_id=None, receipts=None):
    """Change a submitted line's details - never its amount. ``None`` leaves a field as it is;
    ``supplier_id`` / ``account_id`` are Xero ids that must be among the company's synced
    suppliers and its accounts switched on for Petty Cash; ``receipts`` are uploaded files that
    replace the line's receipts. Returns the line."""
    from blueprints.report.models.shop_expense import ReportExpenseAttachment
    from blueprints.report.services.expenses import checked_receipt, expense_accounts, suppliers
    from blueprints.report.services.s3_storage import delete_files_from_s3, upload_file_to_s3
    from models.db import Report, db

    report = db.session.get(Report, line.report_id)
    check_editable(report, user)
    entity_id = report.company

    if remarks is not None:
        remarks = str(remarks).strip()
        if len(remarks) > MAX_REMARKS:
            raise EditRefused(f"Keep the description to {MAX_REMARKS} characters or fewer.", 422)
    supplier = account = None
    if supplier_id is not None:
        supplier = next((c for c in suppliers(entity_id) if c.xero_contact_id == supplier_id), None)
        if supplier is None:
            raise EditRefused("Choose a supplier from the list.", 422)
    if account_id is not None:
        account = next((a for a in expense_accounts(entity_id) if a.xero_account_id == account_id), None)
        if account is None:
            raise EditRefused("Choose an account code from the list.", 422)
    checked = []
    for upload in receipts or []:
        upload, problem = checked_receipt(upload)
        if problem:
            raise EditRefused(problem, 422)
        checked.append(upload)

    replaced = []
    try:
        if remarks is not None:
            line.remarks = remarks
        if supplier is not None:
            line.contact_id, line.contact_name = supplier.xero_contact_id, supplier.name
        if account is not None:
            line.account_id, line.account_code, line.item = account.xero_account_id, account.xero_code, account.name
        if checked:
            old = list(line.attachments)
            keys = [
                upload_file_to_s3(upload, str(report.id), transaction_date=report.transaction_date,
                                  description=line.item or line.remarks or "EXPENSE", amount=line.amount,
                                  file_index=i if len(checked) > 1 else None)
                for i, upload in enumerate(checked)
            ]
            line.set_receipts([(k, u.filename, u.mimetype) for k, u in zip(keys, checked)], uploaded_by=user.id)
            db.session.flush()
            for attachment in old:
                if attachment.file_path in keys:
                    continue
                if db.session.query(ReportExpenseAttachment.id).filter_by(attachment_id=attachment.id).first() is None:
                    if attachment.file_path:
                        replaced.append(attachment.file_path)
                    db.session.delete(attachment)
        _save(report)
    except Exception:
        db.session.rollback()
        raise
    # Only now: a failed edit above keeps the old receipt AND its file.
    delete_files_from_s3(replaced)
    if replaced:
        logger.info(f"Expense {line.id}: {len(replaced)} replaced receipt file(s) removed")
    return line
