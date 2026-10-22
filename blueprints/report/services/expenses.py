"""The report wizard's Expenses step: the suppliers and accounts a line may use, adding and deleting
a line with its receipts, the report's totals, and the step's own save - shared by the Jinja page's
routes (``report/routes/expense.py``, ``report/routes/api.py``) and the Petty Cash API
(``petty_cash_api/routes/expenses.py``, minty-petty-cash-web's port), so the two cannot disagree.

Extracted 2026-10-14 under ``tests/test_report_expenses_state.py`` (characterisation, green before
and after). Flask's rules, quirks included: a line's item is the chosen account's name, it needs at
least one receipt, and every change recomputes ``expense_total`` and the closing balance
(``opening + cash_addition + cash sales - expenses - deposit``; the step formula, which leaves the
discrepancy out). Fixed on the way out, deliberately: a line on a report that is no longer a draft
can no longer be deleted, and the step's save commits its own progress (it relied on a later
request hook's commit).

Editing a draft's line (``update_expense``, 2026-10-19, pinned first by the update tests in
``tests/test_report_expenses_state.py``) moved here from ``report/routes/api.py`` so the Petty Cash
API's ``PATCH /expense-lines/<id>`` shares it. Fixed on the way: a replaced receipt's file now
leaves the bucket after the commit (it was left behind, its ``attachment`` row orphaned).
"""
from __future__ import annotations

from services.app_runtime.log import logger


class ExpenseRefused(Exception):
    """A change the rules refuse, with the sentence to show."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


NOT_A_DRAFT = "This report isn't a draft anymore, so I can't change its expenses."
MAX_RECEIPT_BYTES = 10 * 1024 * 1024


def checked_receipt(upload):
    """One uploaded receipt checked as the Expenses step takes it: ``(upload, None)`` - its
    Content-Type set to what the bytes are (PDF, JPEG or PNG) - or ``(None, the refusal)``."""
    import os

    from blueprints.report.services.expense_ai import sniff_mime

    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size == 0:
        return None, "That file is empty. Attach the receipt again."
    if size > MAX_RECEIPT_BYTES:
        return None, "Attach a file of 10 MB or less."
    mime = sniff_mime(upload.stream.read(16))
    upload.stream.seek(0)
    if mime is None:
        return None, "Attach a PDF, JPEG or PNG file."
    # Stored as what the bytes are, not what the browser claimed (FileStorage parses this header
    # lazily, and nothing has read it yet).
    upload.headers["Content-Type"] = mime
    return upload, None


def suppliers(entity_id):
    """The company's synced Xero contacts (``xero_contact_sync``), A to Z - the only suppliers a
    line can be saved with (an id with no synced row is stored as no supplier)."""
    from models.db import XeroContactSync, db

    return (
        XeroContactSync.query.filter_by(entity_id=entity_id)
        .order_by(db.func.lower(XeroContactSync.name))
        .all()
    )


def expense_accounts(entity_id):
    """The company's accounts switched on for Petty Cash (``entity_account_xero.is_active``)."""
    from models.db import AccountInfo, EntityAccountXero, db

    return (
        db.session.query(AccountInfo)
        .join(EntityAccountXero, EntityAccountXero.account_id == AccountInfo.id)
        .filter(AccountInfo.entity_id == entity_id, EntityAccountXero.is_active.is_(True))
        .all()
    )


def lines(report_id):
    from models.db import ShopExpense

    return ShopExpense.query.filter_by(report_id=report_id).order_by(ShopExpense.created_at).all()


def recompute_totals(report) -> float:
    """``expense_total`` = the sum of the lines, then the closing balance. Flushes; returns the total."""
    from blueprints.report.services.shared import get_cash_sales_from_detail
    from models.db import db

    db.session.flush()
    total = sum(line.amount or 0 for line in lines(report.id))
    report.expenses = total
    report.closing_balance = (
        (report.opening_balance or 0)
        + (report.cash_addition or 0)
        + get_cash_sales_from_detail(report.id, fallback_value=report.cash_sales or 0.0)
        - total
        - (report.bank_deposit or 0)
    )
    return total


def add_expense(report, user, *, item, amount, remarks, contact_id, contact_name, account_id, account_code, files):
    """Store one line on ``report`` with its receipts (``files``: uploaded file objects, at least
    one), recompute the totals, commit and log it. ``contact_id`` / ``account_id`` are Xero ids,
    resolved to the company's synced rows by the model. Returns the line."""
    from blueprints.report.services.history import log_history
    from blueprints.report.services.s3_storage import upload_file_to_s3
    from models.db import ShopExpense, db

    if report.status != "draft":
        raise ExpenseRefused(NOT_A_DRAFT)
    if not files:
        raise ExpenseRefused("Expense must have at least one valid file attached.")

    description = item or remarks or "EXPENSE"
    keys = [
        upload_file_to_s3(
            f,
            str(report.id),
            transaction_date=report.transaction_date,
            description=description,
            amount=amount,
            file_index=i if len(files) > 1 else None,
        )
        for i, f in enumerate(files)
    ]
    line = ShopExpense(
        report_id=report.id,
        item=item,
        amount=amount,
        remarks=remarks,
        contact_id=contact_id,
        contact_name=contact_name,
        account_id=account_id,
        account_code=account_code,
    )
    for uploaded, key in zip(files, keys):
        line.add_receipt(key, original_name=uploaded.filename, mime_type=uploaded.mimetype, uploaded_by=user.id)
    db.session.add(line)
    recompute_totals(report)
    db.session.commit()
    log_history(
        report_id=report.id,
        company=report.company,
        user_id=user.id,
        action="added",
        field_changed="expense",
        old_value="previous_expenses",
        new_value=f"Added expense: {item} (${amount})",
    )
    return line


