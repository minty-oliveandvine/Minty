from uuid import uuid4

from models.db import db


class ReportCashCountDraft(db.Model):
    __tablename__ = "report_cashcount_draft"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report.id", ondelete="CASCADE"),
        nullable=False,
    )
    thousand_note = db.Column(db.Integer)
    fivehundred_note = db.Column(db.Integer)
    onehundred_note = db.Column(db.Integer)
    fifty_note = db.Column(db.Integer)
    twenty_note = db.Column(db.Integer)
    ten_note = db.Column(db.Integer)
    five_coin = db.Column(db.Integer)
    two_coin = db.Column(db.Integer)
    one_coin = db.Column(db.Integer)
    safe_box_balance = db.Column(db.Float)
    discrepancy_amount = db.Column(db.Float)
    discrepancy_reason = db.Column(db.String(300))
    discrepancy_type = db.Column(db.String(20), default="none")
    actual_cash_total = db.Column(db.Float)
    # FK re-pointed at report.id in r6a06.
    report_draft = db.relationship("Report", lazy=True)
