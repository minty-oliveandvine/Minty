"""Which permissions a role holds (``role_permission``; was ``role_permissions``).

The schema's key is ``(role_id, permission_id)`` - no ``id``, no stamps.
"""
from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class RolePermissions(db.Model):
    __tablename__ = "role_permission"
    __table_args__ = {"schema": SCHEMA}
    role_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.role.id", ondelete="CASCADE"), primary_key=True,
    )
    permission_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.permission.id", ondelete="CASCADE"), primary_key=True,
    )


RolePermission = RolePermissions
