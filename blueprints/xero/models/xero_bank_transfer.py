"""A bank transfer pushed to Xero for a report's deposit (``xero_bank_transfer``).

Same standing as ``xero_bank_transaction``: not written by today's publish flow, carried by
the loader. ``sync_report_id`` is NOT NULL and goes with the report (schema); money is
``numeric``, ``transfer_date`` is timestamptz, and the row has stamps (schema item 22).
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid, Money
from models.db import db


class XeroBankTransfer(db.Model):
    __tablename__ = "xero_bank_transfer"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    sync_report_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.report.id", ondelete="CASCADE"), nullable=False,
    )
    from_bank_account_id = db.Column(db.String(36), nullable=False)
    to_bank_account_id = db.Column(db.String(36), nullable=False)
    amount = db.Column(Money(), nullable=False)
    transfer_date = db.Column(db.DateTime(timezone=True), nullable=False)
    xero_bank_transfer_id = db.Column(db.String(36), nullable=False)
    from_bank_transaction_id = db.Column(db.String(36), nullable=False)
    to_bank_transaction_id = db.Column(db.String(36), nullable=False)
    status = db.Column(db.String(10))
    error_message = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
