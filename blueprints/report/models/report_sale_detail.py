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
    # Catalog link, denormalized on purpose. Resolving the method via
    # sale_id -> sale_info breaks for historical reports: ending.py outer-joins
    # SaleInfo "to include deleted/disabled sale types", so once an entity
    # removes a method the amount survives with no way to tell what it was for.
    # Carrying the catalog id here keeps every report self-describing.
    sales_method_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.sales_method.id", ondelete="RESTRICT"),
        nullable=True,
    )
    type = db.Column(db.String(50))
    amount = db.Column(db.Float)
    create_at = db.Column(db.DateTime)
    report_v2 = db.relationship("ReportV2", backref="report_sale_detail", lazy=True)
    sale_info = db.relationship("SaleInfo", backref="report_sale_detail", lazy=True)
    sales_method = db.relationship("SalesMethod", lazy="joined")

