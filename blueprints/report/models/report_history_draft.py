from datetime import datetime

from models.db import db


class ReportHistoryDraft(db.Model):
    __tablename__ = "report_history_draft"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.Integer, primary_key=True)
    report_draft_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.report.id", ondelete="CASCADE"),
        nullable=False,
    )
    company = db.Column(db.String(150), nullable=False, index=True)
    user_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.user.id", ondelete="SET NULL")
    )
    action = db.Column(db.String(50), nullable=False)
    field_changed = db.Column(db.String(255), nullable=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User", back_populates="report_history_drafts")
    # FK re-pointed at report.id in r6a06.
    report_draft = db.relationship("Report", lazy=True)
