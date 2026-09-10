"""An offer to hand one entity's subscription to a different payer — and the journal of
what happened when it was accepted.

Two jobs in one table, deliberately.

As an OFFER it is ordinary: the current payer nominates another admin, the nominee accepts
or declines, and it expires if nobody answers.

As a JOURNAL it is the thing that makes accepting safe. Accepting has to charge the new
payer and then move the payer pointer, and those two cannot be one transaction — every
``store`` helper commits its own unit of work, and by the time the processor declines, the
invoice row and its status are already on disk. So the accept is ORDERED rather than
atomic, and the order needs a durable record: ``charging`` is written and committed before
the charge is attempted, ``charged`` once the money is in, ``accepted`` once the pointer
has moved. A process that dies anywhere in between leaves a row that says exactly how far
it got, which both a retried accept and ``transfers.repair_stranded`` can finish.

The renewal runner already works this way — it charges, then advances ``paid_through``, and
repairs a crash between the two by recomputing the invoice key and adopting what it finds.
The difference is that a renewal recomputes its key on the next pass anyway, while an
accept is a one-shot user action that nothing would ever revisit. Hence this row.
"""
import uuid

from blueprints.subscription.constants import (
    TRANSFER_OPEN_STATUSES,
    TRANSFER_PENDING,
    TRANSFER_STRANDED_STATUSES,
)
from models.db import db
from blueprints.subscription.models.mixins import CreatedAtMixin
from blueprints.subscription.models.column_types import (
    TRANSFER_STATUS,
    uuid_column,
)

# The status vocabulary lives in ``constants``, which is deliberately dependency-free —
# importing it from here instead would make every consumer of a status pull the model
# module in ahead of ``models.db`` and hit the partial-initialisation cycle.
_OPEN = ",".join(f"'{s}'" for s in TRANSFER_OPEN_STATUSES)
_STRANDED = ",".join(f"'{s}'" for s in TRANSFER_STRANDED_STATUSES)


class SubscriptionTransfer(CreatedAtMixin, db.Model):
    __tablename__ = "subscription_transfer"
    __table_args__ = (
        # ONE open offer per entity. Partial, so declined and expired history accumulates
        # freely while the live claim stays unique — and it covers the in-flight states,
        # not just ``pending``, or a second accept could start while the first is
        # mid-charge and both would move the same pointer.
        db.Index(
            "uq_subscription_transfer_open",
            "entity_id",
            unique=True,
            postgresql_where=db.text(f"status IN ({_OPEN})"),
            sqlite_where=db.text(f"status IN ({_OPEN})"),
        ),
        # The repair step's work list. Normally empty — an accept that completes leaves
        # nothing here — so a partial index costs nothing to keep.
        db.Index(
            "ix_subscription_transfer_stranded",
            "status",
            postgresql_where=db.text(f"status IN ({_STRANDED})"),
            sqlite_where=db.text(f"status IN ({_STRANDED})"),
        ),
        db.Index("ix_subscription_transfer_to_user", "to_user_id", "status"),
        db.Index("ix_subscription_transfer_entity", "entity_id", "created_at"),
        {"schema": "pettycashv2"},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"),
        nullable=False,
    )

    # WHO, on each side. No FK either way, for the same reason ``subscription_invoice``
    # has none on its payer: this is a record of something that happened between two
    # people, and it has to survive both of them leaving.
    from_user_id = db.Column(db.String(36), nullable=False)
    to_user_id = db.Column(db.String(36), nullable=False)

    status = db.Column(TRANSFER_STATUS, nullable=False, default=TRANSFER_PENDING)

    # Checked at accept, not only by a sweep. An offer whose day has passed must be
    # refused even if nothing has swept it yet — otherwise "expires in 7 days" means
    # "expires whenever the sweep next runs", which is a different promise.
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    responded_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # --- what the accept actually did -------------------------------------------
    # Evidence, written at accept and never recomputed. The quote shown at OFFER time is
    # only an estimate: the old payer's ``paid_through`` advances on every successful
    # renewal, so an offer that outlives a cycle would be quoting a window that has since
    # moved. These record what was true at the moment it was taken.
    accepted_billed_through = db.Column(db.DateTime(timezone=True), nullable=True)
    accepted_anchor_at = db.Column(db.DateTime(timezone=True), nullable=True)
    quoted_amount = db.Column(db.Integer, nullable=True)  # minor units, like every amount
    quoted_currency = db.Column(db.CHAR(3), nullable=True)

    # --- the charge ---------------------------------------------------------------
    # How many times a charge has been STARTED for this offer. Incremented and committed
    # before each attempt, and it is what makes the idempotency key safe in both
    # directions: ``transfer-{id}-{attempt}`` is identical for a double-click within one
    # attempt, so the unique index on ``subscription_invoice.idempotency_key`` refuses the
    # second — and different on the next attempt, so a card that was declined can be fixed
    # and retried. Without the counter a fixed key would jam, because voiding an invoice
    # deliberately KEEPS its row and its key claimed.
    charge_attempt = db.Column(db.Integer, nullable=False, server_default="0")
    charge_key = db.Column(db.String(120), nullable=True)
    charge_invoice_id = db.Column(db.String(64), nullable=True)

    note = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return (
            f"<SubscriptionTransfer {self.entity_id} "
            f"{self.from_user_id}->{self.to_user_id} {self.status}>"
        )
