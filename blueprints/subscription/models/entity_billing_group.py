"""Which card pays for this company — the per-entity payment method, as a pointer.

One row per (entity, payer): the card this payer has nominated for this company. The card
itself, and the cycle it owns, live on ``payer_billing_group``.

PER (ENTITY, PAYER), NOT PER ENTITY. Exactly the grain ``entity_billing_consent`` was
widened to when subscriptions became transferable, and for the same reason: unique on
``entity_id`` alone, the OLD payer's nomination would go on naming a card after the
company had been handed to someone else — and that card belongs to a different person.
The previous payer's row stays behind as history, because "which card was this company on
in June" is asked most often by the person who no longer pays for it.

NOT A COLUMN ON ``entity_module_subscription``. That table is per (entity, MODULE), so a
card held there would have to be kept in agreement across an entity's rows — the burden
``payer_user_id`` already carries, and the reason ``store.upsert_module_row`` refuses to
change it rather than trusting callers. A second such column doubles the burden for no
gain: the nomination is per company, so one row per company is the honest shape.

NOMINATION IS REQUIRED, NOT INHERITED. There is deliberately no fallback to the account
default. A billable entity with no row here is a billing ERROR — reported and skipped,
never guessed at, the same way ``renewals.build_renewal`` skips a module set the catalog
cannot price rather than inventing a number. A silent fallback is how one card came to
pay for every company in the first place.

A TRIAL NEEDS NO ROW. Nothing is charged during an app-level trial, so no card has to be
nominated to start one. The nomination is required at the point the entity begins to
bill: a paid subscribe, or the trial converting.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import TimestampMixin
from blueprints.subscription.models.column_types import uuid_column


class EntityBillingGroup(TimestampMixin, db.Model):
    __tablename__ = "entity_billing_group"
    __table_args__ = (
        # One nomination per company per payer — see the module docstring.
        db.UniqueConstraint(
            "entity_id", "payer_user_id", name="uq_entity_billing_group_entity_payer"
        ),
        db.Index("ix_entity_billing_group_entity", "entity_id"),
        db.Index("ix_entity_billing_group_payer", "payer_user_id"),
        db.Index("ix_entity_billing_group_group", "billing_group_id"),
        {"schema": "pettycashv3"},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv3.entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Whose nomination this is. FK to ``user`` for the same reason the group's is.
    payer_user_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv3.user.id"),
        nullable=False,
    )
    # uuid, unlike entity_id and payer_user_id above. This one points INSIDE the
    # subscription tables, so it converted with them; those two point at
    # ``entities`` / ``user``, which are still String(36) - and Postgres cannot key
    # a uuid column to a varchar one. See column_types for the whole boundary.
    billing_group_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv3.payer_billing_group.id"),
        nullable=False,
    )
    # How the card came to be nominated — "capture" (a card entered while setting this
    # company up), "chosen" (an already-saved card picked for it) or "backfill" (carried
    # over from the account default when per-entity cards landed). Kept for support, the
    # same way ``entity_billing_consent.source`` is: "why is this company on this card?"
    source = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return (
            f"<EntityBillingGroup entity={self.entity_id} "
            f"group={self.billing_group_id} via={self.source}>"
        )
