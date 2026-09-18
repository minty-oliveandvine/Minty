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
from blueprints.shared.enums import SystemRole
from models.db import db, tz
from blueprints.shared.column_types import MintyUuid
from blueprints.shared.schema import SCHEMA


class User(UserMixin, db.Model):
    """A person. Matches ``user`` in docs/schema/01_schema_rebased.sql.

    The Xero OAuth bundle lives in ``user_token`` (one row per person, see
    ``UserToken``); the six token columns this table used to carry are gone. The
    attributes ``access_token``, ``refresh_token``, ``id_token``, ``expires_in`` and
    ``token_created_at`` remain as *properties over that row*, so the code that reads
    ``user.access_token`` keeps working and every write lands in ``user_token``.

    Also gone (schema items 14 and 19): ``xero_entity_id`` — which company a person
    connected is ``entities.connected_by_user_id`` now; ``current_entity_id`` — presence is
    a fact about the person (``signed_in_at`` / ``last_seen_at``), not about a company;
    ``xero_token`` — never read.
    """

    __tablename__ = "user"
    __table_args__ = {"schema": SCHEMA}
    SYSTEM_ROLE_NORMAL = USER_SYSTEM_ROLE_NORMAL
    SYSTEM_ROLE_SUPERUSER = USER_SYSTEM_ROLE_SUPERUSER
    SYSTEM_ROLE_DEFAULT = USER_SYSTEM_ROLE_DEFAULT
    SYSTEM_ROLE_VALUES = USER_SYSTEM_ROLE_VALUES
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
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
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
    username = db.Column(db.String(150), nullable=False, unique=True)
    system_role = db.Column(
        db.Enum(SystemRole, name="system_role", schema=SCHEMA, native_enum=True,
                create_type=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=USER_SYSTEM_ROLE_DEFAULT,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    approved = db.Column(db.Boolean, default=False)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime(timezone=True), nullable=True)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)
    report_histories = db.relationship("ReportHistory", back_populates="user")
    # Sign-in presence, read by Settings > Users (see services/user_presence.py).
    # `signed_in_at` is the intent — stamped at login, cleared at logout, from
    # either module. `last_seen_at` is the backstop for the browser that is simply
    # closed, which sends no logout at all and would otherwise leave the person
    # listed as signed in forever. Both facts are about the person: which company
    # they are standing in is not recorded (schema item 14 — Settings > Users
    # answers "who is signed in to Minty").
    signed_in_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # ---- the Xero token bundle, stored in user_token -------------------------------
    #
    # ``UserToken`` declares the relationship (backref ``user_token``, one row, joined).
    # Reads answer None when there is no row; the first write creates it. Writers
    # that used to clear the six columns one by one now go through ``clear_tokens``.

    def _token_row(self, create: bool = False):
        row = self.user_token
        if row is None and create:
            from blueprints.auth.models.user_token import UserToken

            row = UserToken(user_id=self.id)
            self.user_token = row
        return row

    @property
    def access_token(self):
        row = self._token_row()
        return row.access_token if row is not None else None

    @access_token.setter
    def access_token(self, value):
        row = self._token_row(create=True)
        row.access_token = value
        if value:
            row.access_token_obtained_at = datetime.now(tz)

    @property
    def refresh_token(self):
        row = self._token_row()
        return row.refresh_token if row is not None else None

    @refresh_token.setter
    def refresh_token(self, value):
        self._token_row(create=True).refresh_token = value

    @property
    def id_token(self):
        row = self._token_row()
        return row.id_token if row is not None else None

    @id_token.setter
    def id_token(self, value):
        self._token_row(create=True).id_token = value

    @property
    def expires_in(self):
        row = self._token_row()
        return row.access_token_expires_in if row is not None else None

    @expires_in.setter
    def expires_in(self, value):
        self._token_row(create=True).access_token_expires_in = int(value) if value is not None else None

    @property
    def token_created_at(self):
        """When the current access token was obtained (``user_token.access_token_obtained_at``)."""
        row = self._token_row()
        return row.access_token_obtained_at if row is not None else None

    @token_created_at.setter
    def token_created_at(self, value):
        self._token_row(create=True).access_token_obtained_at = value

    def clear_tokens(self) -> None:
        """Forget the Xero bundle (disconnect, deactivate). Keeps the row, empties it."""
        row = self._token_row()
        if row is None:
            return
        row.access_token = None
        row.access_token_obtained_at = None
        row.access_token_expires_in = None
        row.refresh_token = None
        row.id_token = None

    @property
    def has_xero_tokens(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    @classmethod
    def normalize_system_role(cls, system_role: str | None) -> str:
        return normalize_system_role(system_role)

    @classmethod
    def legacy_role_to_system_role(cls, role: str | None) -> str:
        return legacy_role_to_system_role(role)
