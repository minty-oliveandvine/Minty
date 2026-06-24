import uuid
from datetime import datetime

from models.db import db, tz


class SaleInfo(db.Model):
    __tablename__ = "sale_info"
    __table_args__ = {"schema": "pettycashv2"}
    sale_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"))
    type = db.Column(db.String(50))
    sale_name = db.Column(db.String(80))
    value_name = db.Column(db.String(80))
    create_date = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(tz), onupdate=lambda: datetime.now(tz)
    )
    display_order = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
