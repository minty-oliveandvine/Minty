"""Audit row for one AI extraction attempt on the Add New Expense card.

Stage 1, §10.2. Advisory only: nothing here is read back by the expense
record, the report totals, or the Xero publish path. Losing the whole table
costs measurement data and nothing else (§10.4), which is what makes the
rollback in §11.3 cheap.

NEVER stored here: receipt bytes, the prompt, the raw model text, or any
credential (§10.2, §8.4).
"""

from uuid import uuid4

from models.db import db


class AiExpenseSuggestion(db.Model):
    __tablename__ = "ai_expense_suggestion"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Identity
    entity_id = db.Column(db.String(36), nullable=False, index=True)
    user_id = db.Column(db.String(36), nullable=True)
    report_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False,
        server_default=db.func.now(),
    )

    # Request
    model_id = db.Column(db.String(100), nullable=True)
    provider_request_id = db.Column(db.String(120), nullable=True)
    # Compliance-relevant (§8.5): evidences, per request, where inference ran.
    # "gemini-api-direct" on the spike path; the Vertex region otherwise.
    location = db.Column(db.String(60), nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    thinking_level = db.Column(db.String(16), nullable=True)

    # Usage
    input_tokens = db.Column(db.Integer, nullable=True)
    output_tokens = db.Column(db.Integer, nullable=True)
    # Invisible in the reply, billed at the output rate, and drawn from
    # max_output_tokens — so a long think truncates the JSON while the
    # output count stays small. Kept separate or that is undiagnosable.
    thought_tokens = db.Column(db.Integer, nullable=True)
    cached_tokens = db.Column(db.Integer, nullable=True)
    estimated_cost = db.Column(db.Numeric(12, 6), nullable=True)

    # Result — post-validation only, so a value here is one we would have shown
    status = db.Column(db.String(24), nullable=False, default="ok")
    error_code = db.Column(db.String(60), nullable=True)
    suggested_fields = db.Column(db.Text, nullable=True)
    confidence_by_field = db.Column(db.Text, nullable=True)

    # Outcome — written when the user presses Add (§11.4 accept rate)
    accepted_fields = db.Column(db.Text, nullable=True)
