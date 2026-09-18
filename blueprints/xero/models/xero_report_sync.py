"""What a report's Xero publish created (``xero_report_sync``): one row per report.

``xero_response_text`` holds the publish record (``xero/services/publish_record.py``) - the
Xero object ids per module, so a republish updates rather than duplicates. Schema 2.43 fixed
the two typos (``sync_statuc``, ``xero_reponse_text``), made ``report_id`` NOT NULL + UNIQUE
and put it ON DELETE CASCADE: the record goes with the report (the r9a09 SET NULL "audit
trail survives the report" is gone - schema item 22 gave the row stamps instead).
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class XeroReportSync(db.Model):
    __tablename__ = "xero_report_sync"
    __table_args__ = (
        db.UniqueConstraint("report_id", name="xero_report_sync_report_key"),
        {"schema": SCHEMA},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    report_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.report.id", ondelete="CASCADE"), nullable=False,
    )
    sync_status = db.Column(db.String(20))
    reported_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    xero_response_text = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
