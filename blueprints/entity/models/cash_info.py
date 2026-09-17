"""Per-currency catalogue of cash denominations (``cash_info``).

The source of truth for face values used by the cash count. Adding a denomination is an
INSERT here - no schema change, no code change. Entities pick which of these they log via
``EntityCashSetting``. Keyed on currency, not country: a face value is a property of the
currency. ``cash_id`` (the old serial key) is a synonym of the uuid ``id``.
"""
import uuid

from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid, Money, pg_enum
from blueprints.shared.enums import CashType
from models.db import db


class CashInfo(db.Model):
    __tablename__ = "cash_info"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    currency_id = db.Column(MintyUuid(), db.ForeignKey("pettycashv3.currency_info.id"), nullable=False)
    type = db.Column(pg_enum(CashType), nullable=True)
    cash_value = db.Column(Money(12, 2), nullable=False)
    cash_name = db.Column(db.String(20))
    description = db.Column(db.Text)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    cash_id = synonym("id")
    desc = synonym("description")
