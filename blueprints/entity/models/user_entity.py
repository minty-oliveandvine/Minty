import uuid

from models.db import db


class UserEntity(db.Model):
    __tablename__ = "user_entity"
    __table_args__ = {"schema": "pettycashv2"}
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id", ondelete="CASCADE"),
        primary_key=True,
        default=str(uuid.uuid4()),
    )
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = db.Column(db.String(20), nullable=False)
    create_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    approved = db.Column(db.Boolean, default=True)
    joined_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    entity = db.relationship("Entity", backref="user_entity", lazy=True)
    user = db.relationship("User", backref="user_entity", lazy=True)
