"""POST /capture/upload — take one file in, hand back an upload id.

The order of the checks in this file is the design. Each one is cheaper than
the one after it, so a bad file is refused as early and as cheaply as possible:
the size check costs nothing, the magic-byte check costs nothing, the page
count costs a millisecond, the duplicate check costs one indexed query, and
only after all of them does anything get stored or sent to a model.

Reordering these to "tidy them up" would mean paying to store and read files we
were always going to refuse.

TWO KINDS OF ERROR, TWO KINDS OF RESPONSE

  The user caused it   (wrong type, too many pages, too big)
                       -> 4xx with a plain-English message. They can fix it
                          and they need to know.

  The AI or we caused it  (timeout, provider down, rate limit)
                       -> the upload still succeeds where it can, and failures
                          surface later in the queue as a status. Stage 1's
                          rule — unavailable means invisible — applies to the
                          model, not to a file the user just chose.

The one thing that is NOT an error: a duplicate. That returns 200 with a
pointer to the drafts the user already has, because it is a helpful answer
rather than a failure.
"""

from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required
from loguru import logger
from werkzeug.utils import secure_filename

from blueprints.capture import capture_bp
from blueprints.capture.models.capture_upload import (STATUS_QUEUED,
                                                      UPLOAD_ACTIVE_STATUSES,
                                                      CaptureUpload)
from blueprints.capture.routes.module_guard import resolve_entity_id
from blueprints.capture.services import capture_ai, pdf_tools, storage
from models.db import db
from services.permission_policy import Permission, has_permission


def _error(message, status=400, code=None):
    payload = {"status": "error", "message": message}
    if code:
        payload["reason"] = code
    return jsonify(payload), status


@capture_bp.route("/capture/upload", methods=["POST"])
@login_required
def capture_upload():
    # The module gate and the kill switch already ran in the blueprint's
    # before_request, so by this point the feature is on and the company has a
    # module that can receive a draft.
    entity_id = resolve_entity_id()

    # The gate answers "does this company have the feature". This answers "is
    # this person allowed to use it".
    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        logger.warning(
            "capture: upload denied user={} entity={}",
            getattr(current_user, "id", None), entity_id,
        )
        return _error("You don't have permission to add expenses here.", 403)

    # Before the file is even read. A user who is over their limit should not
    # be able to make us hold 10 MB in memory to be told no.
    if not capture_ai.check_rate_limit(getattr(current_user, "id", ""), entity_id):
        logger.info("capture: rate limited entity={}", entity_id)
        return _error(
            "That's a lot of uploads at once. Give it a minute and try again.",
            429,
            capture_ai.REASON_RATE_LIMITED,
        )

    uploaded = request.files.get("file")
    if not uploaded:
        return _error("No file was received.", 400, capture_ai.REASON_UNSUPPORTED_FILE)

    # Read under THIS route's cap. The app-wide MAX_CONTENT_LENGTH is far too
    # permissive for something that becomes input tokens. Reading cap+1 bytes
    # is what lets us tell "exactly at the limit" from "over it" without
    # holding the whole oversized file.
    cap = capture_ai.max_file_bytes()
    data = uploaded.read(cap + 1)
    if not data:
        return _error("That file is empty.", 400, capture_ai.REASON_UNSUPPORTED_FILE)
    if len(data) > cap:
        return _error(
            f"That file is larger than {cap // (1024 * 1024)} MB.",
            400,
            capture_ai.REASON_FILE_TOO_LARGE,
        )

    # Content, not extension. A .pdf that is really a JPEG is fine and common —
    # we just record what it actually is.
    mime = capture_ai.sniff_mime(data)
    if mime is None:
        return _error(
            "Only PDF, JPG and PNG files can be read.",
            400,
            capture_ai.REASON_UNSUPPORTED_FILE,
        )

    # Page count. Images are one page by definition; PDFs get counted, and an
    # unreadable one is refused here rather than failing in a background thread
    # after we have already paid to store it.
    page_count = 1
    if mime == capture_ai.MIME_PDF:
        try:
            page_count = pdf_tools.page_count(data)
        except pdf_tools.PdfUnreadable:
            return _error(
                "That PDF couldn't be opened. It may be damaged or password "
                "protected.",
                400,
                capture_ai.REASON_CORRUPT_FILE,
            )
        limit = capture_ai.max_pages()
        if page_count > limit:
            return _error(
                f"That PDF has {page_count} pages. Please upload "
                f"{limit} pages or fewer.",
                400,
                capture_ai.REASON_TOO_MANY_PAGES,
            )
        if page_count < 1:
            return _error(
                "That PDF has no pages in it.", 400, capture_ai.REASON_CORRUPT_FILE
            )

    # Duplicate detection, on the BYTES. Users rename files and mail clients
    # rename attachments, but the same receipt scanned once is the same bytes
    # every time. Returning the existing upload is more useful than an error,
    # and it costs no model call at all.
    digest = capture_ai.content_hash(data)
    existing = _find_duplicate(entity_id, digest)
    if existing is not None:
        logger.info(
            "capture: duplicate upload entity={} matches upload={}",
            entity_id, existing.id,
        )
        return (
            jsonify(
                {
                    "status": "duplicate",
                    "duplicate": True,
                    "upload_id": existing.id,
                    "message": _duplicate_message(existing),
                }
            ),
            200,
        )

    upload = CaptureUpload(
        entity_id=entity_id,
        uploaded_by=str(getattr(current_user, "id", "")),
        original_filename=secure_filename(uploaded.filename or "")[:255] or None,
        mime_type=mime,
        byte_size=len(data),
        page_count=page_count,
        content_sha256=digest,
        # Filled in below — the key needs the row's id, and the id is generated
        # by the model's default rather than by the database.
        s3_key="",
        status=STATUS_QUEUED,
    )
    db.session.add(upload)
    # Flush, not commit: the column default generates the id here, and the S3
    # key needs it. Nothing is durable until the commit further down, so a
    # failed store leaves no row behind.
    db.session.flush()

    key = storage.original_key(entity_id, upload.id, mime)
    try:
        storage.put_bytes(key, data, mime)
    except Exception as exc:
        # Nothing was committed, so there is no row pointing at a key holding
        # nothing. The user gets a real error and can simply try again.
        db.session.rollback()
        logger.exception("capture: S3 store failed entity={}: {}", entity_id, exc)
        return _error(
            "We couldn't save that file just now. Please try again.", 503
        )

    upload.s3_key = key
    db.session.commit()

    logger.info(
        "capture: upload accepted id={} entity={} user={} mime={} bytes={} pages={}",
        upload.id, entity_id, getattr(current_user, "id", None),
        mime, len(data), page_count,
    )

    _start_processing(upload.id)

    return (
        jsonify(
            {
                "status": "queued",
                "upload_id": upload.id,
                "page_count": page_count,
                "original_filename": upload.original_filename,
            }
        ),
        202,
    )


