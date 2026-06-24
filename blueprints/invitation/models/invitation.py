import uuid

from models.db import db


class Invitation(db.Model):
    __tablename__ = "invitations"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    invited_by = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    accepted_at = db.Column(db.TIMESTAMP, nullable=True)
    # When the invite lapses (Hong Kong time). Set at creation to
    # created_at + INVITATION_TTL_DAYS. NULL = legacy row, never expires.
    expires_at = db.Column(db.TIMESTAMP, nullable=True)

    entity = db.relationship("Entity", backref="invitations", lazy=True)
    inviter = db.relationship("User", foreign_keys=[invited_by], lazy=True)
