"""GET /capture/draft/<id>/file — the document, so the user can look at it.

Streamed THROUGH Flask rather than redirected to a presigned S3 URL. A
presigned URL keeps working after the user's session ends, can be pasted into a
chat, and cannot be revoked — for a page whose whole content is other people's
financial documents, that is the wrong trade for saving a little bandwidth.

Every request re-authorises: the kill switch and the module gate in the
blueprint's before_request, then the permission check and the entity match
here. The unguessable S3 key is a second line of defence, never the first.
"""

from __future__ import annotations

from flask import Response, abort
from loguru import logger

from blueprints.capture import capture_bp
from blueprints.capture.models.capture_draft import CaptureDraft
from blueprints.capture.models.capture_upload import CaptureUpload
from blueprints.capture.routes.module_guard import current_entity_id
from blueprints.capture.services import actor, storage
from services.permission_policy import Permission, has_permission


@capture_bp.route("/capture/draft/<string:draft_id>/file", methods=["GET"])
def capture_draft_file(draft_id):
    entity_id = current_entity_id()
    if not has_permission(actor.acting_user(), Permission.REPORT_EDIT_OWN, entity_id):
        abort(403)

    draft = CaptureDraft.query.filter(
        CaptureDraft.id == draft_id,
        CaptureDraft.entity_id == entity_id,
    ).first()
    if draft is None:
        # 404, not 403 — do not confirm that another company's rows exist.
        abort(404)

    upload = CaptureUpload.query.get(draft.upload_id)

    # The single-document file when we cut one, otherwise the original. A
    # single-document upload never gets cut, so page_s3_key is null there and
    # the parent IS the document.
    key = draft.page_s3_key or (upload.s3_key if upload else None)
    if not key:
        abort(404)

    data = storage.get_bytes(key)
    if data is None:
        logger.warning("capture files: {} is missing from storage", key)
        abort(404)

    mime = (upload.mime_type if upload else None) or "application/octet-stream"
    return Response(
        data,
        mimetype=mime,
        headers={
            # inline: the point is to look at it beside the fields, not to
            # download it.
            "Content-Disposition": "inline",
            # Private, because this is one customer's financial document. Five
            # minutes is enough for a user scrolling their queue and short
            # enough that a revoked permission bites quickly.
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
