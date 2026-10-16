"""The report wizard's Expenses step for minty-petty-cash-web - ``blueprints/report/services/
expenses.py``, the same functions the Jinja page's routes use.

- ``GET /reports/expenses?transaction_date=``: the day's draft, its lines and total, and the
  suppliers and accounts a line may use. No draft is a 409 that sends the app to Opening (the
  Jinja page redirects there).
- ``POST /reports/expenses/lines`` (multipart): ``transaction_date``, ``amount``, ``remarks``,
  ``supplier_id``, ``account_id`` and one ``receipt`` file. Checked HERE - the Jinja page leaves
  every check to the browser: an amount above 0, a supplier and an account from the lists this
  route hands out, a description of at most 300 characters, a PDF / JPEG / PNG of at most 10 MB
  (by its bytes, not its name).
- ``DELETE /expense-lines/<id>``: a line of a draft of this company.
- ``GET /expense-lines/<id>/receipts/<attachment id>``: the receipt's bytes - by the attachment's
  id, never by its storage key.
- ``PUT /reports/expenses`` ``{transaction_date, action}``: the step's Save & Next / Save & Exit.

``REPORT_EDIT_OWN`` throughout, as the page asks; deleting asks what the Jinja route asks.
"""
from __future__ import annotations

import os

from flask import make_response, request

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.petty_cash_api.api import company, refuse, respond, user
from blueprints.petty_cash_api.routes.opening import (MAX_AMOUNT, NOT_ALLOWED, _currency_code,
                                                      _day, _may_edit, draft_payload)

#: Flask's page says "for today" whatever the day; the sentence its save uses fits every day.
NO_DRAFT = "I don't see a draft yet - let's start with the opening entry."
BAD_DATE = "That date doesn't look quite right! Please check the format and try again."
NOT_FOUND = "Hmm, I couldn't find that expense."
#: What a receipt may be, as the Jinja page's picker says: "PDF, JPEG, PNG (Max 10MB)".
MAX_RECEIPT_BYTES = 10 * 1024 * 1024
MAX_REMARKS = 300


def _receipt_name(attachment) -> str:
    return attachment.original_name or os.path.basename(attachment.file_path or "") or "Receipt"


def line_payload(line) -> dict:
    return {
        "id": str(line.id),
        "item": line.item or "",
        "amount": float(line.amount or 0),
        "remarks": line.remarks or "",
        "supplier": {"id": line.contact_id, "name": line.contact_name} if line.contact is not None else None,
        "account": (
            {"id": line.account_id, "code": line.account_code or "", "name": line.account.name}
            if line.account is not None
            else None
        ),
        "receipts": [
            {"id": str(a.id), "name": _receipt_name(a), "mime_type": a.mime_type}
            for a in line.attachments
        ],
    }


def _draft(entity_id, day):
    from blueprints.report.services.opening import find_draft

    return find_draft(entity_id, day)


@petty_cash_api_bp.get("/reports/expenses")
def expenses_page():
    from blueprints.report.services.expenses import expense_accounts, lines, suppliers
    from services.permission_policy import Permission, has_permission

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    day = _day(request.args.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    draft = _draft(entity_id, day)
    if draft is None:
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)
    rows = lines(draft.id)
    return respond(
        {
            "transaction_date": day.isoformat(),
            "currency_code": _currency_code(entity_id),
            "draft": draft_payload(draft),
            "lines": [line_payload(line) for line in rows],
            "total": float(sum(line.amount or 0 for line in rows)),
            "suppliers": [{"id": c.xero_contact_id, "name": c.name} for c in suppliers(entity_id)],
            "accounts": [
                {"id": a.xero_account_id, "code": a.xero_code or "", "name": a.name}
                for a in expense_accounts(entity_id)
            ],
            "permissions": {"create_supplier": has_permission(user(), Permission.CONTACT_CREATE, entity_id)},
        }
    )


def _amount(raw) -> float | None:
    text = str(raw or "").replace(",", "").strip()
    try:
        value = round(float(text), 2)
    except ValueError:
        return None
    return value if 0 < value <= MAX_AMOUNT else None


def _receipt():
    """The uploaded receipt (checked by ``expenses.checked_receipt``), or a refusal sentence."""
    from blueprints.report.services.expenses import checked_receipt

    files = [f for f in request.files.getlist("receipt") if f and (f.filename or "").strip()]
    if not files:
        return None, "Attach the receipt to add this expense."
    if len(files) > 1:
        return None, "Attach one receipt per expense."
    return checked_receipt(files[0])


