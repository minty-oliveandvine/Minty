from models.db import db


class CashInfo(db.Model):
    """Per-country catalog of cash denominations.

    The source of truth for face values used by the cash count. Adding a
    denomination is an INSERT here — no schema change, no code change.
    Entities pick which of these they log via EntityCashDenomination.
    """

    __tablename__ = "cash_info"
    __table_args__ = {"schema": "pettycashv2"}
    cash_id = db.Column(db.Integer, primary_key=True)
    country_code = db.Column(
        db.CHAR(2), db.ForeignKey("pettycashv2.country_info.country_code")
    )
    # 'note' | 'coin'
    type = db.Column(db.String(10))
    cash_value = db.Column(db.Float)
    cash_name = db.Column(db.String(10))
    desc = db.Column(db.Text)
    display_order = db.Column(db.Integer, nullable=False, default=999)
    # Retires a denomination without deleting the historical counts that
    # reference it.
    is_active = db.Column(db.Boolean, nullable=False, default=True)
