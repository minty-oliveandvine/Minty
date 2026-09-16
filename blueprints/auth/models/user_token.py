import uuid

from models.db import db


class UserToken(db.Model):
    """OAuth tokens (Xero) for a User, stored in a dedicated table.

    One row per user (``user_id`` is UNIQUE). Splitting this out of ``user``
    keeps refresh churn off the user row and lets us treat tokens as a
    self-contained record with its own ``created_at`` / ``updated_at``.
    """

    __tablename__ = "user_token"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.Uuid(as_uuid=False),
        db.ForeignKey("pettycashv2.user.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    access_token = db.Column(db.Text, nullable=True)
    access_token_obtained_at = db.Column(db.DateTime(timezone=True), nullable=True)
    access_token_expires_in = db.Column(db.Integer, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    id_token = db.Column(db.Text, nullable=True)
    refresh_token_last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(), nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
        nullable=False,
    )

    user = db.relationship(
        "User", backref=db.backref("user_token", uselist=False, lazy="joined")
    )
