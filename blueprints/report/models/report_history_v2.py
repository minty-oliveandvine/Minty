from uuid import uuid4

from models.db import db


class ReportHistoryV2(db.Model):
    __tablename__ = "report_history_v2"
    __table_args__ = {"schema": "pettycashv2"}
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report_v2.report_id", ondelete="CASCADE"),
        primary_key=True,
    )
    history_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    emp_id = db.Column(db.String(36))
    create_date = db.Column(db.DateTime)
    opening_balance = db.Column(db.Float)
    adjusted_opening_balance = db.Column(db.Float)
    sale_amount = db.Column(db.Float)
    expense_amount = db.Column(db.Float)
    withdraw_amount = db.Column(db.Float)
    status = db.Column(db.String(20))
    xero_organiztion_id = db.Column(db.String(36))
    report_v2 = db.relationship("ReportV2", backref="report_history_v2", lazy=True)
