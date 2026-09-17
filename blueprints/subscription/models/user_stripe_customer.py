"""The payer's billing account, plus its Stripe customer / subscription mapping.

The Stripe customer is owned by the paying *user*, not the entity. This table is
the single source of truth for that 1:1 link (and the payer's one subscription),
so the app doesn't have to resolve it via ``Customer.search`` on every request.

It is also becoming the payer's BILLING ACCOUNT — ``anchor_at``, ``currency`` and
``status`` describe the cycle itself and mean nothing to Stripe. The table keeps its
old name for now because renaming it is a cutover-time change, not an additive one;
the Stripe columns fall away once billing no longer runs through subscriptions.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import TimestampMixin
from blueprints.subscription.models.column_types import uuid_column


class UserStripeCustomer(TimestampMixin, db.Model):
    __tablename__ = "user_stripe_customer"
    __table_args__ = {"schema": "pettycashv3"}

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv3.user.id"),
        nullable=False,
        unique=True,
    )
    # Stripe is still the payment RAIL — invoices are issued against this customer —
    # so this stays after the subscription biller is gone.
    stripe_customer_id = db.Column(db.String(255), nullable=False, unique=True)

    # --- the billing cycle, owned by Minty ---------------------------------------
    #
    # The ORIGINAL cycle start, never a rolling period end. Every period is re-derived
    # from it by ``billing.period_containing``, which is what keeps a month-end anchor
    # correct: 31 Jan clamps to 28 Feb and springs back to 31 Mar. Advancing a stored
    # period_end month by month would clamp it permanently and silently shorten every
    # later period — the exact bug the engine is built to avoid.
    #
    # Null until the payer's first paid module: an app-level trial has no cycle.
    anchor_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Billing currency, fixed at the first charge — a payer's invoices must not mix.
    currency = db.Column(
        db.CHAR(3),
        db.ForeignKey("pettycashv3.currency_info.currency_code"),
        nullable=True,
    )
    # No ``paid_through``, ``dunning_started_at`` or ``dunning_attempts`` here any more,
    # and no ``status`` either.
    #
    # The first three were the ONE-CYCLE-PER-PAYER design: a payer had one subscription,
    # so one paid-through date and one dunning clock, and both lived on the account. The
    # per-entity card cutover (y1a01) replaced that with one cycle per CARD -- a payer
    # holding two cards has two paid-through dates and two dunning clocks, and only the
    # card's answer is true of the companies nominated onto it. They now live on
    # ``payer_billing_group``, and the columns here were dropped once the backfill had
    # copied every one of them across. Reading the account for those questions answered
    # for a design that no longer exists: ``payer_is_dunning`` did exactly that and
    # returned False for a payer genuinely mid-collection.
    #
    # ``status`` went earlier and for a different reason: it held active/past_due/closed
    # and nothing ever read it. Two fields claiming to hold billing state, one of them
    # decorative, is how they drift.

    def __repr__(self):
        return (
            f"<UserStripeCustomer user={self.user_id} "
            f"customer={self.stripe_customer_id}>"
        )
