from uuid import uuid4

from models.db import db


class XeroBankTransfer(db.Model):
    __tablename__ = "xero_bank_transfer"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    # Re-pointed at report.id in r4a04 (Stage 3). See xero_report_sync.
    sync_report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report.id", ondelete="CASCADE"),
        primary_key=True,
    )
    from_bank_account_id = db.Column(db.String(36), nullable=False)
    to_bank_account_id = db.Column(db.String(36), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transfer_date = db.Column(db.DateTime, nullable=False)
    xero_bank_transfer_id = db.Column(db.String(36), nullable=False)
    from_bank_transaction_id = db.Column(db.String(36), nullable=False)
    to_bank_transaction_id = db.Column(db.String(36), nullable=False)
    status = db.Column(db.String(10))
    error_message = db.Column(db.Text)
