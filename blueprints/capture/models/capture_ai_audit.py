"""One row per AI call. NUMBERS ONLY.

No amounts, no supplier names, no descriptions, no file bytes — not even
truncated. Stage 1's endpoint makes the same choice and states the reason in
``blueprints/report/routes/expense_ai.py``: those are a client's financial
details, and a metrics table is the wrong place for them. The values live in
``capture_draft.suggested``, behind the same authorisation as everything else.

What this table is for: cost, latency, cache hit rate, and how often the model
is confident. It answers "is the feature worth what it costs" and "did that
change make it better", and neither question needs a single receipt total.

Stage 1 shipped without any audit table at all and logs these numbers instead.
That was defensible when nothing persisted. Stage 2 persists drafts anyway and
makes up to eleven calls per upload, so the numbers need to be queryable.
"""

from uuid import uuid4

from sqlalchemy.dialects.postgresql import JSONB

from models.db import db

SCHEMA = "pettycashv2"

# JSONB in PostgreSQL, plain JSON everywhere else — see the note in
# capture_draft.py for why the variant is required rather than tidy.
JSON_TYPE = db.JSON().with_variant(JSONB(), "postgresql")

PASS_SPLIT = 1
PASS_EXTRACT = 2

STATUS_OK = "ok"
STATUS_NO_SUGGESTION = "no_suggestion"


class CaptureAiAudit(db.Model):
    __tablename__ = "capture_ai_audit"
    __table_args__ = {"schema": SCHEMA}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    upload_id = db.Column(
        db.String(36),
        db.ForeignKey(f"{SCHEMA}.capture_upload.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Null for Pass 1 — the split call belongs to the upload, not to any one
    # document, because it is the call that decides how many there are.
    draft_id = db.Column(db.String(36), nullable=True)
    entity_id = db.Column(db.String(36), nullable=False)

    pass_number = db.Column(db.SmallInteger, nullable=False)

    model_id = db.Column(db.String(64), nullable=True)
    # Same meaning as Stage 1's ``location()``: a compliance field, not a
    # performance knob. On the direct Gemini API there is no region to pin, and
    # that absence is itself the fact worth evidencing — the value then names
    # the route and the tier instead.
    location = db.Column(db.String(64), nullable=True)

    latency_ms = db.Column(db.Integer, nullable=True)
    input_tokens = db.Column(db.Integer, nullable=True)
    output_tokens = db.Column(db.Integer, nullable=True)
    # Billed at the OUTPUT rate and invisible in the reply. Stage 1 learnt this
    # the hard way: leaving thinking out of the sum understated a measured call
    # by about 60%, and a truncation caused by a long think is indistinguishable
    # from a terse answer without this column beside the other two.
    thought_tokens = db.Column(db.Integer, nullable=True)
    # Zero across repeated calls for one entity means the cacheable prefix is
    # either under Gemini's minimum or is not byte-stable. Worth an alert.
    cached_tokens = db.Column(db.Integer, nullable=True)

    # An indication for the cost dashboard, not an invoice.
    estimated_cost = db.Column(db.Numeric(12, 6), nullable=True)

    status = db.Column(db.String(32), nullable=False)
    reason = db.Column(db.String(64), nullable=True)

    # Field name -> confidence number. NO VALUES.
    confidence_by_field = db.Column(JSON_TYPE, nullable=True)

    created_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False, server_default=db.func.now()
    )

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<CaptureAiAudit {self.id} pass{self.pass_number} {self.status}>"