def _orphaned_files(old_attachments, keep_keys=()) -> list[str]:
    """After a line's links changed: delete the ``attachment`` rows of ``old_attachments`` that no
    link uses any more and return their keys - the files to remove AFTER the commit (a failed
    change keeps the old receipt and its file). Flushes."""
    from blueprints.report.models.shop_expense import ReportExpenseAttachment
    from models.db import db

    db.session.flush()
    gone = []
    for attachment in old_attachments:
        if attachment.file_path in keep_keys:
            continue
        if db.session.query(ReportExpenseAttachment.id).filter_by(attachment_id=attachment.id).first() is None:
            if attachment.file_path:
                gone.append(attachment.file_path)
            db.session.delete(attachment)
    return gone


def replace_receipts(line, report, uploads, user, *, description, amount) -> list[str]:
    """Store ``uploads`` (checked file objects) and make them the line's receipts. Returns the
    replaced files' keys, for the caller to remove after its commit. Shared by the draft edit here
    and the submitted-report edit (``report_edits.edit_expense_line``)."""
    from blueprints.report.services.s3_storage import upload_file_to_s3

    old = list(line.attachments)
    keys = [
        upload_file_to_s3(upload, str(report.id), transaction_date=report.transaction_date,
                          description=description, amount=amount,
                          file_index=i if len(uploads) > 1 else None)
        for i, upload in enumerate(uploads)
    ]
    line.set_receipts([(k, u.filename, u.mimetype) for k, u in zip(keys, uploads)], uploaded_by=user.id)
    return _orphaned_files(old, keep_keys=keys)


KEEP_A_RECEIPT = "Every expense needs its receipt. Attach a new receipt before removing the last one."


def update_expense(report, line, user, *, item, amount, remarks, contact_id, contact_name, account_id,
                   account_code, files=(), remove_receipt_ids=()):
    """Change a line of a DRAFT in place: every field is given (the caller resolves what it keeps);
    ``files`` (uploaded file objects), when there are any, replace the line's receipts;
    ``remove_receipt_ids`` (attachment ids) drop those receipts - a line always keeps at least one.
    Recompute the totals, commit and log it; replaced or removed files leave the bucket after the
    commit. Returns the line. Shared by the Jinja page (``/report/expense/update/<id>``) and the
    Petty Cash API (``PATCH /expense-lines/<id>``)."""
    from blueprints.report.services.history import log_history
    from blueprints.report.services.s3_storage import delete_files_from_s3
    from models.db import db

    # Re-read the report and the line under a row lock (report first, then line - the order the
    # submit and other writers take them), so a submit landing mid-request is seen here and two
    # edits can't each recompute the totals from a stale sum. Django's service does the same with
    # select_for_update (security review, 2026-10-19). `of=` locks only the row itself: the models
    # eager-join their users, and Postgres refuses FOR UPDATE on the nullable side of an outer join.
    for row in (report, line):
        model = type(row)
        (db.session.query(model).filter(model.id == row.id)
         .with_for_update(of=model).populate_existing().one())
    if report.status != "draft":
        raise ExpenseRefused(NOT_A_DRAFT)
    remove = {str(i) for i in remove_receipt_ids or ()}
    kept = [a for a in line.attachments if str(a.id) not in remove]
    if not files and not kept:
        raise ExpenseRefused(KEEP_A_RECEIPT)

    gone = []
    try:
        if files:
            gone = replace_receipts(line, report, list(files), user,
                                    description=item or remarks or "EXPENSE", amount=amount)
        elif remove:
            old = list(line.attachments)
            line.set_receipts([(a.file_path, None, None) for a in kept], uploaded_by=user.id)
            gone = _orphaned_files([a for a in old if str(a.id) in remove])
        line.item = item
        line.amount = amount
        line.remarks = remarks
        line.contact_id = contact_id
        line.contact_name = contact_name
        line.account_id = account_id
        line.account_code = account_code
        recompute_totals(report)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    delete_files_from_s3(gone)
    if gone:
        logger.info(f"Expense {line.id}: {len(gone)} replaced receipt file(s) removed")
    log_history(
        report_id=report.id,
        company=report.company,
        user_id=user.id,
        action="updated",
        field_changed="expense",
        old_value=f"expense_{line.id}",
        new_value=f"updated to amount: ${amount}",
    )
    return line


def delete_expense(report, line, user) -> float:
    """Delete ``line`` and its receipts from a DRAFT report, recompute, commit and log it. Returns
    the new total."""
    from blueprints.report.services.history import log_history
    from blueprints.report.services.s3_storage import delete_expense_with_receipts
    from models.db import db

    if report.status != "draft":
        raise ExpenseRefused(NOT_A_DRAFT)
    line_id = line.id
    delete_expense_with_receipts(line)
    total = recompute_totals(report)
    db.session.commit()
    logger.info(f"Expense {line_id} deleted from report {report.id}; total now {total}")
    log_history(
        report_id=report.id,
        company=report.company,
        user_id=user.id,
        action="deleted",
        field_changed="expense",
        old_value=f"expense_{line_id}",
        new_value="deleted",
    )
    return total


def save_expenses_step(report, action_type: str):
    """The step's Save & Next / Save & Exit: the wizard's progress, committed."""
    from blueprints.report.services.shared import update_draft_progress
    from models.db import db

    update_draft_progress(report, action_type, "expenses", "deposit")
    db.session.commit()
    return report
