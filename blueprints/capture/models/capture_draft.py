"""One row per document found inside an upload.

Five receipts in one PDF are FIVE rows here, not one. That is the decision the
whole two-pass engine exists to serve: Pass 1 works out where the document
boundaries are, Pass 2 reads each one separately, and each produces a row that
the user reviews and confirms on its own.

Nothing in this table is an accounting record. A row becomes one only when a
human presses Confirm, and then ``target_ref`` names what it became.
"""

from uuid import uuid4

from sqlalchemy.dialects.postgresql import JSONB

from models.db import db

SCHEMA = "pettycashv2"

# JSONB in PostgreSQL, plain JSON everywhere else.
#
# The variant is not decoration: the test harness runs on SQLite, and a bare
# postgresql.JSONB column fails to compile there — which takes down every test
# that calls create_all(), not just this feature's. Production still gets JSONB
# (binary, no reparse on read), and the migration declares the same thing.
JSON_TYPE = db.JSON().with_variant(JSONB(), "postgresql")

# ---------------------------------------------------------------------------
# What kind of document Pass 1 decided this is.
# ---------------------------------------------------------------------------
DOC_TYPE_RECEIPT = "receipt"
DOC_TYPE_INVOICE = "invoice"
DOC_TYPE_OTHER = "other"

DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_INVOICE, DOC_TYPE_OTHER)

# ---------------------------------------------------------------------------
# Where a confirmed draft goes. Decided by ``services/routing.py`` in Python,
# never by the model — see that module for why.
# ---------------------------------------------------------------------------
DEST_PETTY_CASH = "petty_cash"
DEST_PAYMENT = "payment"
# "We know what this is, but you don't have the module that would receive it."
# Not an error and not a rejection: the draft sits in the queue with an
# explanation, because the user should see that the system understood it.
DEST_HOLD = "hold"
DEST_REJECTED = "rejected"

DESTINATIONS = (DEST_PETTY_CASH, DEST_PAYMENT, DEST_HOLD, DEST_REJECTED)

# ---------------------------------------------------------------------------
# Status. ``posted`` is terminal — once a draft has become a real record there
# is no state it can move to that would be honest.
# ---------------------------------------------------------------------------
STATUS_READY = "ready"
STATUS_NEEDS_CLARIFICATION = "needs_clarification"
STATUS_HOLD = "hold"
STATUS_CONFIRMING = "confirming"
STATUS_SEND_FAILED = "send_failed"
STATUS_POSTED = "posted"
STATUS_ARCHIVED = "archived"

DRAFT_STATUSES = (
    STATUS_READY,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_HOLD,
    STATUS_CONFIRMING,
    STATUS_SEND_FAILED,
    STATUS_POSTED,
    STATUS_ARCHIVED,
)

# What the bubble's badge counts.
DRAFT_ATTENTION_STATUSES = (
    STATUS_READY,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_SEND_FAILED,
)

# How many times the retry sweeper will re-push a draft before leaving it for a
# human. Five attempts with exponential backoff spans roughly half an hour.
MAX_SEND_ATTEMPTS = 5


class CaptureDraft(db.Model):
    __tablename__ = "capture_draft"
    __table_args__ = {"schema": SCHEMA}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    upload_id = db.Column(
        db.String(36),
        db.ForeignKey(f"{SCHEMA}.capture_upload.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Denormalised from the upload ON PURPOSE. Every authorisation check in the
    # feature reads it, and resolving it through capture_upload would add a
    # join to every single request for no benefit.
    entity_id = db.Column(
        db.String(36), db.ForeignKey(f"{SCHEMA}.entities.id"), nullable=False
    )

    # 1, 2, 3 ... within the upload. Drives "Document 2 of 5" on the card.
    sequence = db.Column(db.Integer, nullable=False)

    # 1-based and inclusive. A two-page invoice is one row with start 1, end 2.
    page_start = db.Column(db.Integer, nullable=False)
    page_end = db.Column(db.Integer, nullable=False)

    # Pass 1's short description, e.g. "top-left receipt, Starbucks HK$48".
    # Only meaningful when several documents share one page: Pass 2 receives
    # the same page image for each of them, and this is the only thing telling
    # it which one to read. Untrusted text off a photograph — render with
    # textContent, never innerHTML.
    locator = db.Column(db.String(200), nullable=True)

    doc_type = db.Column(db.String(32), nullable=False)
    doc_type_confidence = db.Column(db.Numeric(4, 3), nullable=True)

    destination = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=False, default=STATUS_READY)

    # Pass 2's validated output, in the {value, confidence, band, applied}
    # shape Stage 1 uses. Kept whole so the queue page can reuse the marking
    # logic from static/js/expense_ai.js without translating anything.
    suggested = db.Column(JSON_TYPE, nullable=True)
    # What the user actually saved. Written on confirm. The pair of columns is
    # the training data for entity-specific behaviour: "the model said X, the
    # user chose Y" is the only signal worth feeding back into the prompt.
    confirmed = db.Column(JSON_TYPE, nullable=True)

    # Lifted out of ``suggested`` so the queue can sort, filter and total
    # without unpacking JSON on every row.
    document_date = db.Column(db.Date, nullable=True)
    amount = db.Column(db.Numeric(14, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    supplier_name = db.Column(db.String(150), nullable=True)

    # The single-document file cut out of the original. Null when the upload
    # held only one document — then the parent's s3_key is the file.
    page_s3_key = db.Column(db.String(512), nullable=True)

    # What it became: a shop_expense.id, or Module 2's PaymentRequest id.
    target_ref = db.Column(db.String(128), nullable=True)

    send_attempts = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    # Never contains file contents. A message from our own code or from the
    # destination service, truncated.
    last_error = db.Column(db.String(500), nullable=True)

    created_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False, server_default=db.func.now()
    )
    updated_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False, server_default=db.func.now()
    )
    confirmed_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)
    confirmed_by = db.Column(db.String(36), nullable=True)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<CaptureDraft {self.id} {self.doc_type}->{self.destination} {self.status}>"
