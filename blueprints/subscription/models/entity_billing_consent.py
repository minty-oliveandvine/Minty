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

Per entity AND PER PAYER. It was once unique on ``entity_id`` alone, which was
indistinguishable from correct only because an entity's payer never changed. Once a
subscription can be handed to someone else, a single row per entity means the OLD payer's
agreement authorises charging the NEW payer's card — the trial-end job included, with no
user action at all. So the grain is ``(entity_id, user_id)``: each payer answers for
themselves, and the previous payer's row stays as history, because "why was I billed for
this entity in June" is asked most often by the person who no longer pays.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import CreatedAtMixin
from blueprints.subscription.models.column_types import uuid_column


class EntityBillingConsent(CreatedAtMixin, db.Model):
    __tablename__ = "entity_billing_consent"
    __table_args__ = (
        # One consent per (entity, payer) — see the module docstring. Not on entity_id
        # alone, or a transferred entity would keep answering about the wrong person.
        db.UniqueConstraint(
            "entity_id", "user_id", name="uq_entity_billing_consent_entity_user"
        ),
        {"schema": "pettycashv3"},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv3.entities.id"),
        nullable=False,
    )
    # Who agreed. FK to user (not user_stripe_customer) for the same reason the
    # subscription mirror does it: consent can be recorded before a customer exists.
    user_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv3.user.id"),
        nullable=False,
        index=True,
    )
    # How it was given — "card" (entered a card in this entity's setup Checkout) or
    # "confirmed" (accepted the in-app charge confirmation against a saved card).
    # Kept for support/audit: "why was I billed for this entity?"
    source = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f"<EntityBillingConsent entity={self.entity_id} via={self.source}>"
