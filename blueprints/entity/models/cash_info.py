from sqlalchemy.dialects.postgresql import UUID

from models.db import db


class CashInfo(db.Model):
    """Per-currency catalog of cash denominations.

    The source of truth for face values used by the cash count. Adding a
    denomination is an INSERT here — no schema change, no code change.
    Entities pick which of these they log via EntityCashSetting.

    Keyed on currency_id, not country: a face value is a property of the
    currency, so two countries sharing one would otherwise duplicate rows.
    country_code is retained only until the v3 cutover drops it.
    """

    __tablename__ = "cash_info"
    __table_args__ = {"schema": "pettycashv2"}
    cash_id = db.Column(db.Integer, primary_key=True)
    currency_id = db.Column(
        UUID(as_uuid=False), db.ForeignKey("pettycashv2.currency_info.id")
    )
    # Legacy. Superseded by currency_id; dropped with the v3 schema.
    country_code = db.Column(
        db.String(3), db.ForeignKey("pettycashv2.country_info.country_code")
    )
    # 'note' | 'coin'
    type = db.Column(db.String(10))
    cash_value = db.Column(db.Numeric(12, 2))
    cash_name = db.Column(db.String(10))
    # v3 renames this to `description`; `desc` is a reserved word.
    desc = db.Column(db.Text)
    display_order = db.Column(db.Integer, nullable=False, default=999)
    # Retires a denomination without deleting the historical counts that
    # reference it (report_cash_count.cash_id is ON DELETE RESTRICT).
    is_active = db.Column(db.Boolean, nullable=False, default=True)
