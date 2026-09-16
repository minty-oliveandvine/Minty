import uuid

from sqlalchemy.dialects.postgresql import UUID

from models.db import db


class CurrencyInfo(db.Model):
    """Mirror of pettycashv2.currency_info.

    id is a uuid primary key (gen_random_uuid() server-side); currency_code
    carries the 3-letter ISO 4217 code and is unique.
    """

    __tablename__ = "currency_info"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    currency_code = db.Column(db.CHAR(3), unique=True, nullable=False)
    currency_name = db.Column(db.String(100), nullable=False)
    symbol = db.Column(db.String(10), nullable=False, default="")
    decimal_places = db.Column(db.SmallInteger, nullable=False, default=2)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=db.func.current_timestamp(),
    )
