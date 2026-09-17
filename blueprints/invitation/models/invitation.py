"""A team invite (``invitation``; was ``invitations``).

``status`` is the ``invitation_status`` enum (``cancelled`` is ``revoked`` now), ``role`` the
``entity_role`` enum the membership will carry, the ids uuids and the stamps timestamptz.
"""
import uuid

from blueprints.shared.column_types import MintyUuid, pg_enum
from blueprints.shared.enums import EntityRole, InvitationStatus
from models.db import db


class Invitation(db.Model):
    __tablename__ = "invitation"
    __table_args__ = (
        db.UniqueConstraint("token", name="invitation_token_key"),
        {"schema": "pettycashv3"},
    )

    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        MintyUuid(),
        db.ForeignKey("pettycashv3.entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = db.Column(db.String(150), nullable=False)
    role = db.Column(pg_enum(EntityRole), nullable=False)
    # Invitee's name captured at invite time. Persisted so the pending-invite
    # cards (onboarding Step 8 + Settings -> Users) keep the name/email/role
    # format on resume. Nullable for legacy rows.
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    token = db.Column(db.String(64), nullable=False)
    status = db.Column(pg_enum(InvitationStatus), nullable=False, default=InvitationStatus.PENDING)
    invited_by = db.Column(
        MintyUuid(),
        db.ForeignKey("pettycashv3.user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    accepted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # When the invite lapses. Set at creation to created_at + INVITATION_TTL_DAYS.
    # NULL = legacy row, never expires.
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    entity = db.relationship("Entity", backref="invitations", lazy=True)
    inviter = db.relationship("User", foreign_keys=[invited_by], lazy=True)
