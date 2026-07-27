import uuid

from models.db import db


class EntityCashDenomination(db.Model):
    """Which denominations an entity logs in its cash count.

    A row exists only where the entity diverges from its country default, so
    an entity with no rows sees every active CashInfo row for its country and
    automatically picks up denominations added later.
    """

    __tablename__ = "entity_cash_denomination"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    cash_id = db.Column(
        db.Integer,
        db.ForeignKey("pettycashv2.cash_info.cash_id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    # NULL inherits CashInfo.display_order.
    display_order = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
    cash_info = db.relationship("CashInfo", lazy="joined")
