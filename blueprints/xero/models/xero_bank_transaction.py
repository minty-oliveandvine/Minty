"""A bank transaction pushed to Xero for a report (``xero_bank_transaction``).

Nothing in the publish flow writes this table today (the publish record on
``xero_report_sync`` is what the republish reads); the loader carried production's rows and
``/insert_xero_transaction`` still inserts a fixture row. Money is ``numeric`` and the ids
uuids since C5; ``create_at`` became ``created_at``.
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid, Money
from models.db import db


class XeroBankTransaction(db.Model):
    __tablename__ = "xero_bank_transaction"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    sync_report_id = db.Column(MintyUuid(), db.ForeignKey("pettycashv3.report.id", ondelete="CASCADE"))
    type = db.Column(db.String(10), nullable=False)
    xero_contact_id = db.Column(db.String(36), nullable=False)
    xero_contact_name = db.Column(db.String(100))
    unit_amount = db.Column(Money(), nullable=False)
    quantity = db.Column(Money(12, 2), nullable=False)
    xero_account_id = db.Column(db.String(36), nullable=False)
    xero_account_code = db.Column(db.String(10))
    description = db.Column(db.Text)
    xero_bank_account_id = db.Column(db.String(36), nullable=False)
    xero_bank_transaction_id = db.Column(db.String(36), nullable=False)
    subtotal = db.Column(Money())
    total_tax = db.Column(Money())
    total = db.Column(Money())
    status = db.Column(db.String(10))
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
