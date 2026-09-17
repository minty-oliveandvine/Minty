"""Which synced accounts a company's petty-cash publish may use (``entity_account_xero``).

``id`` alone is the key since C5 (the model used to declare ``account_id`` as a second
primary-key column, which the table never had).
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid
from models.db import db


class EntityAccountXero(db.Model):
    __tablename__ = "entity_account_xero"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    account_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.account_info.id", ondelete="CASCADE"), nullable=False,
    )
    name = db.Column(db.String(80))
    type = db.Column(db.String(50))
    xero_org_id = db.Column(db.String(36))
    xero_account_id = db.Column(db.String(36))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
