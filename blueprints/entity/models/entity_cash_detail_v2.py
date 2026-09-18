"""A company's cash-in-stock per denomination (``entity_cash_detail``; was
``entity_cash_detail_v2`` / ``EntityCashDetailV2`` - the old class name stays importable)."""
from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid, Money, pg_enum
from blueprints.shared.enums import CashType
from models.db import db
from blueprints.shared.schema import SCHEMA


class EntityCashDetail(db.Model):
    __tablename__ = "entity_cash_detail"
    __table_args__ = {"schema": SCHEMA}
    entity_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"), primary_key=True
    )
    cash_id = db.Column(MintyUuid(), db.ForeignKey(f"{SCHEMA}.cash_info.id"), primary_key=True)
    cash_type = db.Column(pg_enum(CashType), nullable=True)
    cash_instock = db.Column(Money(), nullable=True)
    description = db.Column(db.Text)
    desc = synonym("description")
    cash_info = db.relationship("CashInfo", backref="entity_cash_detail", lazy=True)


EntityCashDetailV2 = EntityCashDetail
