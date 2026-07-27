import uuid

from models.db import db


class ReportCashCountDetail(db.Model):
    """One counted denomination on one report.

    The cash-count equivalent of ReportSaleDetail: replaces the nine fixed
    note/coin columns on ReportCashCountDraft, which are kept as a fallback
    for rows predating the backfill.
    """

    __tablename__ = "report_cashcount_detail"
    __table_args__ = (
        db.UniqueConstraint(
            "report_id", "cash_id", name="uq_cashcount_detail_report_cash"
        ),
        {"schema": "pettycashv2"},
    )
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report_draft.id", ondelete="CASCADE"),
        nullable=False,
    )
    cash_id = db.Column(
        db.Integer,
        db.ForeignKey("pettycashv2.cash_info.cash_id", ondelete="RESTRICT"),
        nullable=False,
    )
    count = db.Column(db.Integer, nullable=False, default=0)
    # Face value as at the time of counting, so a later revaluation cannot
    # retroactively change what a historical report totalled to.
    cash_value = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
    cash_info = db.relationship("CashInfo", lazy="joined")
