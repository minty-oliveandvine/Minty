import uuid
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import UUID

from blueprints.auth.system_roles import SYSTEM_ROLE_DEFAULT as USER_SYSTEM_ROLE_DEFAULT
from blueprints.auth.system_roles import SYSTEM_ROLE_NORMAL as USER_SYSTEM_ROLE_NORMAL
from blueprints.auth.system_roles import (
    SYSTEM_ROLE_SUPERUSER as USER_SYSTEM_ROLE_SUPERUSER,
)
from blueprints.auth.system_roles import SYSTEM_ROLE_VALUES as USER_SYSTEM_ROLE_VALUES
from blueprints.auth.system_roles import (
    legacy_role_to_system_role,
    normalize_system_role,
)
from models.db import db, tz


class User(UserMixin, db.Model):
    __tablename__ = "user"
    __table_args__ = {"schema": "pettycashv2"}
    SYSTEM_ROLE_NORMAL = USER_SYSTEM_ROLE_NORMAL
    SYSTEM_ROLE_SUPERUSER = USER_SYSTEM_ROLE_SUPERUSER
    SYSTEM_ROLE_DEFAULT = USER_SYSTEM_ROLE_DEFAULT
    SYSTEM_ROLE_VALUES = USER_SYSTEM_ROLE_VALUES
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(100), nullable=True, unique=True)
    # Xero-side identity (from the OAuth id_token email claim). Kept distinct
    # from `email` (the personal/OTP identity) so we can tell "same person"
    # (email == xero_email) from "two people" (different addresses).
    xero_email = db.Column(db.String(100), nullable=True, unique=True)
    password = db.Column(db.String(150), nullable=False)
    xero_user_id = db.Column(UUID(as_uuid=True), unique=True)
    first_name = db.Column(db.String(150), nullable=False)
    last_name = db.Column(db.String(150), nullable=False)
    user_phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    username = db.Column(db.String(150), nullable=False, unique=True)
    xero_entity_id = db.Column(db.String(36))
    system_role = db.Column(
        db.String(20), nullable=False, default=USER_SYSTEM_ROLE_DEFAULT
    )
    approved = db.Column(db.Boolean, default=False)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    report_histories = db.relationship("ReportHistory", back_populates="user")
    report_history_drafts = db.relationship("ReportHistoryDraft", back_populates="user")
    xero_token = db.Column(db.String(2048), nullable=True)
    access_token = db.Column(db.String(2048), nullable=True)
    refresh_token = db.Column(db.String(255), nullable=True)
    id_token = db.Column(db.String(2048), nullable=True)
    expires_in = db.Column(db.Integer, nullable=True)
    token_created_at = db.Column(
        db.TIMESTAMP, nullable=True, default=lambda: datetime.now(tz)
    )

    @classmethod
    def normalize_system_role(cls, system_role: str | None) -> str:
        return normalize_system_role(system_role)

    @classmethod
    def legacy_role_to_system_role(cls, role: str | None) -> str:
        return legacy_role_to_system_role(role)
