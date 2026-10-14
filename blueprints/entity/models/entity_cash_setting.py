from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class EntityCashSetting(db.Model):
    """Which denominations an entity logs in its cash count (``entity_cash_setting``).

    The cash mirror of EntitySaleSetting. Setting a company's currency writes one row per
    active CashInfo row of it (entity/services/cash_settings.py, and minty-onboarding-api's
    copy for the wizard). An entity with no rows - one created before that - sees every
    active CashInfo row for its currency.
    """

    __tablename__ = "entity_cash_setting"
    __table_args__ = {"schema": SCHEMA}
    entity_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"), primary_key=True,
    )
    cash_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.cash_info.id", ondelete="CASCADE"), primary_key=True,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now(), onupdate=db.func.now(),
    )
    cash_info = db.relationship("CashInfo", lazy="joined")
