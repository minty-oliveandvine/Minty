from models.db import db


class CashInfo(db.Model):
    __tablename__ = "cash_info"
    __table_args__ = {"schema": "pettycashv2"}
    cash_id = db.Column(db.Integer, primary_key=True)
    country_code = db.Column(
        db.String(3), db.ForeignKey("pettycashv2.country_info.country_code")
    )
    type = db.Column(db.String(10))
    cash_value = db.Column(db.Float)
    cash_name = db.Column(db.String(10))
    desc = db.Column(db.Text)
