from uuid import uuid4

from models.db import db


class ShopExpense(db.Model):
    __tablename__ = "shop_expense"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    report_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.report.id"), nullable=False
    )
    item = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.String(300), nullable=True)
    files = db.Column(db.Text)
    s3_key = db.Column(db.String(255), nullable=True)
    contact_id = db.Column(db.String(36), nullable=True)
    contact_name = db.Column(db.String(150), nullable=True)
    account_id = db.Column(db.String(36), nullable=True)
    account_code = db.Column(db.String(20), nullable=True)
    item_code = db.Column(db.String(20), nullable=True)

