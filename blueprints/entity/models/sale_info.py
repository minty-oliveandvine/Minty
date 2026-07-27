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
    # Catalog link — the EntityFunctionMap-style pointer at SalesMethod.
    # Nullable during the transition; `value_name` remains the legacy key until
    # every read has moved over. RESTRICT on the DB side: a catalog row in
    # active use must be deactivated (is_active = False), never deleted.
    sales_method_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.sales_method.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sales_method = db.relationship("SalesMethod", lazy="joined")
    create_date = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(tz), onupdate=lambda: datetime.now(tz)
    )
    display_order = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
