from uuid import uuid4

from models.db import db


class EntityAccountXero(db.Model):
    __tablename__ = "entity_account_xero"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    account_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.account_info.id", ondelete="CASCADE"), primary_key=True
    )
    name = db.Column(db.String(80))
    type = db.Column(db.String(50))
    xero_org_id = db.Column(db.String(36))
    xero_account_id = db.Column(db.String(36))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

