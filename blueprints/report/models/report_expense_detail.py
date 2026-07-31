from uuid import uuid4

from models.db import db


class ReportExpenseDetail(db.Model):
    __tablename__ = "report_expense_detail"
    __table_args__ = {"schema": "pettycashv2"}
    expense_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # Re-pointed at report.id in r4a04 (Stage 3) — see report_sale_detail.
    report_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.report.id", ondelete="CASCADE")
    )
    account_id = db.Column(db.String(36), nullable=False)
    amount = db.Column(db.Float)
    info_filepath = db.Column(db.Text)
    description = db.Column(db.Text)
    create_at = db.Column(db.DateTime)

