import uuid

from blueprints.shared.column_types import MintyUuid, Money
from models.db import db


class ReportCashCount(db.Model):
    """One counted denomination on one report (``report_cash_count``)."""

    __tablename__ = "report_cash_count"
    __table_args__ = (
        db.UniqueConstraint("report_id", "cash_id", name="report_cash_count_uq"),
        db.CheckConstraint("quantity >= 0", name="chk_rcc_qty"),
        {"schema": "pettycashv3"},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.report.id", ondelete="CASCADE"), nullable=False,
    )
    cash_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.cash_info.id", ondelete="RESTRICT"), nullable=False,
    )
    quantity = db.Column(db.Integer, nullable=False, default=0)
    cash_value = db.Column(Money(12, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now(), onupdate=db.func.now(),
    )
    cash_info = db.relationship("CashInfo", lazy="joined")
