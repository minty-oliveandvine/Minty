from uuid import uuid4

from models.db import db


class ReportSaleDetail(db.Model):
    __tablename__ = "report_sale_detail"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    sale_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.sale_info.sale_id", ondelete="CASCADE"))
    report_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.report_v2.report_id", ondelete="CASCADE")
    )
    type = db.Column(db.String(50))
    amount = db.Column(db.Float)
    create_at = db.Column(db.DateTime)
    report_v2 = db.relationship("ReportV2", backref="report_sale_detail", lazy=True)
    sale_info = db.relationship("SaleInfo", backref="report_sale_detail", lazy=True)

