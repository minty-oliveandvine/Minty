from models.db import db


class CountryInfo(db.Model):
    __tablename__ = "country_info"
    __table_args__ = {"schema": "pettycashv2"}
    country_code = db.Column(db.String(3), primary_key=True, nullable=False)
    country_name_en = db.Column(db.String(50), nullable=False)
    country_name_ko = db.Column(db.String(50))
    currency_id = db.Column(
        db.String(10), db.ForeignKey("pettycashv2.currency_info.currency_code")
    )
    cash_info = db.relationship("CashInfo", backref="country_info", lazy=True)
