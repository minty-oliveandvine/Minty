"""Where a draft goes — decided in Python, never by the model.

The model's job is to say what a document IS. This module's job is to say where
that kind of document goes for this particular company. They are deliberately
different jobs in different places, for three reasons:

  1. IT IS TESTABLE. ``decide_destination`` is a pure function of three
     arguments. A routing bug is reproducible and covered by a table of cases,
     rather than probabilistic and covered by hoping.

  2. THE MODEL CANNOT GRANT ENTITLEMENT. If the model chose, then whether a
     customer's invoice reached a module they had not paid for would depend on
     a language model's judgement. That is not a position anybody wants to
     defend, to a customer or to anyone else.

  3. THE RULE CAN CHANGE CHEAPLY. When it does, we change one function and one
     test — not a prompt, and not the model's behaviour on every document it
     has already read.

Remember BILL means PAYMENT. The database constant was never renamed because
renaming it would be a risky migration with no user benefit. Every word a user
can see says "Payment".
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from loguru import logger

from blueprints.capture.models.capture_draft import (DEST_HOLD, DEST_PAYMENT,
                                                     DEST_PETTY_CASH,
                                                     DEST_REJECTED,
                                                     DOC_TYPE_INVOICE,
                                                     DOC_TYPE_RECEIPT,
                                                     MAX_SEND_ATTEMPTS)

# How long to wait on Module 2 before giving up. Never call a service in
# another process without one of these.
PAYMENT_TIMEOUT_SECONDS = 15


def decide_destination(
    doc_type: str, petty_cash_enabled: bool, bill_enabled: bool
) -> str:
    """Return one of: 'petty_cash', 'payment', 'hold', 'rejected'.

        doc_type   petty cash   payment   ->  destination
        ---------  -----------  --------  ------------------
        receipt    yes          -             petty_cash
        receipt    no           yes           hold
        invoice    -            yes           payment
        invoice    -            no            hold
        other      -            -             rejected
        anything   no           no            hold (unreachable in practice —
                                              the blueprint gate already
                                              refused the request)

    ``hold`` means "we know what this is, but you do not have the module that
    would receive it". It is not an error and not a rejection: the draft sits
    in the queue with an explanation, because the user should be able to see
    that the system understood their document. Hiding it would look like the
    upload had simply vanished.
    """
    if doc_type == DOC_TYPE_RECEIPT:
        return DEST_PETTY_CASH if petty_cash_enabled else DEST_HOLD

    if doc_type == DOC_TYPE_INVOICE:
        return DEST_PAYMENT if bill_enabled else DEST_HOLD

    # Anything else — a bank statement, a contract, a blurry photo of a desk.
    # Pass 1 should already have stopped the upload before we got here, so
    # reaching this line means a mixed upload where some documents were real.
    return DEST_REJECTED


def entity_modules(entity_id: str) -> tuple[bool, bool]:
    """(petty_cash_enabled, bill_enabled) for one entity.

    Fails CLOSED on error, matching the blueprint's gate: a transient database
    problem must not be a way to route a document into a module the entity does
    not hold. Both false sends everything to ``hold``, which is visible,
    reversible, and honest about the fact that we could not tell.
    """
    try:
        from blueprints.entity.routes.modules import _is_module_enabled

        return (
            bool(_is_module_enabled(entity_id, "PETTY_CASH")),
            bool(_is_module_enabled(entity_id, "BILL")),
        )
    except Exception as exc:
        logger.error("capture routing: module lookup failed entity={}: {}", entity_id, exc)
        return (False, False)


# ==========================================================================
# PUSHING A CONFIRMED DRAFT TO ITS DESTINATION
#
# Two destinations, two completely different operations:
#
#   Petty Cash  a row in OUR database. One transaction, done.
#   Payment     an API call to billing-backend, a separate service. Can be
#               slow, can be down, can half-succeed.
#
# The user should not have to know there are two systems behind the queue, so
# both go through ``push`` and both report the same way.
# ==========================================================================
def push(draft_id: str) -> str:
    """Send one confirmed draft to its destination. Returns the new status.

    Never raises: a failure here becomes ``send_failed``, which the retry
    sweeper picks up and the user can retry by hand. A draft is never silently
    lost, and it never reports itself as posted when the far side never saw it.
    """
    from blueprints.capture.models.capture_draft import (DEST_PAYMENT,
                                                         DEST_PETTY_CASH,
                                                         STATUS_POSTED,
                                                         STATUS_SEND_FAILED)
    from models.db import db

    from blueprints.capture.models.capture_draft import CaptureDraft

    draft = CaptureDraft.query.get(draft_id)
    if draft is None:
        return "missing"

    try:
        if draft.destination == DEST_PETTY_CASH:
            reference = _post_to_petty_cash(draft)
        elif draft.destination == DEST_PAYMENT:
            reference = _post_to_payment(draft)
        else:
            # 'hold' and 'rejected' are not destinations anything can be sent
            # to. Reaching here means the confirm endpoint let something
            # through it should not have.
            logger.error(
                "capture routing: draft {} has no sendable destination ({})",
                draft_id, draft.destination,
            )
            return _mark_failed(draft, "There is nowhere to send this one.")
    except _SendRefused as exc:
        # The far side said no and will say no again. Not retried.
        logger.warning("capture routing: draft {} refused: {}", draft_id, exc)
        draft.send_attempts = MAX_SEND_ATTEMPTS  # stop the sweeper trying
        return _mark_failed(draft, str(exc))
    except Exception as exc:
        logger.exception("capture routing: draft {} push failed: {}", draft_id, exc)
        draft.send_attempts = (draft.send_attempts or 0) + 1
        return _mark_failed(draft, str(exc)[:500])

    draft.status = STATUS_POSTED
    draft.target_ref = reference
    draft.last_error = None
    draft.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    logger.info(
        "capture routing: draft {} posted to {} as {}",
        draft_id, draft.destination, reference,
    )
    return STATUS_POSTED


class _SendRefused(Exception):
    """The destination rejected the content. Retrying will not help."""


def _mark_failed(draft, message: str) -> str:
    from blueprints.capture.models.capture_draft import STATUS_SEND_FAILED
    from models.db import db

    draft.status = STATUS_SEND_FAILED
    draft.last_error = (message or "")[:500]
    draft.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return STATUS_SEND_FAILED


# --------------------------------------------------------------------------
# Petty Cash — a local write.
# --------------------------------------------------------------------------
def _post_to_petty_cash(draft) -> str:
    """Create the ShopExpense row. Returns its id.

    THE GOTCHA THIS FUNCTION EXISTS AROUND: ``ShopExpense.report_id`` is NOT
    NULL with a foreign key to ``pettycashv2.report``. A petty cash expense
    cannot exist without a report, so the queue card carries a required "Add to
    report" dropdown and its choice arrives here in ``confirmed["report_id"]``.
    """
    import json

    from blueprints.report.models.report import Report
    from blueprints.report.models.shop_expense import ShopExpense
    from models.db import db

    values = draft.confirmed or {}
    report_id = values.get("report_id")
    if not report_id:
        raise _SendRefused("No petty cash report was chosen for this expense.")

    report = Report.query.filter(
        Report.id == report_id,
        Report.company == draft.entity_id,
        Report.status == "draft",
    ).first()
    if report is None:
        # Between the page rendering and the click, the report may have been
        # published or deleted. Refused rather than retried: the answer will
        # not change on its own, and the user needs to pick another one.
        raise _SendRefused(
            "That petty cash report is no longer open. Pick another one."
        )

    # Copy, do NOT move. The capture file is on a retention clock; a posted
    # expense is not. Sharing one object would mean the retention sweeper could
    # delete the attachment out from under a real accounting record months
    # later.
    expense_key = _copy_document_for_expense(draft, report)

    amount = values.get("amount")
    try:
        amount = float(Decimal(str(amount)))
    except (InvalidOperation, TypeError, ValueError):
        raise _SendRefused("That amount is not a number we can post.")
    if amount <= 0:
        raise _SendRefused("An expense needs an amount greater than zero.")

    description = (values.get("description") or "").strip()[:150] or "EXPENSE"

    expense = ShopExpense(
        report_id=report.id,
        item=description,
        amount=amount,
        remarks=(values.get("description") or "").strip()[:300] or None,
        # Format B, matching the multi-file upload path in
        # blueprints/report/routes/expense.py: metadata in ``files``, the full
        # object key in ``s3_key``. ``normalize_expense_files`` reads this pair.
        files=json.dumps(
            {
                "original_filename": _display_name(draft),
                "mime_type": _document_mime(draft),
            }
        ),
        s3_key=expense_key,
        contact_id=(values.get("contact_id") or None),
        contact_name=(values.get("contact_name") or None),
        account_id=(values.get("account_id") or None),
        account_code=(values.get("account_code") or None),
    )
    db.session.add(expense)
    db.session.flush()
    # NOT committed here. The caller commits the expense and the draft's own
    # status in ONE transaction — half of this succeeding is the outcome worth
    # real effort to avoid.
    return expense.id


def _copy_document_for_expense(draft, report) -> str | None:
    """Copy the draft's file to the report's own location. Returns the new key.

    Best-effort: an expense with no attachment is a nuisance, an expense that
    cannot be created is worse. On failure we fall back to the capture key,
    which works today and is cleaned up by retention later — logged loudly so
    it is visible if it becomes common.
    """
    from blueprints.capture.services import storage

    source = draft.page_s3_key or _upload_key(draft)
    if not source:
        return None

    target = f"expenses/{report.id}/{draft.id}{_extension(source)}"
    try:
        data = storage.get_bytes(source)
        if not data:
            raise RuntimeError("the capture file could not be read")
        storage.put_bytes(target, data, _document_mime(draft))
        return target
    except Exception as exc:
        logger.error(
            "capture routing: could not copy {} for expense on draft {}: {}. "
            "Falling back to the capture key, which retention WILL delete.",
            source, draft.id, exc,
        )
        return source


def _upload_key(draft):
    from blueprints.capture.models.capture_upload import CaptureUpload

    upload = CaptureUpload.query.get(draft.upload_id)
    return upload.s3_key if upload else None


def _document_mime(draft) -> str:
    from blueprints.capture.models.capture_upload import CaptureUpload

    upload = CaptureUpload.query.get(draft.upload_id)
    return (upload.mime_type if upload else None) or "application/octet-stream"


def _extension(key: str) -> str:
    import os

    return os.path.splitext(key or "")[1] or ".bin"


def _display_name(draft) -> str:
    """What the expense page shows beside the attachment.

    The original filename, with the document number when one upload produced
    several — "march-receipts (2).pdf" says more than "doc-2.pdf".
    """
    import os

    from blueprints.capture.models.capture_upload import CaptureUpload

    upload = CaptureUpload.query.get(draft.upload_id)
    name = (upload.original_filename if upload else None) or "capture"
    if (upload and (upload.document_count or 1) > 1):
        stem, ext = os.path.splitext(name)
        return f"{stem} ({draft.sequence}){ext}"
    return name


# --------------------------------------------------------------------------
# Payment Submission — a cross-service push to Module 2 (billing-backend).
# --------------------------------------------------------------------------
def billing_backend_url() -> str:
    """Base URL of Module 2's API, or "" when it is not configured.

    Unset is a supported state, not a broken one: invoices then route to
    ``hold`` and the user sees an explanation instead of a queue full of drafts
    that will never send.
    """
    import os

    return (os.environ.get("BILLING_BACKEND_URL") or "").rstrip("/")


def _post_to_payment(draft) -> str:
    """Create a PaymentRequest in Module 2. Returns its id.

    ==================== CONFIRM BEFORE RELYING ON THIS ====================
    Everything about the far side of this call is UNVERIFIED. Four questions
    are open with the Module 2 developer (see section 20 of the implementation
    guide):

      1. The exact endpoint path and JSON body for creating a PaymentRequest.
      2. Whether it accepts a presigned URL for the attachment or needs bytes.
      3. Whether it honours an Idempotency-Key header.
      4. Whether a token minted by Minty is accepted, and what expiry works.

    The auth scheme below is the one Module 2 already uses for every call it
    makes to its own backend — an HS256 JWT signed with the shared SECRET_KEY,
    plus X-Entity-Id — so that half is grounded. The path and body are not.

    Until those answers land, this is wired but not proven. It is written so
    the failure is loud and safe: a wrong path gives a 404, which is treated as
    a refusal, and the draft lands in ``send_failed`` with the message. Nothing
    is lost and nothing is double-sent.
    =======================================================================
    """
    import requests

    base = billing_backend_url()
    if not base:
        raise _SendRefused(
            "Payment Submission isn't connected yet, so there's nowhere to "
            "send this."
        )

    values = draft.confirmed or {}
    token = _mint_module2_token(draft)

    payload = {
        "supplier_name": values.get("contact_name") or draft.supplier_name,
        "supplier_contact_id": values.get("contact_id"),
        "invoice_number": values.get("invoice_number"),
        "invoice_date": values.get("document_date"),
        "due_date": values.get("due_date"),
        "amount": values.get("amount"),
        "tax_amount": values.get("tax_amount"),
        "currency": values.get("currency"),
        "account_code": values.get("account_code"),
        "account_id": values.get("account_id"),
        "description": values.get("description"),
        "source": "minty_ai_capture",
        "source_reference": draft.id,
    }

    response = requests.post(
        f"{base}/api/payment-requests/",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Entity-Id": str(draft.entity_id),
            # THIS MATTERS. The retry sweeper re-sends after a timeout, and a
            # timeout does not tell you whether the far side processed the
            # request. Without an idempotency key, one slow response creates a
            # duplicate payment request — which is a genuinely bad outcome, not
            # a cosmetic one.
            "Idempotency-Key": str(draft.id),
        },
        timeout=PAYMENT_TIMEOUT_SECONDS,
    )

    if 200 <= response.status_code < 300:
        return _payment_reference(response, draft)

    if 400 <= response.status_code < 500:
        # Will still be a 4xx in ten minutes. Not retried.
        raise _SendRefused(_payment_error(response))

    # 5xx: worth another go. Raised as an ordinary exception so ``push``
    # increments send_attempts and the sweeper picks it up.
    raise RuntimeError(
        f"Payment Submission returned {response.status_code}: "
        f"{_payment_error(response)}"
    )


def _payment_reference(response, draft) -> str:
    """Module 2's id for the created request.

    Falls back to the draft id so ``target_ref`` is never empty on a success —
    an unrecognised response shape must not turn a posted record into one that
    looks unposted.
    """
    try:
        body = response.json()
    except Exception:
        return str(draft.id)
    for key in ("id", "payment_request_id", "reference", "uuid"):
        value = body.get(key) if isinstance(body, dict) else None
        if value:
            return str(value)[:128]
    return str(draft.id)


def _payment_error(response) -> str:
    """A short, safe message out of whatever the far side sent."""
    try:
        body = response.json()
        if isinstance(body, dict):
            for key in ("detail", "message", "error"):
                if body.get(key):
                    return str(body[key])[:300]
        return str(body)[:300]
    except Exception:
        return (response.text or "")[:300] or f"HTTP {response.status_code}"


def _mint_module2_token(draft) -> str:
    """The same short-lived HS256 JWT Module 2 already accepts.

    Minted HERE rather than passed in from the confirm request, and that is the
    point: a token minted at confirm time would be long expired by the fifth
    retry half an hour later. Freshness has to come from the moment of sending.
    """
    from blueprints.entity.routes.modules import _generate_module_token
    from blueprints.entity.models.entity import Entity

    entity = Entity.query.filter(Entity.id == draft.entity_id).first()
    return _generate_module_token(
        user_id=draft.confirmed_by or "",
        entity_id=draft.entity_id,
        xero_org_id=getattr(entity, "xero_org_id", "") or "",
        billing_enabled=True,
        petty_cash_enabled=True,
    )
