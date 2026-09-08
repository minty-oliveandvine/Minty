"""The background worker: one upload in, N drafts out.

WHY THREADS AND NOT A QUEUE

The obvious answer is Celery or RQ with Redis and a worker process. We are not
doing that, because Minty has no Redis, no worker process, and no deployment
slot for one. Adding that infrastructure for this feature would be a bigger
change than the feature.

So: process in a daemon thread, keep ALL state in the database, and let the
browser poll. The database is the source of truth and the thread never is. If
every thread on the box died right now, the data would still be consistent and
``sweeper.recover_stuck_uploads`` would pick the rows back up.

There is precedent — ``sync_chart_of_accounts_if_changed_background`` in
``blueprints/entity/services/settings.py`` does fire-and-forget work in a
daemon thread. Read it if this pattern is new to you.

THREE THINGS THAT WILL BITE YOU, ALL OF THEM HANDLED BELOW

  1. ``current_app`` is a PROXY. Passing it into a thread hands over a proxy
     bound to a request that has already ended. ``_get_current_object()`` gives
     the real application.
  2. Everything inside the thread must run in ``with app.app_context():``.
     Without it, the first ``db.session`` call raises "working outside of
     application context".
  3. The thread must not share the request's session, and must return its own.
     ``db.session.remove()`` in a ``finally`` block. A leaked session exhausts
     the pool, and the symptom — requests hanging rather than erroring — is
     horrible to diagnose.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from flask import current_app
from loguru import logger

from blueprints.capture.models.capture_ai_audit import (PASS_EXTRACT,
                                                        PASS_SPLIT, STATUS_OK,
                                                        CaptureAiAudit)
from blueprints.capture.models.capture_draft import (DEST_HOLD, DEST_REJECTED,
                                                     DOC_TYPE_OTHER,
                                                     STATUS_HOLD,
                                                     STATUS_NEEDS_CLARIFICATION,
                                                     STATUS_READY, CaptureDraft)
from blueprints.capture.models.capture_upload import (
    REJECT_INTERNAL_ERROR, REJECT_NOT_A_FINANCIAL_DOCUMENT,
    REJECT_NO_DOCUMENT_FOUND, REJECT_TOO_MANY_DOCUMENTS, STATUS_DONE,
    STATUS_FAILED, STATUS_PROCESSING, STATUS_REJECTED_NOT_SUPPORTED,
    STATUS_REJECTED_TOO_MANY, CaptureUpload)
from blueprints.capture.services import capture_ai, pdf_tools, routing, storage
from models.db import db

# How many uploads may be in Pass 1 / Pass 2 at once, across this process.
#
# Built once at import and NOT re-read per call, unlike every other setting: a
# semaphore's size is fixed at construction, and quietly swapping it while
# threads hold permits would be worse than needing a restart to change it.
_SEMAPHORE = threading.BoundedSemaphore(capture_ai.max_concurrent())


def _now():
    return datetime.now(timezone.utc)


def start(upload_id: str) -> None:
    """Hand one upload to a background thread. Returns immediately."""
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run,
        args=(app, upload_id),
        name=f"capture-{upload_id[:8]}",
        daemon=True,
    )
    thread.start()


def _run(app, upload_id: str) -> None:
    with app.app_context():
        try:
            with _SEMAPHORE:
                process(upload_id)
        except Exception as exc:
            logger.exception("capture pipeline: unhandled error on {}: {}", upload_id, exc)
            _fail(upload_id, REJECT_INTERNAL_ERROR)
        finally:
            # Return this thread's session to the pool. Skipping this is the
            # bug that presents as "the app hangs after about an hour".
            db.session.remove()


def process(upload_id: str) -> None:
    """The whole job for one upload. Runs inside an app context.

    Separated from ``_run`` so tests can call it directly, without threads.
    """
    upload = CaptureUpload.query.get(upload_id)
    if upload is None:
        logger.warning("capture pipeline: upload {} vanished before processing", upload_id)
        return

    upload.status = STATUS_PROCESSING
    upload.processing_started_at = _now()
    upload.updated_at = _now()
    db.session.commit()

    data = storage.get_bytes(upload.s3_key)
    if not data:
        logger.error("capture pipeline: could not read {} from S3", upload.s3_key)
        _finish(upload, STATUS_FAILED, REJECT_INTERNAL_ERROR)
        return

    prepared, prepared_mime = capture_ai.prepare_document(data, upload.mime_type)

    # ---------------------------------------------------------------- pass 1
    split = capture_ai.split_and_classify(
        prepared, prepared_mime, upload.page_count or 1
    )
    _write_audit(upload, split.audit, PASS_SPLIT, split.reason, draft_id=None)

    if not split.documents:
        # A provider failure and "there is no document in here" are different
        # things and must not look the same to the user: one is worth retrying,
        # the other never will be.
        if split.reason in (
            capture_ai.REASON_NO_DOCUMENT_FOUND,
            capture_ai.REASON_INVALID_REPLY,
        ):
            _finish(upload, STATUS_REJECTED_NOT_SUPPORTED, REJECT_NO_DOCUMENT_FOUND)
        else:
            _finish(upload, STATUS_FAILED, split.reason or REJECT_INTERNAL_ERROR)
        return

    documents = split.documents

    if len(documents) > capture_ai.max_documents():
        # Deliberately NOT "process the first ten". Finding more documents than
        # the limit usually means the split went wrong, and ten wrong drafts
        # are worse than one clear message.
        logger.info(
            "capture pipeline: upload {} found {} documents, limit is {}",
            upload.id, len(documents), capture_ai.max_documents(),
        )
        _finish(upload, STATUS_REJECTED_TOO_MANY, REJECT_TOO_MANY_DOCUMENTS)
        return

    real = [d for d in documents if d["doc_type"] != DOC_TYPE_OTHER]

    if not real and not upload.bypass_classification:
        # THIS IS THE CHECK THAT SAVES THE MONEY. A bank statement costs one
        # call to identify, not one call per page plus one per document.
        logger.info(
            "capture pipeline: upload {} is not a financial document ({})",
            upload.id, (documents[0].get("other_reason") or "")[:80],
        )
        _finish(
            upload, STATUS_REJECTED_NOT_SUPPORTED, REJECT_NOT_A_FINANCIAL_DOCUMENT
        )
        return

    if upload.bypass_classification and not real:
        # The user pressed "This IS a receipt, process it anyway". Take them at
        # their word and read every document as a receipt.
        from blueprints.capture.models.capture_draft import DOC_TYPE_RECEIPT

        real = documents
        for document in real:
            document["doc_type"] = DOC_TYPE_RECEIPT

    # ---------------------------------------------------------------- pass 2
    petty_cash_on, bill_on = routing.entity_modules(upload.entity_id)
    single = len(real) == 1

    created = 0
    for index, document in enumerate(real, start=1):
        try:
            created += _build_draft(
                upload, document, index, data, single, petty_cash_on, bill_on
            )
        except Exception as exc:
            # One bad document does not lose the other four. The user keeps
            # what worked and can re-upload the page that did not.
            logger.exception(
                "capture pipeline: document {} of upload {} failed: {}",
                index, upload.id, exc,
            )
            db.session.rollback()

    if created == 0:
        _finish(upload, STATUS_FAILED, REJECT_INTERNAL_ERROR)
        return

    upload.document_count = created
    _finish(upload, STATUS_DONE, None)


def _build_draft(
    upload, document, sequence, original_bytes, single, petty_cash_on, bill_on
) -> int:
    """Cut out one document, read it, and commit ONE draft. Returns 0 or 1.

    Committed per draft, not once at the end. If document 4 of 5 fails the user
    keeps drafts 1-3, and the bubble's count climbs while they watch — which is
    the difference between "it is working" and "it is stuck".
    """
    page_bytes = original_bytes
    page_mime = upload.mime_type
    page_key = None

    # Only PDFs can be cut. Several documents on one image page are told apart
    # by the locator instead, which is exactly what it is for.
    if upload.mime_type == capture_ai.MIME_PDF and not single:
        try:
            page_bytes = pdf_tools.extract_pages(
                original_bytes, document["page_start"], document["page_end"]
            )
            page_key = storage.document_key(
                upload.entity_id, upload.id, sequence, page_mime
            )
            storage.put_bytes(page_key, page_bytes, page_mime)
        except pdf_tools.PdfUnreadable as exc:
            # Fall back to the whole file rather than losing the draft. The
            # user sees more pages than they need, which is a nuisance; losing
            # the receipt is not.
            logger.warning(
                "capture pipeline: could not cut pages {}-{} of {}: {}",
                document["page_start"], document["page_end"], upload.id, exc,
            )
            page_bytes, page_key = original_bytes, None

    is_invoice = document["doc_type"] == "invoice"
    context = capture_ai.build_entity_context(upload.entity_id, for_invoice=is_invoice)

    suggestions = None
    reason = capture_ai.REASON_NO_CONTEXT
    audit = {}
    if context is not None:
        prepared, prepared_mime = capture_ai.prepare_document(page_bytes, page_mime)
        result = capture_ai.extract(
            prepared,
            prepared_mime,
            context,
            document["doc_type"],
            document.get("locator", "") if not single else "",
        )
        suggestions, reason, audit = result.suggestions, result.reason, result.audit
    else:
        # No chart of accounts and no contacts yet. The draft is still worth
        # creating — the user can fill it in and it beats losing the upload.
        logger.info(
            "capture pipeline: no context for entity {}, draft {} left empty",
            upload.entity_id, sequence,
        )

    destination = routing.decide_destination(
        document["doc_type"], petty_cash_on, bill_on
    )
    if destination == DEST_REJECTED:
        # A stray 'other' inside an otherwise good upload — a covering letter
        # stapled to a receipt. Drop it silently rather than showing the user a
        # draft they can do nothing with.
        return 0

    draft = CaptureDraft(
        upload_id=upload.id,
        entity_id=upload.entity_id,
        sequence=sequence,
        page_start=document["page_start"],
        page_end=document["page_end"],
        locator=document.get("locator") or None,
        doc_type=document["doc_type"],
        doc_type_confidence=document.get("doc_type_confidence"),
        destination=destination,
        status=_draft_status(destination, suggestions),
        suggested=suggestions,
        page_s3_key=page_key,
    )
    _lift_columns(draft, suggestions)
    db.session.add(draft)
    db.session.flush()

    _write_audit(upload, audit, PASS_EXTRACT, reason, draft_id=draft.id)
    db.session.commit()
    return 1


def _draft_status(destination, suggestions) -> str:
    """ready, needs_clarification, or hold.

    A draft needs clarification when the two fields nobody can post without —
    the amount and the date — did not come back usable. Tune this from real
    pilot data rather than agonising over it now.
    """
    if destination == DEST_HOLD:
        return STATUS_HOLD
    if not suggestions:
        return STATUS_NEEDS_CLARIFICATION

    amount = suggestions.get("amount") or {}
    date = suggestions.get("document_date") or {}
    if not amount.get("applied") or not date.get("applied"):
        return STATUS_NEEDS_CLARIFICATION
    return STATUS_READY


def _lift_columns(draft, suggestions) -> None:
    """Copy the four sortable values out of the JSON into real columns.

    The queue sorts and filters on these on every page load, and unpacking JSON
    per row to do it would be a needless cost on the one query users wait for.
    """
    if not suggestions:
        return
    from decimal import Decimal, InvalidOperation

    amount = (suggestions.get("amount") or {}).get("value")
    if amount:
        try:
            draft.amount = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            draft.amount = None

    currency = suggestions.get("currency")
    draft.currency = currency or None

    supplier = suggestions.get("supplier") or {}
    # The matched contact name, or the name read off the document when nothing
    # matched — either is more use in a queue column than a blank.
    draft.supplier_name = (
        supplier.get("value") or supplier.get("detected_name") or None
    )

    raw_date = (suggestions.get("document_date") or {}).get("value")
    if raw_date:
        try:
            draft.document_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            draft.document_date = None


def _write_audit(upload, audit, pass_number, reason, draft_id=None) -> None:
    """One row per model call. NUMBERS ONLY — never a value off the document.

    Best-effort: a metrics row is not worth failing an upload over.
    """
    if not audit:
        return
    try:
        db.session.add(
            CaptureAiAudit(
                upload_id=upload.id,
                draft_id=draft_id,
                entity_id=upload.entity_id,
                pass_number=pass_number,
                model_id=audit.get("model_id"),
                location=audit.get("location"),
                latency_ms=audit.get("latency_ms"),
                input_tokens=audit.get("input_tokens"),
                output_tokens=audit.get("output_tokens"),
                thought_tokens=audit.get("thought_tokens"),
                cached_tokens=audit.get("cached_tokens"),
                estimated_cost=audit.get("estimated_cost"),
                status=STATUS_OK if not reason else "no_suggestion",
                reason=reason,
                confidence_by_field=audit.get("confidence_by_field"),
            )
        )
    except Exception as exc:
        logger.warning("capture pipeline: could not write audit row: {}", exc)


def _finish(upload, status, reason) -> None:
    upload.status = status
    upload.reject_reason = reason
    upload.completed_at = _now()
    upload.updated_at = _now()
    db.session.commit()
    logger.info(
        "capture pipeline: upload {} finished status={} reason={} documents={}",
        upload.id, status, reason, upload.document_count,
    )


def _fail(upload_id, reason) -> None:
    """Last-resort status write from the outermost handler.

    Its own try/except because it runs after something already went wrong, and
    the session may be in a state where the write fails too.
    """
    try:
        db.session.rollback()
        upload = CaptureUpload.query.get(upload_id)
        if upload and upload.status == STATUS_PROCESSING:
            _finish(upload, STATUS_FAILED, reason)
    except Exception as exc:
        logger.error("capture pipeline: could not even record failure: {}", exc)
