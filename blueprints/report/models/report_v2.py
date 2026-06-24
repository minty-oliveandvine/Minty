from uuid import uuid4

from models.db import db


class ReportV2(db.Model):
    __tablename__ = "report_v2"
    __table_args__ = {"schema": "pettycashv2"}
    report_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid4())
    )
    entity_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"))
    report_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    starting_balance = db.Column(db.Float)
    add_cash_amount = db.Column(db.Float)
    cash_from_type = db.Column(db.String(10))
    add_cash_bank_account_id = db.Column(db.String(36))
    opening_balance = db.Column(db.Float)
    adjusted_opening_balance = db.Column(db.Float)
    xero_organiztion_id = db.Column(db.String(36))
    cashsale_total = db.Column(db.Float)
    nocashsale_total = db.Column(db.Float)
    cash_deposit = db.Column(db.Float)
    expense_total = db.Column(db.Float)

