import uuid
from datetime import datetime, timezone

from models.db import db


class EmailOtp(db.Model):
    __tablename__ = "email_otp"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(100), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
