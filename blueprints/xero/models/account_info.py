from uuid import uuid4

from models.db import db


class AccountInfo(db.Model):
    __tablename__ = "account_info"
    __table_args__ = (
        db.UniqueConstraint(
            "entity_id",
            "xero_account_id",
            name="uq_account_info_entity_xero_account",
        ),
        {"schema": "pettycashv2"},
    )
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"))
    type = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    xero_account_id = db.Column(db.String(36))
    xero_code = db.Column(db.String(50))
    status = db.Column(db.String(50), default="ACTIVE")
    class_type = db.Column(db.String(50))
    bank_account_number = db.Column(db.String(50))
    bank_account_type = db.Column(db.String(50))
    description = db.Column(db.String(255))
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    entity_account_xero = db.relationship(
        "EntityAccountXero", cascade="all, delete-orphan", backref="account", lazy=True
    )

