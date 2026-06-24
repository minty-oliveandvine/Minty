"""Entity function models for per-entity module enablement."""
from models.db import db


class EntityFunction(db.Model):
    """Defines available functions/modules that can be enabled per entity."""
    __tablename__ = "entity_function"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True)
    function_code = db.Column(db.String(100), unique=True, nullable=False)
    function_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default="")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True))
    updated_at = db.Column(db.DateTime(timezone=True))

    def __repr__(self):
        return f"<EntityFunction {self.function_code}>"


class EntityFunctionMap(db.Model):
    """Maps entities to enabled functions/modules."""
    __tablename__ = "entity_function_map"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True)
    entity_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.entities.id"), nullable=False, index=True)
    entity_function_id = db.Column(db.String(36), db.ForeignKey("pettycashv2.entity_function.id"), nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    enabled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    disabled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    settings_json = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.String(36), default="", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True))
    updated_at = db.Column(db.DateTime(timezone=True))

    entity_function = db.relationship("EntityFunction", backref="entity_mappings")

    def __repr__(self):
        return f"<EntityFunctionMap {self.entity_id} -> {self.entity_function_id}>"
