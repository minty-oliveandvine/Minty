from sqlalchemy.dialects.postgresql import UUID

from models.db import db
from blueprints.shared.schema import SCHEMA


class CountryInfo(db.Model):
    """Mirror of pettycashv3.country_info.

    country_code (ISO 3166-1 alpha-2) is the primary key; alpha3_code carries
    the alpha-3 code. currency_id links to the currency registry (ON DELETE
    SET NULL in the DB).
    """

    __tablename__ = "country_info"
    __table_args__ = {"schema": SCHEMA}
    country_code = db.Column(db.CHAR(2), primary_key=True)
    alpha3_code = db.Column(db.CHAR(3), nullable=False)
    country_name_en = db.Column(db.String(100), nullable=False)
    currency_id = db.Column(
        UUID(as_uuid=False), db.ForeignKey(f"{SCHEMA}.currency_info.id")
    )
    phone_code = db.Column(db.String(10))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=False, default=999)
    # cash_info is keyed on currency, not country (its country_code went with the redesign)