def _duplicate_message(upload) -> str:
    """"You already uploaded this on 3 March."

    Built with an explicit day integer rather than a strftime directive: the
    one that drops the leading zero is ``%-d`` on Linux and ``%#d`` on Windows,
    and this app is developed on Windows and deployed on Linux.
    """
    stamp = getattr(upload, "created_at", None)
    if not stamp:
        return "You already uploaded this file."
    return f"You already uploaded this file on {stamp.day} {stamp:%B}."


def _find_duplicate(entity_id: str, digest: str):
    """The most recent non-rejected upload of these exact bytes, if any.

    Bounded by CAPTURE_DEDUPE_DAYS so re-submitting the same monthly invoice
    next quarter is treated as the new document it is, not as a duplicate of
    something from months ago.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=capture_ai.dedupe_days())
    return (
        CaptureUpload.query.filter(
            CaptureUpload.entity_id == entity_id,
            CaptureUpload.content_sha256 == digest,
            CaptureUpload.status.in_(UPLOAD_ACTIVE_STATUSES),
            CaptureUpload.created_at >= cutoff,
        )
        .order_by(CaptureUpload.created_at.desc())
        .first()
    )


def _start_processing(upload_id: str) -> None:
    """Hand the upload to the background worker.

    Imported lazily and wrapped: the pipeline is build-order step 8, and until
    it exists an upload simply sits at ``queued``. That is a working state, not
    a broken one — the file is stored, the row is committed, and the sweeper
    will not touch it because nothing has claimed it. When the pipeline lands,
    queued rows start moving with no change to this file.
    """
    try:
        from blueprints.capture.services import pipeline

        pipeline.start(upload_id)
    except ImportError:
        logger.info(
            "capture: pipeline not built yet — upload {} left queued", upload_id
        )
    except Exception as exc:
        # A worker that failed to START is not a reason to fail the upload: the
        # file is safely stored and the sweeper will pick the row up.
        logger.exception("capture: could not start pipeline for {}: {}", upload_id, exc)
