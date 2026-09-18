"""A Xero account synced for one company (``account_info``).

``(entity_id, xero_account_id)`` is unique - the constraint the chart-of-accounts sync
upserts on (``uq_account_entity_xero``). Since C5 the ids are uuids and the row carries
``updated_at``; ``ReportExpense.account`` and ``entity_pettycash_settings`` point here.
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class AccountInfo(db.Model):
    __tablename__ = "account_info"
    __table_args__ = (
        db.UniqueConstraint("entity_id", "xero_account_id", name="uq_account_entity_xero"),
        {"schema": SCHEMA},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    entity_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"), nullable=False,
    )
    type = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    xero_account_id = db.Column(db.String(36))
    xero_code = db.Column(db.String(50))
    status = db.Column(db.String(50), default="ACTIVE")
    class_type = db.Column(db.String(50))
    bank_account_number = db.Column(db.String(50))
    bank_account_type = db.Column(db.String(50))
    description = db.Column(db.String(255))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
    entity_account_xero = db.relationship(
        "EntityAccountXero", cascade="all, delete-orphan", backref="account", lazy=True
    )
