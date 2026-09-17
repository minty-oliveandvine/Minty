"""The role catalogue (``role``; was ``roles``). The class keeps its old name."""
import uuid

from blueprints.shared.column_types import MintyUuid
from models.db import db


class Roles(db.Model):
    __tablename__ = "role"
    __table_args__ = (
        db.UniqueConstraint("name", name="role_name_key"),
        {"schema": "pettycashv3"},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


Role = Roles
