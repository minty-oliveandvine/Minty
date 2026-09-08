"""The JSON endpoints behind the bubble and the queue page.

  GET  /capture/status                   the bubble's poll — must stay cheap
  GET  /capture/drafts                   the queue's list
  GET  /capture/reports                  open petty cash reports for the picker
  POST /capture/draft/<id>/confirm       make it a real record
  POST /capture/draft/<id>/reject        archive it
  POST /capture/draft/<id>/retry         re-send one that failed to send
  POST /capture/upload/<id>/retry        "this IS a receipt, process it anyway"

TWO RULES THAT APPLY TO EVERY ONE OF THEM

  The entity is resolved SERVER-SIDE and a client-supplied value is never
  trusted. Every row read or written is re-checked against that entity.

  A draft belonging to another company returns 404, not 403. A 403 confirms the
  row exists, which is information an outsider should not be able to collect.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import jsonify, request
from flask_login import current_user, login_required
from loguru import logger

from blueprints.capture import capture_bp
from blueprints.capture.models.capture_draft import (DEST_PETTY_CASH,
                                                     DRAFT_ATTENTION_STATUSES,
                                                     STATUS_ARCHIVED,
                                                     STATUS_CONFIRMING,
                                                     STATUS_NEEDS_CLARIFICATION,
                                                     STATUS_POSTED,
                                                     STATUS_READY,
                                                     STATUS_SEND_FAILED,
                                                     CaptureDraft)
from blueprints.capture.models.capture_upload import (
    STATUS_PROCESSING, STATUS_QUEUED, STATUS_REJECTED_NOT_SUPPORTED,
    CaptureUpload)
from blueprints.capture.routes.module_guard import resolve_entity_id
from blueprints.capture.services import capture_ai, routing
from models.db import db
from services.permission_policy import Permission, has_permission


def _error(message, status=400, code=None):
    payload = {"status": "error", "message": message}
    if code:
        payload["reason"] = code
    return jsonify(payload), status


def _authorised_entity():
    """(entity_id, error_response). Exactly one is set."""
    entity_id = resolve_entity_id()
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        return None, _error("You don't have permission to do that here.", 403)
    return entity_id, None


def _own_draft(draft_id, entity_id):
    """One draft, or None if it is not this company's.

    The caller turns None into a 404. Never a 403 — do not confirm that another
    company's rows exist.
    """
    return CaptureDraft.query.filter(
        CaptureDraft.id == draft_id,
        CaptureDraft.entity_id == entity_id,
    ).first()


# --------------------------------------------------------------------------
# GET /capture/status — polled every two seconds by every open bubble.
#
# This runs more often than anything else in the feature, so it is TWO INDEXED
# QUERIES AND NOTHING ELSE. No S3, no model, no cross-schema joins. If you are
# about to add work here, add it to /capture/drafts instead.
# --------------------------------------------------------------------------
@capture_bp.route("/capture/status", methods=["GET"])
@login_required
def capture_status():
    entity_id, error = _authorised_entity()
    if error:
        return error

    upload_counts = dict(
        db.session.query(CaptureUpload.status, db.func.count(CaptureUpload.id))
        .filter(CaptureUpload.entity_id == entity_id)
        .group_by(CaptureUpload.status)
        .all()
    )
    draft_counts = dict(
        db.session.query(CaptureDraft.status, db.func.count(CaptureDraft.id))
        .filter(CaptureDraft.entity_id == entity_id)
        .group_by(CaptureDraft.status)
        .all()
    )

    processing = upload_counts.get(STATUS_QUEUED, 0) + upload_counts.get(
        STATUS_PROCESSING, 0
    )
    ready = draft_counts.get(STATUS_READY, 0)
    needs = draft_counts.get(STATUS_NEEDS_CLARIFICATION, 0)
    failed = draft_counts.get(STATUS_SEND_FAILED, 0)

    return jsonify(
        {
            "processing": processing,
            "ready": ready,
            "needs_clarification": needs,
            "send_failed": failed,
            # What the badge shows: everything actually waiting on a person.
            "attention": ready + needs + failed,
            "recent": _recent_uploads(entity_id),
        }
    )


def _recent_uploads(entity_id, limit=3):
    """The last few uploads, for the bubble's short list.

    Three, deliberately. The bubble is a launcher, not the queue — a scrolling
    list in the corner would be a worse version of the page that already exists.
    """
    rows = (
        CaptureUpload.query.filter(CaptureUpload.entity_id == entity_id)
        .order_by(CaptureUpload.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "upload_id": row.id,
            "filename": row.original_filename or "upload",
            "status": row.status,
            "document_count": row.document_count,
            "reject_reason": row.reject_reason,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------
# GET /capture/drafts — the queue's list.
# --------------------------------------------------------------------------
@capture_bp.route("/capture/drafts", methods=["GET"])
@login_required
def capture_drafts():
    entity_id, error = _authorised_entity()
    if error:
        return error

    query = CaptureDraft.query.filter(CaptureDraft.entity_id == entity_id)

    status = (request.args.get("status") or "").strip()
    if status == "attention":
        query = query.filter(CaptureDraft.status.in_(DRAFT_ATTENTION_STATUSES))
    elif status:
        query = query.filter(CaptureDraft.status == status)
    else:
        # The default view hides what the user has already dealt with. Posted
        # and archived rows are still reachable by asking for them.
        query = query.filter(
            CaptureDraft.status.notin_([STATUS_POSTED, STATUS_ARCHIVED])
        )

    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except (TypeError, ValueError):
        limit = 50

    drafts = query.order_by(CaptureDraft.created_at.desc()).limit(limit).all()

    # One query for the parents rather than one per row.
    upload_ids = {d.upload_id for d in drafts}
    uploads = {
        u.id: u
        for u in CaptureUpload.query.filter(CaptureUpload.id.in_(upload_ids)).all()
    } if upload_ids else {}

    return jsonify({"drafts": [_draft_json(d, uploads.get(d.upload_id)) for d in drafts]})


def _draft_json(draft, upload):
    return {
        "id": draft.id,
        "upload_id": draft.upload_id,
        "sequence": draft.sequence,
        "of": (upload.document_count if upload else None) or 1,
        "original_filename": (upload.original_filename if upload else None) or "upload",
        "page_start": draft.page_start,
        "page_end": draft.page_end,
        "locator": draft.locator,
        "doc_type": draft.doc_type,
        "destination": draft.destination,
        "status": draft.status,
        # An endpoint, never an S3 key. The key never reaches the browser.
        "file_url": f"/capture/draft/{draft.id}/file",
        "suggested": draft.suggested,
        "amount": str(draft.amount) if draft.amount is not None else None,
        "currency": draft.currency,
        "supplier_name": draft.supplier_name,
        "document_date": draft.document_date.isoformat() if draft.document_date else None,
        "last_error": draft.last_error,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


# --------------------------------------------------------------------------
# GET /capture/reports — open petty cash reports, for the card's picker.
#
# This exists because ``ShopExpense.report_id`` is NOT NULL: a petty cash
# expense cannot exist without a report, so the user has to choose one before
# Confirm can do anything.
# --------------------------------------------------------------------------
@capture_bp.route("/capture/reports", methods=["GET"])
@login_required
def capture_reports():
    entity_id, error = _authorised_entity()
    if error:
        return error

    from blueprints.report.models.report import Report

    rows = (
        Report.query.filter(
            Report.company == entity_id,
            Report.status == "draft",
        )
        .order_by(Report.transaction_date.desc())
        .limit(20)
        .all()
    )
    return jsonify(
        {
            "reports": [
                {
                    "id": row.id,
                    "transaction_date": (
                        row.transaction_date.isoformat()
                        if row.transaction_date else None
                    ),
                    "label": (
                        row.transaction_date.strftime("%d %b %Y")
                        if row.transaction_date else row.id[:8]
                    ),
                }
                for row in rows
            ]
        }
    )


# --------------------------------------------------------------------------
# POST /capture/draft/<id>/confirm
# --------------------------------------------------------------------------
@capture_bp.route("/capture/draft/<string:draft_id>/confirm", methods=["POST"])
@login_required
def capture_confirm(draft_id):
    entity_id, error = _authorised_entity()
    if error:
        return error

    draft = _own_draft(draft_id, entity_id)
    if draft is None:
        return _error("We couldn't find that one.", 404)
    if draft.status == STATUS_POSTED:
        return _error("This one has already been added.", 409)
    if draft.status == STATUS_ARCHIVED:
        return _error("This one was archived.", 409)

    body = request.get_json(silent=True) or {}

    # The destination is OURS, not the client's. Accepting one from the request
    # would let a caller send a receipt to Payment Submission by editing a form
    # field, which is exactly what putting the routing rule in Python prevents.
    destination = draft.destination
    petty_cash_on, bill_on = routing.entity_modules(entity_id)
    if destination == DEST_PETTY_CASH and not petty_cash_on:
        return _error("Petty Cash isn't switched on for this company.", 400)
    if destination == "payment" and not bill_on:
        return _error("Payment Submission isn't switched on for this company.", 400)
    if destination in ("hold", "rejected"):
        return _error("There's nowhere to send this one yet.", 400)

    values, problem = _validated_values(body, draft, entity_id)
    if problem:
        return _error(problem, 400)

    draft.confirmed = values
    draft.confirmed_at = datetime.now(timezone.utc)
    draft.confirmed_by = str(getattr(current_user, "id", "") or "")
    draft.status = STATUS_CONFIRMING
    draft.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    status = routing.push(draft.id)
    return jsonify(
        {
            "status": status,
            "draft_id": draft.id,
            "target_ref": draft.target_ref,
            "message": _confirm_message(status, draft),
        }
    )


def _confirm_message(status, draft):
    if status == STATUS_POSTED:
        return (
            "Added to petty cash."
            if draft.destination == DEST_PETTY_CASH
            else "Sent to Payment Submission."
        )
    if status == STATUS_SEND_FAILED:
        return draft.last_error or "We couldn't send that one. We'll try again."
    return "Working on it."


def _validated_values(body, draft, entity_id):
    """What the USER submitted, re-checked server-side. (values, problem).

    ``draft.suggested`` is deliberately not consulted. The user may have
    changed every field, and they are the authority — but that also means none
    of it can be trusted just because a suggestion once passed validation.
    """
    from decimal import Decimal, InvalidOperation

    values = {
        "destination": draft.destination,
        "description": (body.get("description") or "").strip()[:300],
        "currency": (body.get("currency") or "").strip().upper()[:3] or None,
        "document_date": (body.get("document_date") or "").strip()[:10] or None,
        "invoice_number": (body.get("invoice_number") or "").strip()[:60] or None,
        "due_date": (body.get("due_date") or "").strip()[:10] or None,
    }

    raw_amount = body.get("amount")
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None, "That amount doesn't look like a number."
    if amount <= 0:
        return None, "An amount greater than zero is needed."
    values["amount"] = format(amount, "f")

    raw_tax = body.get("tax_amount")
    if raw_tax not in (None, ""):
        try:
            values["tax_amount"] = format(
                Decimal(str(raw_tax)).quantize(Decimal("0.01")), "f"
            )
        except (InvalidOperation, TypeError, ValueError):
            return None, "That tax amount doesn't look like a number."

    # Ids are re-checked against the entity's OWN lists, exactly as the model's
    # reply is. A confirmed draft is a write, so this matters more here, not
    # less.
    context = capture_ai.build_entity_context(
        entity_id, for_invoice=(draft.doc_type == "invoice")
    )
    accounts = {a["id"]: a for a in (context or {}).get("accounts", [])}
    contacts = {c["id"]: c for c in (context or {}).get("contacts", [])}

    account_id = (body.get("account_id") or "").strip()
    if account_id:
        if account_id not in accounts:
            return None, "That account code isn't one of this company's."
        values["account_id"] = account_id
        values["account_code"] = accounts[account_id]["code"]

    contact_id = (body.get("contact_id") or "").strip()
    if contact_id:
        if contact_id not in contacts:
            return None, "That supplier isn't one of this company's."
        values["contact_id"] = contact_id
        values["contact_name"] = contacts[contact_id]["name"]
    else:
        # A free-text name with no contact behind it is allowed — it is what
        # the model read off the document, and the user can create the contact
        # later. It is stored as text and never becomes a contact by itself.
        values["contact_name"] = (body.get("contact_name") or "").strip()[:150] or None

    if draft.destination == DEST_PETTY_CASH:
        report_id = (body.get("report_id") or "").strip()
        if not report_id:
            return None, "Choose which petty cash report this belongs to."
        # Ownership is re-checked in routing._post_to_petty_cash against the
        # entity AND the draft status, so a stale id from an old page cannot
        # write into another company's report.
        values["report_id"] = report_id

    return values, None


# --------------------------------------------------------------------------
# POST /capture/draft/<id>/reject — archive.
# --------------------------------------------------------------------------
@capture_bp.route("/capture/draft/<string:draft_id>/reject", methods=["POST"])
@login_required
def capture_reject(draft_id):
    entity_id, error = _authorised_entity()
    if error:
        return error

    draft = _own_draft(draft_id, entity_id)
    if draft is None:
        return _error("We couldn't find that one.", 404)
    if draft.status == STATUS_POSTED:
        return _error("This one has already been added, so it can't be archived.", 409)

    draft.status = STATUS_ARCHIVED
    draft.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    # The row and its file stay until retention removes them, so "I archived
    # that by mistake" is recoverable by support.
    return jsonify({"status": STATUS_ARCHIVED, "draft_id": draft.id})


# --------------------------------------------------------------------------
# POST /capture/draft/<id>/retry — re-send one that failed to send.
# --------------------------------------------------------------------------
@capture_bp.route("/capture/draft/<string:draft_id>/retry", methods=["POST"])
@login_required
def capture_retry_send(draft_id):
    entity_id, error = _authorised_entity()
    if error:
        return error

    draft = _own_draft(draft_id, entity_id)
    if draft is None:
        return _error("We couldn't find that one.", 404)
    if draft.status != STATUS_SEND_FAILED:
        return _error("There's nothing to retry on this one.", 400)

    # A hand retry clears the attempt count. The sweeper's five-attempt limit
    # is there to stop an unattended loop, not to stop a person who has just
    # fixed whatever was wrong.
    draft.send_attempts = 0
    draft.status = STATUS_CONFIRMING
    draft.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    status = routing.push(draft.id)
    return jsonify(
        {"status": status, "draft_id": draft.id, "message": _confirm_message(status, draft)}
    )


# --------------------------------------------------------------------------
# POST /capture/upload/<id>/retry — "this IS a receipt, process it anyway".
#
# The escape hatch for a legitimate crumpled receipt the model refused. Without
# it the user is simply stuck, because re-uploading the same bytes hits the
# duplicate check.
# --------------------------------------------------------------------------
@capture_bp.route("/capture/upload/<string:upload_id>/retry", methods=["POST"])
@login_required
def capture_retry_upload(upload_id):
    entity_id, error = _authorised_entity()
    if error:
        return error

    upload = CaptureUpload.query.filter(
        CaptureUpload.id == upload_id,
        CaptureUpload.entity_id == entity_id,
    ).first()
    if upload is None:
        return _error("We couldn't find that upload.", 404)

    if upload.status != STATUS_REJECTED_NOT_SUPPORTED:
        return _error("There's nothing to retry on that one.", 400)

    if upload.bypass_classification:
        # Allowed ONCE. Otherwise a determined user can spend money in a loop
        # on a photo of their lunch.
        return _error("We already tried reading this one twice.", 400)

    # A real model call, so it counts against the limit like any other upload.
    if not capture_ai.check_rate_limit(getattr(current_user, "id", ""), entity_id):
        return _error(
            "That's a lot of uploads at once. Give it a minute and try again.",
            429,
            capture_ai.REASON_RATE_LIMITED,
        )

    upload.bypass_classification = True
    upload.status = STATUS_QUEUED
    upload.reject_reason = None
    upload.processing_started_at = None
    upload.completed_at = None
    upload.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    from blueprints.capture.services import pipeline

    pipeline.start(upload.id)
    logger.info("capture: upload {} re-queued by override", upload.id)
    return jsonify({"status": STATUS_QUEUED, "upload_id": upload.id}), 202
