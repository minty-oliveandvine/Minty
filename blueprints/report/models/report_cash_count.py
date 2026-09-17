import uuid

from models.db import db


class ReportCashCount(db.Model):
    """One counted denomination on one report.

    The cash-count equivalent of ReportSaleDetail: replaces the nine fixed
    note/coin columns that used to live on report_cashcount_draft (dropped in
    r10a10).
    """

    __tablename__ = "report_cash_count"
    __table_args__ = (
        db.UniqueConstraint("report_id", "cash_id", name="report_cash_count_uq"),
        db.CheckConstraint("quantity >= 0", name="chk_rcc_qty"),
        {"schema": "pettycashv3"},
    )
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Re-pointed at report.id in r8a08. It referenced report_draft.id, which
    # r6a06 missed — and once Step 2 stopped creating draft rows, inserting a
    # cash count for any new report violated that FK. The value never changed:
    # a report and its draft share one id.
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv3.report.id", ondelete="CASCADE"),
        nullable=False,
    )
    cash_id = db.Column(
        db.Integer,
        db.ForeignKey("pettycashv3.cash_info.cash_id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity = db.Column(db.Integer, nullable=False, default=0)
    # Face value as at the time of counting, so a later revaluation cannot
    # retroactively change what a historical report totalled to.
    cash_value = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(
        db.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
    cash_info = db.relationship("CashInfo", lazy="joined")
