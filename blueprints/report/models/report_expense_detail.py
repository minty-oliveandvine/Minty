from uuid import uuid4

from models.db import db


class ReportExpenseDetail(db.Model):
    __tablename__ = "report_expense_detail"
    __table_args__ = {"schema": "pettycashv2"}
    expense_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid4())
    )
    report_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.report_v2.report_id", ondelete="CASCADE")
    )
    account_id = db.Column(db.String(36), nullable=False)
    amount = db.Column(db.Float)
    info_filepath = db.Column(db.Text)
    description = db.Column(db.Text)
    create_at = db.Column(db.DateTime)
    report_v2 = db.relationship("ReportV2", backref="report_expense_detail", lazy=True)