@petty_cash_api_bp.post("/reports/expenses/lines")
def add_expense_line():
    from blueprints.report.services.expenses import (ExpenseRefused, add_expense,
                                                     expense_accounts, suppliers)

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    form = request.form
    day = _day(form.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    amount = _amount(form.get("amount"))
    if amount is None:
        return refuse(f"Enter the amount as a number above 0 and up to {MAX_AMOUNT:,.2f}.", 422)
    remarks = (form.get("remarks") or "").strip()
    if len(remarks) > MAX_REMARKS:
        return refuse(f"Keep the description to {MAX_REMARKS} characters or fewer.", 422)
    supplier = next((c for c in suppliers(entity_id) if c.xero_contact_id == form.get("supplier_id")), None)
    if supplier is None:
        return refuse("Choose a supplier from the list.", 422)
    account = next((a for a in expense_accounts(entity_id) if a.xero_account_id == form.get("account_id")), None)
    if account is None:
        return refuse("Choose an account code from the list.", 422)
    receipt, problem = _receipt()
    if problem:
        return refuse(problem, 422)

    draft = _draft(entity_id, day)
    if draft is None:
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)
    try:
        line = add_expense(
            draft,
            user(),
            item=account.name,
            amount=amount,
            remarks=remarks,
            contact_id=supplier.xero_contact_id,
            contact_name=supplier.name,
            account_id=account.xero_account_id,
            account_code=account.xero_code,
            files=[receipt],
        )
    except ExpenseRefused as refused:
        return refuse(refused.message, 409)
    return respond({"line": line_payload(line), "total": float(draft.expenses or 0)}, 201)


def _company_line(entity_id, line_id):
    """The line and its report, when the line is on a report of this company; else ``(None, None)``."""
    import uuid

    from models.db import Report, ShopExpense, db

    try:
        uuid.UUID(str(line_id))
    except ValueError:
        return None, None
    line = db.session.get(ShopExpense, str(line_id))
    report = db.session.get(Report, line.report_id) if line is not None else None
    if report is None or str(report.company) != str(entity_id):
        return None, None
    return line, report


@petty_cash_api_bp.delete("/expense-lines/<line_id>")
def delete_expense_line(line_id):
    from blueprints.report.services.expenses import ExpenseRefused, delete_expense
    from services.permission_policy import can_delete_report

    entity_id = company()["id"]
    line, report = _company_line(entity_id, line_id)
    if line is None:
        return refuse(NOT_FOUND, 404)
    if not can_delete_report(user(), report):
        return refuse("It looks like you don't have permission to delete this expense.", 403)
    try:
        total = delete_expense(report, line, user())
    except ExpenseRefused as refused:
        return refuse(refused.message, 409)
    return respond({"total": float(total)})


@petty_cash_api_bp.get("/expense-lines/<line_id>/receipts/<attachment_id>")
def expense_receipt(line_id, attachment_id):
    from blueprints.report.services.s3_storage import get_s3_bucket, get_s3_client
    from services.permission_policy import can_view_report

    entity_id = company()["id"]
    line, report = _company_line(entity_id, line_id)
    if line is None or not can_view_report(user(), report):
        return refuse("I couldn't find that file.", 404)
    attachment = next((a for a in line.attachments if str(a.id) == str(attachment_id)), None)
    if attachment is None or not attachment.file_path:
        return refuse("I couldn't find that file.", 404)
    obj = get_s3_client().get_object(Bucket=get_s3_bucket(), Key=attachment.file_path)
    body = obj["Body"].read(MAX_RECEIPT_BYTES + 1)
    if len(body) > MAX_RECEIPT_BYTES:
        return refuse("That file is too big to show here.", 413)
    from blueprints.report.services.expense_ai import sniff_mime

    resp = make_response(body)
    resp.headers["Content-Type"] = sniff_mime(body[:16]) or attachment.mime_type or "application/octet-stream"
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@petty_cash_api_bp.put("/reports/expenses")
def save_expenses_step_route():
    from blueprints.report.services.expenses import save_expenses_step

    entity_id = company()["id"]
    if not _may_edit(entity_id):
        return refuse(NOT_ALLOWED, 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return refuse("Send the step as JSON.", 422)
    day = _day(body.get("transaction_date"))
    if day is None:
        return refuse(BAD_DATE, 422)
    action = body.get("action")
    if action not in ("next", "exit"):
        return refuse("Choose Save & Next or Save & Exit.", 422)
    draft = _draft(entity_id, day)
    if draft is None:
        return respond({"error": NO_DRAFT, "to": "opening"}, 409)
    # Flask's Save & Exit records nothing (the page leaves without calling the server).
    if action == "next":
        save_expenses_step(draft, "save_next")
    return respond(
        {
            "draft_id": str(draft.id),
            "transaction_date": day.isoformat(),
            "current_section": draft.current_section,
            "completed_sections": list(draft.completed_sections or []),
            "next": "deposit" if action == "next" else "dashboard",
        }
    )


@petty_cash_api_bp.post("/suppliers")
def add_supplier():
    """``{name}`` -> a new contact in the company's Xero organisation, kept as a synced supplier
    (``blueprints/entity/services/suppliers.py``, shared with ``POST /entity/contact/create``)."""
    from blueprints.entity.services.suppliers import MAX_NAME, SupplierRefused, create_supplier
    from services.permission_policy import Permission, has_permission

    entity_id = company()["id"]
    if not has_permission(user(), Permission.CONTACT_CREATE, entity_id):
        return refuse("You do not have permission to create contacts for this entity.", 403)
    body = request.get_json(silent=True)
    name = (body.get("name") if isinstance(body, dict) else None) or ""
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return refuse("The supplier's name is still empty. Add the name to continue.", 422)
    if len(name) > MAX_NAME:
        return refuse(f"Keep the supplier's name to {MAX_NAME} characters or fewer.", 422)
    try:
        row = create_supplier(entity_id, name)
    except SupplierRefused as refused:
        return refuse(refused.message, 409 if refused.status == 400 else refused.status)
    return respond({"id": row.xero_contact_id, "name": row.name}, 201)
