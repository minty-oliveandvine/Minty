"""One sales-method amount on one report: ``report_sale`` in the rebased schema.

Was ``ReportSaleDetail`` / ``report_sale_detail``; the old class name stays importable.
``sale_id`` is the catalogue row (``sale_info``), which since C3 is also what the company's
link carries - so a report stays self-describing after the company switches a method off.
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid, Money
from models.db import db


class ReportSale(db.Model):
    __tablename__ = "report_sale"
    __table_args__ = (
        db.UniqueConstraint("report_id", "sale_id", name="report_sale_report_sale_key"),
        {"schema": "pettycashv3"},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    report_id = db.Column(MintyUuid(), db.ForeignKey("pettycashv3.report.id", ondelete="CASCADE"), nullable=False)
    sale_id = db.Column(MintyUuid(), db.ForeignKey("pettycashv3.sale_info.id", ondelete="RESTRICT"), nullable=False)
    amount = db.Column(Money(), nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())

    method = db.relationship("SaleInfo", foreign_keys=[sale_id], lazy="joined")

    # pre-C4 names
    @property
    def sale_info(self):
        return self.method

    @property
    def sale_info_id(self):
        return self.sale_id

    @property
    def type(self):
        return self.method.type if self.method is not None else None

    @property
    def create_at(self):
        return self.created_at


ReportSaleDetail = ReportSale
