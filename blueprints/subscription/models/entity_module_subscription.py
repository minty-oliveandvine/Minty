"""Per-(entity, module) subscription state — one denormalized row per module.

Carries access, the app-level trial, and the cancel-extension lifecycle. These rows
ARE the source of truth: they were once a mirror of Stripe subscription state, but
with the Stripe biller retired there is nothing upstream of them. The paying user
(and, via ``user_stripe_customer``, the Stripe customer the invoices are issued
against) is referenced by ``payer_user_id`` — a FK to ``user``, NOT to
``user_stripe_customer``, so a trial row can exist before any card/customer.

A bundled entity has two rows (PETTY_CASH + BILL) billed as ONE bundle price, so
never total an entity by summing its rows — price the module SET via
``store.billing_plan_for_codes``. Phase / extension_state vocab lives in
``blueprints.subscription.constants``.
"""
import uuid

from models.db import db


class EntityModuleSubscription(db.Model):
    __tablename__ = "entity_module_subscription"
    __table_args__ = (
        db.UniqueConstraint(
            "entity_id", "function_code", name="uq_ems_entity_function"
        ),
        {"schema": "pettycashv2"},
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # --- identity ---
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id"),
        nullable=False,
        index=True,
    )
    function_code = db.Column(db.String(100), nullable=False, index=True)  # PETTY_CASH / BILL
    payer_user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id"),
        nullable=False,
        index=True,
    )

    # --- lifecycle ---
    phase = db.Column(db.String(30), nullable=False)  # see constants.SUBSCRIPTION_PHASES
    # Single access-end authority: trial end, cancel extension, or past-due grace.
    app_access_until = db.Column(db.DateTime(timezone=True), nullable=True)

    # --- app-level trial (no Stripe object exists during the trial) ---
    # Only the END is kept. ``trial_start`` and ``trial_used`` were written at trial
    # creation and read by nothing: the start is recoverable from ``created_at``, and
    # "has this module been trialled" is answered by the row existing at all, which is
    # what ``start_module_trial`` actually checks.
    trial_end = db.Column(db.DateTime(timezone=True), nullable=True)

    # When this module was FIRST charged for. Null = never billed, i.e. still a free
    # trial. Set once and never cleared, so it answers "is this a paid module?" for the
    # rest of the row's life — including after it is cancelled, which is the case that
    # matters. Written by both billers.
    #
    # This exists because the question used to be asked of the Stripe subscription
    # item id, which only the Stripe biller ever set. In-house that was always NULL, so
    # every paid module looked like a trial: cancelled ones were expired by the
    # trial-end job, and un-cancelling one was refused with "your free trial has ended".
    first_billed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # No ``current_period_end``. It was stamped on every conversion and purchase and
    # read by nothing: access is decided by ``phase`` and ``app_access_until``, and the
    # payer's cycle is re-derived from ``user_stripe_customer.anchor_at``. Keeping a
    # rolling period end per row is what let three rows of one payer hold three answers,
    # each refreshed only when its own entity was touched.

    # --- cancel extension (see constants.EXTENSION_STATES) ---
    # The amount is recorded here and collected by the next renewal run, so cancelling
    # never depends on a card clearing. Under Stripe this was a pending invoice ITEM
    # swept onto the anchor invoice, and the row carried its id instead.
    extension_state = db.Column(db.String(20), nullable=True)
    # What the extension is WORTH, in minor units. Under Stripe the amount lived on the
    # pending invoice item and the row only needed its id; billing in-house there is no
    # such item, so the row carries the amount until our own renewal run collects it.
    # Null = nothing owed.
    extension_amount = db.Column(db.Integer, nullable=True)

    # No ``cancel_reason``. Why the customer left is HISTORY — nothing here reads it to
    # decide access or what to bill — so it belongs in ``subscription_audit_log``, which
    # keeps one row per cancellation. Held here it would be state, and a module cancelled,
    # renewed and cancelled again would overwrite the first reason with the second.

    # --- bookkeeping ---
    # No ``synced_at``: it recorded the last reconciliation against live Stripe for a
    # staleness check that was never built. Its only writer, ``store.mark_synced``, had
    # no callers.
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
            f"<EntityModuleSubscription {self.entity_id}/{self.function_code} "
            f"phase={self.phase}>"
        )
