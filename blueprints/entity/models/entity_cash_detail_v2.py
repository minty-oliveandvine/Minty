from models.db import db


class EntityCashDetailV2(db.Model):
    __tablename__ = "entity_cash_detail_v2"
    __table_args__ = {"schema": "pettycashv2"}
    entity_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"), primary_key=True
    )
    cash_id = db.Column(
        db.Integer, db.ForeignKey("pettycashv2.cash_info.cash_id"), primary_key=True
    )
    cash_type = db.Column(db.String(30))
    cash_instock = db.Column(db.Float)
    desc = db.Column(db.Text)
    cash_info = db.relationship("CashInfo", backref="entity_cash_detail_v2", lazy=True)
