"""The sales-method catalogue: ``sale_info`` in docs/schema/01_schema_rebased.sql.

One GLOBAL row per method name (``sale_name`` is UNIQUE): Visa, Alipay, Foodpanda, Cash - and
every name a company ever typed for itself (the loader folded the per-entity ``CUSTOM_*``
rows onto one catalogue row per name). Which company uses which method is
``entity_sale_setting`` (``EntitySaleSetting``), a link with its own on/off and order.

``value_name`` is the form-field convention the sales page keeps (``visa_sales``); the Cash
method is the row whose ``value_name`` is ``cash_sales`` - its ``type`` is ``other``.
"""
from uuid import uuid4

from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid
from blueprints.shared.enums import SaleType
from models.db import db
from blueprints.shared.schema import SCHEMA


class SaleInfo(db.Model):
    __tablename__ = "sale_info"
    __table_args__ = {"schema": SCHEMA}

    CASH_VALUE_NAME = "cash_sales"

    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    type = db.Column(
        db.Enum(SaleType, name="sale_type", schema=SCHEMA, native_enum=True,
                create_type=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=SaleType.OTHER,
    )
    sale_name = db.Column(db.String(80), nullable=False, unique=True)
    value_name = db.Column(db.String(80), nullable=True)
    display_order = db.Column(db.Integer, nullable=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    # the names the code used before C3, so readers keep compiling and filtering
    name = synonym("sale_name")
    is_active = synonym("enabled")
    # readers that joined the per-company link by ``sale_id`` now join the catalogue by the
    # same value; the alias lets them keep reading ``.sale_id`` off either object
    sale_id = synonym("id")

    @property
    def is_cash(self) -> bool:
        return self.value_name == self.CASH_VALUE_NAME

    @staticmethod
    def value_name_for(name: str) -> str:
        """The form-field name a NEW method gets: ``"Tap & Go"`` -> ``tap_&_go_sales``, the
        derivation the code has always used (what an old report's detail rows were keyed by)."""
        return (name or "").strip().lower().replace(" ", "_") + "_sales"

    @classmethod
    def by_name(cls, name):
        """The catalogue row for a display name, matched case-insensitively; None if absent."""
        key = (name or "").strip().lower()
        if not key:
            return None
        return cls.query.filter(db.func.lower(cls.sale_name) == key).first()

    @classmethod
    def by_value_name(cls, value_name):
        if not value_name:
            return None
        return cls.query.filter(cls.value_name == value_name).first()

    @classmethod
    def ensure(cls, name, sale_type, *, value_name=None, display_order=None):
        """Get-or-create the catalogue row for ``name``.

        Global by design (schema: UNIQUE sale_name) - two companies that both type "Payme"
        share one row. Does NOT commit: the caller owns the transaction so the catalogue row
        and the link that references it land together. Flushes so the id is available.
        """
        row = cls.by_name(name)
        if row is not None:
            return row
        clean = (name or "").strip() or "Custom"
        row = cls(
            sale_name=clean,
            type=SaleType.normalize(sale_type) or SaleType.OTHER,
            value_name=value_name or cls.value_name_for(clean),
            display_order=display_order,
            enabled=True,
        )
        db.session.add(row)
        db.session.flush()
        return row
