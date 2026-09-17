"""Which sales methods a company uses: ``entity_sale_setting`` in the rebased schema.

A link from a company to a catalogue row (``SaleInfo``), keyed by ``(entity_id, sale_id)``,
carrying only what is per-company: on/off and the order on the sales page. The method's
name, type and form-field name live on the catalogue row and are read through here so the
code that said ``method.sale_name`` / ``method.type`` / ``method.value_name`` still does.

``sale_id`` is the catalogue id. The schema declares no FK for it (the pre-redesign data
minted its own ids here); the model does, so SQLite tests get the constraint too.
"""
from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid
from models.db import db


class EntitySaleSetting(db.Model):
    __tablename__ = "entity_sale_setting"
    __table_args__ = {"schema": "pettycashv2"}

    entity_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"), primary_key=True,
    )
    sale_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv2.sale_info.id", ondelete="RESTRICT"), primary_key=True,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=True)

    sale_info = db.relationship("SaleInfo", lazy="joined")

    # the pre-C3 name of the flag, usable in queries too
    enabled = synonym("is_active")

    # read-through to the catalogue row (object level; joins are needed in SQL)
    @property
    def sale_name(self):
        return self.sale_info.sale_name if self.sale_info is not None else None

    @property
    def value_name(self):
        return self.sale_info.value_name if self.sale_info is not None else None

    @property
    def type(self):
        return self.sale_info.type if self.sale_info is not None else None

    @property
    def is_cash(self) -> bool:
        return self.sale_info is not None and self.sale_info.is_cash
