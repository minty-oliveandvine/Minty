from uuid import uuid4

from models.db import db


class XeroReportSync(db.Model):
    __tablename__ = "xero_report_sync"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    # Re-pointed at report.id in r4a04 (Stage 3); formerly report_v2.report_id.
    #
    # Reshaped in r9a09 (Step 4d): this was part of a composite PK, which is
    # the only reason r4a04 had to use CASCADE — a PK column cannot be SET
    # NULL. `id` is now the sole PK, so deleting a report nulls this column
    # instead of deleting the row. That matters because this table is the
    # audit trail that detects a double-publish to Xero.
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv3.report.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_statuc = db.Column(db.String(20))
    reported_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    xero_reponse_text = db.Column(db.Text)
