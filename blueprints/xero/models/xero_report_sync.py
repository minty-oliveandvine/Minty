from uuid import uuid4

from models.db import db


class XeroReportSync(db.Model):
    __tablename__ = "xero_report_sync"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    report_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report_v2.report_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sync_statuc = db.Column(db.String(20))
    reported_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    xero_reponse_text = db.Column(db.Text)
    report_v2 = db.relationship("ReportV2", backref="xero_report_sync", lazy=True)
