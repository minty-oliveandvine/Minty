"""One row per file a user dropped on the bubble.

An upload is not a draft. One upload produces zero, one, or many drafts — a
3-page PDF holding five receipts produces five ``capture_draft`` rows and one
row here. This table records the FILE and how far processing got with it; the
documents found inside it live next door.

The status column is the whole state machine for the ingest half of the
feature, and the background worker owns it. Nothing else writes it except the
upload endpoint (which sets ``queued``) and the stuck-job sweeper (which sets
``failed`` on a row whose worker thread died with the process).
"""

from uuid import uuid4

from models.db import db

SCHEMA = "pettycashv2"

# ---------------------------------------------------------------------------
# Status values. Kept as plain strings rather than a database enum: adding a
# state to a Postgres enum is a migration, and this list will move during the
# pilot.
# ---------------------------------------------------------------------------
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_REJECTED_NOT_SUPPORTED = "rejected_not_supported"
STATUS_REJECTED_TOO_MANY = "rejected_too_many"
STATUS_FAILED = "failed"

UPLOAD_STATUSES = (
    STATUS_QUEUED,
    STATUS_PROCESSING,
    STATUS_DONE,
    STATUS_REJECTED_NOT_SUPPORTED,
    STATUS_REJECTED_TOO_MANY,
    STATUS_FAILED,
)

# Statuses that still count as "in flight" for the bubble's badge and for the
# duplicate check — a row in one of these has not finished, so re-uploading the
# same file is a duplicate rather than a retry.
UPLOAD_ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_PROCESSING, STATUS_DONE)

# Reason codes for a rejection. Codes, not sentences: the sentence shown to the
# user is chosen by the page, and a code survives being reworded.
REJECT_NO_DOCUMENT_FOUND = "no_document_found"
REJECT_NOT_A_FINANCIAL_DOCUMENT = "not_a_financial_document"
REJECT_TOO_MANY_DOCUMENTS = "too_many_documents"
REJECT_WORKER_LOST = "worker_lost"
REJECT_INTERNAL_ERROR = "internal_error"


class CaptureUpload(db.Model):
    __tablename__ = "capture_upload"
    __table_args__ = {"schema": SCHEMA}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Resolved server-side on every request. A client-supplied entity_id is
    # never trusted — cross-entity leakage is a security defect, not a bug.
    entity_id = db.Column(
        db.String(36), db.ForeignKey(f"{SCHEMA}.entities.id"), nullable=False
    )
    uploaded_by = db.Column(
        db.String(36), db.ForeignKey(f"{SCHEMA}.user.id"), nullable=False
    )

    original_filename = db.Column(db.String(255), nullable=True)
    # The SNIFFED type, from the file's magic bytes. The declared extension is
    # not evidence and is never stored here.
    mime_type = db.Column(db.String(64), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    # 1 for images; the real page count for PDFs.
    page_count = db.Column(db.Integer, nullable=True)

    # Duplicate detection. Receipt capture generates double entries constantly
    # — a double-click, a re-upload, the same PDF mailed twice.
    content_sha256 = db.Column(db.String(64), nullable=False)

    s3_key = db.Column(db.String(512), nullable=False)

    status = db.Column(db.String(32), nullable=False, default=STATUS_QUEUED)
    reject_reason = db.Column(db.String(64), nullable=True)
    document_count = db.Column(db.Integer, nullable=True)

    # Set by the "This IS a receipt — process it anyway" override. Allowed once
    # per upload; the endpoint refuses a second attempt so a determined user
    # cannot spend money in a loop on a photo of their lunch.
    bypass_classification = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )

    created_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False, server_default=db.func.now()
    )
    updated_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False, server_default=db.func.now()
    )
    # Stamped when the worker picks the row up. The stuck-job sweeper compares
    # against this, so a thread that died with the process is recoverable.
    processing_started_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)
    completed_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<CaptureUpload {self.id} {self.status}>"
