"""Per-entity record that the payer agreed to be billed for THIS entity.

A payer's Stripe customer is shared across every entity they pay for, and it carries
one card. Without this table, saving a card while setting up entity #1 would silently
authorise charges for entity #2 the moment it was created: paid checkout would find the
saved card and bill it with no prompt, and — worse — an app-level trial on entity #2
would auto-convert to paid at trial end with no user action at all (see
``checkout.convert_or_expire_due_trials``).

So consent is tracked per ENTITY, not per payer: having a card is necessary to be
charged, but no longer sufficient. It's recorded when the payer explicitly confirms
billing for an entity — either by entering a card in a setup Checkout opened for it, or
by confirming the in-app "you'll be billed X on card ending Y" step.

Consent is deliberately NOT per module: once the payer has agreed to be billed for an
entity, adding another module to that same entity is an ordinary purchase.

Note this cannot be a per-entity CARD. One payer has one Stripe subscription with a line
per entity, and a Stripe subscription has a single default payment method — subscription
items can't each carry their own. Consent is the per-entity thing; the card is shared.
"""
import uuid

from models.db import db


class EntityBillingConsent(db.Model):
    __tablename__ = "entity_billing_consent"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id"),
        nullable=False,
        unique=True,
    )
    # Who agreed. FK to user (not user_stripe_customer) for the same reason the
    # subscription mirror does it: consent can be recorded before a customer exists.
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id"),
        nullable=False,
        index=True,
    )
    # How it was given — "card" (entered a card in this entity's setup Checkout) or
    # "confirmed" (accepted the in-app charge confirmation against a saved card).
    # Kept for support/audit: "why was I billed for this entity?"
    source = db.Column(db.String(20), nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )

    def __repr__(self):
        return f"<EntityBillingConsent entity={self.entity_id} via={self.source}>"
