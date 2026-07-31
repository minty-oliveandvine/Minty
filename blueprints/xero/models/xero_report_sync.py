from uuid import uuid4

from models.db import db


class XeroReportSync(db.Model):
    __tablename__ = "xero_report_sync"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    # Re-pointed at report.id in r4a04 (Stage 3); formerly report_v2.report_id.
    # update_xero_report_sync() already passes the posted Report.id, so the
    # value was always correct — only the parent it is checked against changed.
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sync_statuc = db.Column(db.String(20))
    reported_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    xero_reponse_text = db.Column(db.Text)
