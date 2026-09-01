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


class UserStripeCustomer(db.Model):
    __tablename__ = "user_stripe_customer"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id"),
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
        db.ForeignKey("pettycashv2.currency_info.currency_code"),
        nullable=True,
    )
    # What the payer has PAID FOR, and the date access is measured against. Lives here,
    # not on the module rows: a payer has one subscription and therefore one cycle, so
    # one value. Keeping it per row let three rows of the same payer hold three
    # different answers, because each was only refreshed when its own entity was
    # touched. NULL until the first charge.
    paid_through = db.Column(db.DateTime(timezone=True), nullable=True)
    # No ``status`` column. It held active/past_due/closed and looked like the account's
    # state, but nothing ever read it: collection is driven by ``dunning_started_at``
    # (see ``store.groups_in_dunning``) and access by the module row's ``phase``. Two
    # fields claiming to hold billing state, one of them decorative, is how they drift.

    # --- dunning: what COLLECTION needs between retries ---------------------------
    #
    # The anchor for the whole retry schedule, and deliberately not "last attempt at":
    # timing every retry from the FIRST failure means a delayed worker cannot push the
    # tail out past the access grace window. NULL = not in dunning.
    dunning_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dunning_attempts = db.Column(db.Integer, nullable=False, server_default="0")

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )

    def __repr__(self):
        return (
            f"<UserStripeCustomer user={self.user_id} "
            f"customer={self.stripe_customer_id}>"
        )
