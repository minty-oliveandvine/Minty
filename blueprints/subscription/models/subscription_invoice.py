"""Minty's own record of every invoice it raised.

Before these tables Stripe was the only place that could answer "what did we bill this
payer, and for what?" — and the only guard against billing a period twice, by LISTING a
customer's invoices and scanning their metadata once per payer per renewal.

The shapes mirror ``billing.Invoice`` / ``billing.Line`` so persisting is a write of what
the biller already computed, not a second model of it. See migration ``a1b2c3d4e5f7``
for the full rationale; the two rules that matter when reading rows here:

* ``entity_name`` / ``product_name`` are SNAPSHOTS. An entity renamed next year must not
  rewrite what last year's invoice said it was for — so they are copied, not joined, and
  ``entity_id`` / ``payer_user_id`` carry no foreign key. This is history, and history
  that changes underneath you is worse than none.
* ``total`` is what was actually SENT, not a sum of the lines on demand:
  ``billing_gateway.issue_invoice`` drops zero-amount lines, so a locally recomputed
  total can legitimately differ from what the processor was asked to collect.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import CreatedAtMixin, TimestampMixin
from blueprints.subscription.models.column_types import (
    tz_datetime,
    uuid_column,
)
from blueprints.shared.schema import SCHEMA


class SubscriptionInvoice(TimestampMixin, db.Model):
    __tablename__ = "subscription_invoice"
    __table_args__ = (
        # UNIQUE, not merely indexed: this is what makes charging a period twice
        # impossible rather than unlikely. ``renewals.period_key`` feeds it.
        db.Index(
            "uq_subscription_invoice_idempotency_key", "idempotency_key", unique=True
        ),
        db.Index("ix_subscription_invoice_payer", "payer_user_id", "period_start"),
        db.Index("ix_subscription_invoice_external_id", "external_id"),
        db.Index(
            "ix_subscription_invoice_group", "billing_group_id", "period_start"
        ),
        {"schema": SCHEMA},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    # WHO owes it. No FK: an invoice is history and must survive the payer row.
    payer_user_id = db.Column(uuid_column(), nullable=False)
    # Denormalised from user_stripe_customer rather than joined, because that mapping can
    # be re-pointed (see checkout._resolve_customer_id) and this must keep saying which
    # customer was actually charged.
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    # The processor's own id (in_...). NULL means the row was reserved but we never heard
    # back that anything was sent — see ``store.reserve_invoice``.
    external_id = db.Column(db.String(255), nullable=True)

    # The period this invoice COVERS, half-open [start, end) to match billing.Period —
    # not the date it was raised.
    period_start = db.Column(tz_datetime(), nullable=False)
    period_end = db.Column(tz_datetime(), nullable=False)

    currency = db.Column(
        db.CHAR(3),
        db.ForeignKey(f"{SCHEMA}.currency_info.currency_code"),
        nullable=False,
    )
    # Minor units, like every other amount in this schema. Never a float.
    total = db.Column(db.Integer, nullable=False, server_default="0")
    # draft / open / paid / uncollectible / void — the processor's vocabulary, kept
    # as-is so there is no translation layer to disagree with.
    status = db.Column(db.String(20), nullable=False)
    memo = db.Column(db.String(500), nullable=True)

    # WHICH CARD PAID IT — "Visa •••• 4242" — captured when the charge settled. A
    # SNAPSHOT, for the same reason as entity_name above: the account's current default
    # is a different question the moment a card is updated, and the invoice it would be
    # wrong about first is a failed one. Display only; nothing decides anything on it.
    payment_method = db.Column(db.String(100), nullable=True)
    # Stripe's hosted page for this invoice — the PDF download and, while it is open, a
    # way to pay it. Stored rather than fetched per row, so listing invoices is not N
    # round trips. Null until the invoice is finalized; a draft has none.
    #
    # A CAPABILITY URL: its token is the authorisation, so it is served to the payer and
    # never logged.
    hosted_invoice_url = db.Column(db.String(500), nullable=True)

    # WHICH GROUP — which card — this invoice was raised for. A renewal raises one
    # invoice per ``payer_billing_group``, so "the payer's invoice for this period" is no
    # longer a single document and both ``renewals._already_invoiced`` and
    # ``dunning._current_period_key`` have to ask per group instead.
    #
    # No FK, like every other reference on this table: an invoice is history and must
    # survive the group being closed. NULL on rows raised before per-entity cards, which
    # is what those rows honestly mean — one card paid for everything.
    # uuid: payer_billing_group.id is inside the subscription tables and converted
    # with them. payer_user_id above stays String(36) because ``user`` has not.
    billing_group_id = db.Column(uuid_column(), nullable=True)

    # The double-billing guard. Nullable: a mid-period purchase has no natural key and
    # is guarded by the user waiting for the response instead.
    idempotency_key = db.Column(db.String(255), nullable=True)

    issued_at = db.Column(tz_datetime(), nullable=True)
    paid_at = db.Column(tz_datetime(), nullable=True)

    lines = db.relationship(
        "SubscriptionInvoiceLine",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="SubscriptionInvoiceLine.created_at",
    )

    def __repr__(self):
        return (
            f"<SubscriptionInvoice {self.external_id or self.id} "
            f"{self.status} {self.total}>"
        )


class SubscriptionInvoiceLine(CreatedAtMixin, db.Model):
    __tablename__ = "subscription_invoice_line"
    __table_args__ = (
        db.Index("ix_subscription_invoice_line_invoice_id", "invoice_id"),
        db.Index("ix_subscription_invoice_line_entity_id", "entity_id"),
        {"schema": SCHEMA},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = db.Column(
        uuid_column(),
        db.ForeignKey(f"{SCHEMA}.subscription_invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Every line is attributable to exactly ONE entity — the property that made these
    # invoices readable where the Stripe-subscription ones were not, because there every
    # line inherited the subscription's entity. No FK: history.
    entity_id = db.Column(uuid_column(), nullable=False)
    # SNAPSHOTS, not references. See the module docstring.
    entity_name = db.Column(db.String(255), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)

    amount = db.Column(db.Integer, nullable=False)
    # full / remaining / unused / credit — mirrors billing.Line.kind, which is what
    # decides how the line describes itself to the customer.
    kind = db.Column(db.String(20), nullable=False, server_default="full")
    # The instant a proration was measured from. NULL for a whole-period line.
    at = db.Column(tz_datetime(), nullable=True)

    invoice = db.relationship("SubscriptionInvoice", back_populates="lines")

    def __repr__(self):
        return (
            f"<SubscriptionInvoiceLine {self.entity_name} "
            f"{self.product_name} {self.amount}>"
        )
