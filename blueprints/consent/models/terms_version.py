import uuid

from models.db import db


class TermsVersion(db.Model):
    """A published version of a terms-of-service document.

    ``superseded_at`` is NULL while the version is current/active; it is set
    when a newer version replaces it.
    """

    __tablename__ = "terms_version"
    __table_args__ = {"schema": "pettycashv2"}

    terms_ver_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    doc_url = db.Column(db.Text, nullable=False)
    ver_label = db.Column(db.Text, nullable=False)
    jurisdiction = db.Column(db.Text, nullable=False)
    content_text = db.Column(db.Text, nullable=False)
    published_at = db.Column(
        db.TIMESTAMP(timezone=True),
        server_default=db.func.current_timestamp(),
        nullable=False,
    )
    superseded_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)
