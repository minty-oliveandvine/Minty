import uuid

from sqlalchemy.dialects.postgresql import INET

from models.db import db


class ConsentRecord(db.Model):
    """A captured consent of a principal against a terms version."""

    __tablename__ = "consent_record"
    __table_args__ = {"schema": "pettycashv2"}

    record_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    principal_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "pettycashv2.terms_user_principal.principal_id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    # RESTRICT: a terms version with consents recorded against it must not be
    # deleted.
    terms_ver_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.terms_version.terms_ver_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(
        db.TIMESTAMP(timezone=True),
        server_default=db.func.current_timestamp(),
        nullable=False,
    )
    captured_ip = db.Column(INET, nullable=False)
    captured_ua = db.Column(db.Text, nullable=False)
    capture_method = db.Column(db.Text, nullable=False)
    record_hash = db.Column(db.LargeBinary, nullable=False)

    principal = db.relationship("TermsUserPrincipal", backref="consent_records")
    terms_version = db.relationship("TermsVersion", backref="consent_records")
