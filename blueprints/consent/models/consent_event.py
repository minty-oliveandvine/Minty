from models.db import db


class ConsentEvent(db.Model):
    """Append-only event log for a consent record."""

    __tablename__ = "consent_event"
    __table_args__ = {"schema": "pettycashv2"}

    event_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    record_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.consent_record.record_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_time = db.Column(db.TIMESTAMP(timezone=True), nullable=False)
    event_state = db.Column(db.Text, nullable=False)
    event_type = db.Column(db.Text, nullable=False)
    recorded_at = db.Column(
        db.TIMESTAMP(timezone=True),
        server_default=db.func.current_timestamp(),
        nullable=False,
    )

    record = db.relationship("ConsentRecord", backref="events")
