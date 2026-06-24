from uuid import uuid4

from models.db import db


class XeroContactSync(db.Model):
    __tablename__ = "xero_contact_sync"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"))
    xero_contact_id = db.Column(db.String(36), nullable=False)
    xero_org_id = db.Column(db.String(36))
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50))

