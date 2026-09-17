"""The module catalogue and the per-company module map.

Match ``entity_function`` / ``entity_function_map`` in docs/schema/01_schema_rebased.sql.
"""
import uuid

from sqlalchemy.dialects.postgresql import JSONB

from blueprints.shared.column_types import MintyUuid
from blueprints.shared.enums import ModuleCode
from models.db import db


class EntityFunction(db.Model):
    """The catalogue: one row per module Minty sells (``module_code``, item 20)."""
    __tablename__ = "entity_function"
    __table_args__ = {"schema": "pettycashv3"}

    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    function_code = db.Column(
        db.Enum(ModuleCode, name="module_code", schema="pettycashv3", native_enum=True,
                create_type=False, values_callable=lambda e: [m.value for m in e]),
        unique=True, nullable=False,
    )
    function_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=999)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    def __repr__(self):
        return f"<EntityFunction {self.function_code}>"


class EntityFunctionMap(db.Model):
    """Which modules a company has switched on.

    Keyed by ``(entity_id, entity_function_id)`` - there is no surrogate id. ``created_by``
    is the person who first wrote the row (schema section 4): a user id, or NULL when the
    CLI or a background job did it. The *reason* a row changed (onboarding, subscription
    sync, CLI) is not stored; ``services/modules._write_pairs`` still takes it as ``actor``
    because the paid-subscription guard keys on it.
    """
    __tablename__ = "entity_function_map"
    __table_args__ = {"schema": "pettycashv3"}

    entity_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_function_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.entity_function.id"), primary_key=True,
    )
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    settings_json = db.Column(db.JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    enabled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    disabled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.user.id", ondelete="SET NULL"), nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    entity_function = db.relationship("EntityFunction", backref="entity_mappings")

    def __repr__(self):
        return f"<EntityFunctionMap {self.entity_id} -> {self.entity_function_id}>"
