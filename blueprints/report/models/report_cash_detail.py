from models.db import db


class ReportCashDetail(db.Model):
    __tablename__ = "report_cash_detail"
    __table_args__ = {"schema": "pettycashv2"}
    cash_id = db.Column(
        db.Integer, db.ForeignKey("pettycashv2.cash_info.cash_id"), primary_key=True
    )
    report_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.report_v2.report_id", ondelete="CASCADE")
    )
    amount = db.Column(db.Float)
    create_at = db.Column(db.DateTime)
    count = db.Column(db.Float)
    report_v2 = db.relationship("ReportV2", backref="report_cash_detail", lazy=True)
    cash_info = db.relationship("CashInfo", backref="report_cash_detail", lazy=True)
