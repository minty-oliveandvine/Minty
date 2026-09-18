"""The permission catalogue (``permission``; was ``permissions``).

``code`` is new in the schema (NOT NULL, unique) - the loader filled it from ``name`` and the
model does the same for a row created without one.
"""
import uuid

from sqlalchemy import event

from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class Permissions(db.Model):
    __tablename__ = "permission"
    __table_args__ = (
        db.UniqueConstraint("code", name="permission_code_key"),
        {"schema": SCHEMA},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


@event.listens_for(Permissions, "before_insert")
def _code_defaults_to_name(mapper, connection, target):
    if not target.code:
        target.code = target.name


Permission = Permissions
