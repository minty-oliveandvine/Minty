"""One card, and the billing cycle that card owns.

ONE ACCOUNT, SEVERAL SHELVES. ``user_stripe_customer`` used to be the whole billing
account: one card, one ``paid_through``, one dunning clock, and every company the payer
paid for sharing them. That is what made "choose a card" mean "change the account
default" everywhere in the app — see the module docstring in ``services.payment_methods``.

A billing group is the smaller unit that replaces it: **one payment method, plus
everything it pays for**. A payer may have several. ``entity_billing_group`` says which
companies are on which.

WHAT MOVED HERE, AND WHY EACH ONE HAD TO.

* ``stripe_payment_method_id`` — the card that will be charged for this group's entities.
* ``paid_through`` — what THIS card has paid for. One invoice is raised per group, so this
  is exactly the grain the money is collected at.
* ``dunning_started_at`` / ``dunning_attempts`` — collection is per card too. A payer with
  a good card on company A and a dead one on company B must keep A: the decline has to be
  contained, which it cannot be while the retry clock is a single per-payer value.

THIS IS NOT THE OLD PER-ROW ``current_period_end`` COMING BACK. That one was removed for
drifting between one payer's entities, and it drifted because it was refreshed only when
its own entity happened to be touched — three rows of one payer, three different answers,
all of them claiming to be the same fact. This value is written by exactly one thing, the
charge that collected it, and there is one of those per group per period.

WHAT STAYS ON THE PAYER. ``anchor_at`` and ``currency``, on ``user_stripe_customer``.
Every group of a payer renews on the SAME period boundaries — one cycle, several invoices
— so ``billing.period_containing`` and the month-end clamp are untouched, and a payer's
invoices still cannot mix currencies.

THE CARD IS AN ATTRIBUTE, NOT THE KEY. Entities point at the GROUP, and the group names
the card. If they pointed straight at a ``pm_...`` id, replacing an expiring card would
strand the cycle: a new id is a new key, its ``paid_through`` would start NULL, and
``renewals.due_renewals`` skips NULL outright — the entity would quietly stop renewing.
Here, replacing a card is an UPDATE of one column and the cycle survives it.

Only the id is held. The number is typed into Stripe Elements and confirmed against a
SetupIntent; no PAN reaches this process, this table or these logs.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import TimestampMixin
from blueprints.subscription.models.column_types import uuid_column


class PayerBillingGroup(TimestampMixin, db.Model):
    __tablename__ = "payer_billing_group"
    __table_args__ = (
        # A payer must not hold two groups on one card: the same entity's renewal could
        # then be claimed by either, and the two would disagree about what was paid.
        db.UniqueConstraint(
            "payer_user_id",
            "stripe_payment_method_id",
            name="uq_payer_billing_group_payer_card",
        ),
        db.Index("ix_payer_billing_group_payer", "payer_user_id"),
        db.Index("ix_payer_billing_group_dunning", "dunning_started_at"),
        {"schema": "pettycashv2"},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    # FK to ``user``, not to ``user_stripe_customer`` — the same choice the module rows
    # make. A group can be nominated before the payer has ever been charged.
    payer_user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id"),
        nullable=False,
    )
    # ``pm_...``. Mutable: this is how a card is REPLACED without losing the cycle.
    stripe_payment_method_id = db.Column(db.String(255), nullable=False)

    # --- the cycle this card owns -------------------------------------------------
    #
    # NULL until this card has actually collected something. ``due_renewals`` skips a
    # NULL, which is what stops a freshly nominated card being billed for history.
    paid_through = db.Column(db.DateTime(timezone=True), nullable=True)

    # Anchor for the whole retry schedule, and deliberately not "last attempt at" — see
    # ``services.dunning``. NULL = this card is not in collection.
    dunning_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dunning_attempts = db.Column(db.Integer, nullable=False, server_default="0")

    def __repr__(self):
        return (
            f"<PayerBillingGroup payer={self.payer_user_id} "
            f"card={self.stripe_payment_method_id}>"
        )
