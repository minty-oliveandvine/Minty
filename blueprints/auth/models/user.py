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
    # report_history_drafts went with Step 4a-4 — log_history_draft was the
    # only writer and had no callers. Both sides of the back_populates pair
    # had to go together or mapper configuration fails.
    xero_token = db.Column(db.String(2048), nullable=True)
    access_token = db.Column(db.String(2048), nullable=True)
    refresh_token = db.Column(db.String(255), nullable=True)
    id_token = db.Column(db.String(2048), nullable=True)
    expires_in = db.Column(db.Integer, nullable=True)
    token_created_at = db.Column(
        db.TIMESTAMP, nullable=True, default=lambda: datetime.now(tz)
    )
    # Sign-in presence, read by Settings > Users (see services/user_presence.py).
    # `signed_in_at` is the intent — stamped at login, cleared at logout, from
    # either module. `last_seen_at` is the backstop for the browser that is simply
    # closed, which sends no logout at all and would otherwise leave the person
    # listed as signed in forever. Both are naive HK-local, matching every other
    # TIMESTAMP on this table.
    signed_in_at = db.Column(db.TIMESTAMP, nullable=True)
    last_seen_at = db.Column(db.TIMESTAMP, nullable=True)
    # WHICH company they are signed in to, which the two stamps above cannot say.
    # Those are facts about the person — signed in to Minty, seen recently — but
    # Settings > Users asks a question about a company: who is here, in THIS one.
    # Without this a person signed in to company A was listed as present in company
    # B as well, since nothing in the row distinguished them.
    #
    # Set when they open a company and cleared when they leave it or sign out (see
    # services/user_presence.py). NULL means signed in to Minty but not inside any
    # company — standing on the entity list, which is where every session begins.
    # Deliberately NOT a foreign key. ``entities.last_accessed_by_user_id`` already
    # points the other way, so a constraint here closes a cycle between the two
    # tables — SQLAlchemy cannot then sort them for create/drop and warns that it
    # may become an error. The reference is inert: it is only ever compared for
    # equality, never followed, so a row left pointing at a deleted company simply
    # matches nothing, and presence ages out within the hour regardless.
    current_entity_id = db.Column(db.String(36), nullable=True, index=True)

    @classmethod
    def normalize_system_role(cls, system_role: str | None) -> str:
        return normalize_system_role(system_role)

    @classmethod
    def legacy_role_to_system_role(cls, role: str | None) -> str:
        return legacy_role_to_system_role(role)
