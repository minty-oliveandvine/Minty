from models.db import db


class ReportDetail(db.Model):
    __tablename__ = "report_detail"
    __table_args__ = {"schema": "pettycashv2"}
    report_id = db.Column(db.String(36), primary_key=True)
    entity_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"), primary_key=True
    )
    opening_balance = db.Column(db.Float)
    adjusted_opening_balance = db.Column(db.Float)
    nocashsale_total = db.Column(db.Float)
    cashsale_total = db.Column(db.Float)
    expense_total = db.Column(db.Float)
    discrepancy_amount = db.Column(db.Float, default=0.0)
    discrepancy_description = db.Column(db.Text)
