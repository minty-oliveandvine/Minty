from uuid import uuid4

from models.db import db


class XeroBankTransaction(db.Model):
    __tablename__ = "xero_bank_transaction"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    sync_report_id = db.Column(db.String(36))
    type = db.Column(db.String(10), nullable=False)
    xero_contact_id = db.Column(db.String(36), nullable=False)
    xero_contact_name = db.Column(db.String(100))
    unit_amount = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    xero_account_id = db.Column(db.String(36), nullable=False)
    xero_account_code = db.Column(db.String(10))
    description = db.Column(db.Text)
    xero_bank_account_id = db.Column(db.String(36), nullable=False)
    xero_bank_transaction_id = db.Column(db.String(36), nullable=False)
    subtotal = db.Column(db.Float)
    total_tax = db.Column(db.Float)
    total = db.Column(db.Float)
    status = db.Column(db.String(10))
    create_at = db.Column(db.DateTime)

