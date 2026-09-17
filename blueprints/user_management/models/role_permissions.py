import uuid
from datetime import datetime

from models.db import db


class RolePermissions(db.Model):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    role_id = db.Column(db.String(36), db.ForeignKey("pettycashv3.roles.id"))
    permission_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv3.permissions.id")
    )
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
