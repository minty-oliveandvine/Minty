import uuid

from blueprints.shared.enums import EntityRole
from models.db import db
from blueprints.shared.column_types import MintyUuid


class UserEntity(db.Model):
    __tablename__ = "user_entity"
    __table_args__ = {"schema": "pettycashv3"}
    user_id = db.Column(
        MintyUuid(),
        db.ForeignKey("pettycashv3.user.id", ondelete="CASCADE"),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    entity_id = db.Column(
        MintyUuid(),
        db.ForeignKey("pettycashv3.entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = db.Column(
        db.Enum(EntityRole, name="entity_role", schema="pettycashv3", native_enum=True,
                create_type=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp(), nullable=False)
    approved = db.Column(db.Boolean, default=True, nullable=False)
    joined_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    entity = db.relationship("Entity", backref="user_entity", lazy=True)
    user = db.relationship("User", backref="user_entity", lazy=True)
