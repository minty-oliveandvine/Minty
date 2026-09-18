"""Who did what to a report: ``report_history`` in the rebased schema.

Lost ``company`` (the report knows its company) and ``timestamp`` (-> ``created_at``, kept
as a synonym so ``ReportHistory.timestamp`` still orders a query).
"""
import uuid

from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class ReportHistory(db.Model):
    __tablename__ = "report_history"
    __table_args__ = {"schema": SCHEMA}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.report.id", ondelete="CASCADE"), nullable=False,
    )
    user_id = db.Column(MintyUuid(), db.ForeignKey(f"{SCHEMA}.user.id", ondelete="SET NULL"))
    action = db.Column(db.String(50), nullable=False)
    field_changed = db.Column(db.String(255), nullable=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp(), nullable=False)
    timestamp = synonym("created_at")
    user = db.relationship("User", back_populates="report_histories")
    report = db.relationship("Report", back_populates="report_histories")

    @property
    def company(self):
        return self.report.entity_id if self.report is not None else None
