import uuid

from models.db import db


class CurrencyInfo(db.Model):
    __tablename__ = "currency_info"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    currency_name = db.Column(db.String(100), nullable=False)
    currency_code = db.Column(db.String(10), nullable=False, unique=True)
    symbol = db.Column(db.String(10), server_default="")
    decimal_places = db.Column(db.Integer, default=2)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.TIMESTAMP(timezone=True))
    updated_at = db.Column(db.TIMESTAMP(timezone=True))
    country_info = db.relationship("CountryInfo", backref="currency_info", lazy=True)
