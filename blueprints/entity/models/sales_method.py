from uuid import uuid4

from models.db import db


class SalesMethod(db.Model):
    """Catalog of sales/payment methods — the sales analogue of EntityFunction.

    Row scoping mirrors the global-vs-per-entity split used elsewhere:
      * ``entity_id IS NULL`` → global catalog row (Visa, Octopus, ...),
        available to every entity;
      * ``entity_id`` set     → custom method owned by that one entity, created
        when a user types a name that matches no global row.

    ``sale_info`` rows point here (the EntityFunctionMap analogue), and
    ``report_sale_detail`` rows carry the id directly so a historical report
    stays self-describing even after an entity removes the method.

    ``legacy_column`` is the transition bridge back to the physical ``*_sales``
    columns on report / report_draft. It exists only to drive the backfill and
    is dropped once those columns go — a NEW method must never need one, or
    adding a method would again require a schema change.

    Cash is deliberately absent: ``cash_sales`` is a separate concept with its
    own column and its own ``type == "Cash"`` branch in the totals code.
    """

    __tablename__ = "sale_info"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"),
        nullable=True,
    )
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    # 'Electronic' | 'Delivery' — matches sale_info.type values.
    type = db.Column(db.String(20), nullable=False)
    legacy_column = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    @classmethod
    def resolve(cls, entity_id, *, code=None, legacy_column=None, name=None):
        """Find the catalog row an entity should use for a method.

        Prefers the entity's own custom row over the global one so a custom
        method can shadow a global code. Lookup is by whichever key the caller
        has: ``code``, ``legacy_column`` (the old ``value_name``), or ``name``.

        Returns None when nothing matches — callers creating a user-named
        method should fall back to ``ensure_custom``.
        """
        query = cls.query.filter(
            db.or_(cls.entity_id == entity_id, cls.entity_id.is_(None))
        )
        if code is not None:
            query = query.filter(cls.code == code)
        elif legacy_column is not None:
            query = query.filter(cls.legacy_column == legacy_column)
        elif name is not None:
            query = query.filter(db.func.lower(cls.name) == (name or "").strip().lower())
        else:
            return None
        # entity-owned row first: NULLS LAST puts the global fallback second.
        return query.order_by(cls.entity_id.isnot(None).desc()).first()

    @staticmethod
    def custom_code(name):
        """Derive the catalog code for an entity-invented method name.

        Mirrors the expression the SQL backfill used, so a method minted here
        collides (and therefore dedupes) with its backfilled counterpart
        instead of creating a second row for the same thing.
        """
        base = "".join(ch if ch.isalnum() else "_" for ch in (name or "").strip())
        return ("CUSTOM_" + base.upper())[:49]

    @classmethod
    def ensure_custom(cls, entity_id, name, method_type):
        """Get-or-create the per-entity catalog row for a user-typed method.

        Does NOT commit — the caller owns the transaction, so the new catalog
        row and the sale_info row that references it land together or not at
        all. Flushes so the generated id is available to the caller.
        """
        code = cls.custom_code(name)
        existing = cls.query.filter_by(entity_id=entity_id, code=code).first()
        if existing is not None:
            return existing

        row = cls(
            entity_id=entity_id,
            code=code,
            name=(name or "").strip() or "Custom",
            type=method_type or "Electronic",
            legacy_column=None,  # custom methods have no physical column
            is_active=True,
            display_order=0,
        )
        db.session.add(row)
        db.session.flush()
        return row
