from blueprints.shared.column_types import MintyUuid
from models.db import db


class EntityCashSetting(db.Model):
    """Which denominations an entity logs in its cash count (``entity_cash_setting``).

    The cash mirror of EntitySaleSetting. A row exists only where the entity diverges from
    its currency default, so an entity with no rows sees every active CashInfo row for its
    currency and automatically picks up denominations added later.
    """

    __tablename__ = "entity_cash_setting"
    __table_args__ = {"schema": "pettycashv3"}
    entity_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.entities.id", ondelete="CASCADE"), primary_key=True,
    )
    cash_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.cash_info.id", ondelete="CASCADE"), primary_key=True,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now(), onupdate=db.func.now(),
    )
    cash_info = db.relationship("CashInfo", lazy="joined")
