import uuid

from blueprints.shared.column_types import MintyUuid
from blueprints.shared.enums import EntityStatus
from models.db import db


class Entity(db.Model):
    """A company. Matches ``entities`` in docs/schema/01_schema_rebased.sql.

    Gone with the redesign (item 15): ``minimum_qty``, ``deposit_frequency``, ``deposit_day``
    (never read), ``xero_short_code``, and the two Xero lock dates - billing-backend, the
    only reader, asks Xero's Organisation for them at publish time (decided 2026-09-16).

    ``status`` is the ``entity_status`` enum: ``onboarding`` for the whole wizard, then
    ``connected`` / ``disconnected`` = whether a Xero organisation is linked. The old
    ``active`` / ``cancelled`` / ``deleted`` words no longer exist.
    """

    __tablename__ = "entities"
    __table_args__ = {"schema": "pettycashv3"}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    country_code = db.Column(
        db.CHAR(2), db.ForeignKey("pettycashv3.country_info.country_code")
    )
    currency_id = db.Column(
        MintyUuid(), db.ForeignKey("pettycashv3.currency_info.id")
    )
    name = db.Column(db.String(100), nullable=False)
    # Onboarding Step 1 contact details for the company (not the signed-up
    # person -- user.email / user.user_phone are that, and one user can own
    # several entities). Both optional: the wizard marks them so, and every
    # entity created before c1a01 has NULL. The phone is stored digits-only.
    contact_phone = db.Column(db.String(36))
    business_email = db.Column(db.String(100))
    xero_org_id = db.Column(db.String(36))
    currency_format = db.Column(db.String(30))
    timezone = db.Column(db.String(30))
    note = db.Column(db.Text)
    status = db.Column(
        db.Enum(EntityStatus, name="entity_status", schema="pettycashv3", native_enum=True,
                create_type=False, values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=EntityStatus.ONBOARDING,
    )
    # Onboarding wizard step the user last "Saved and Exited" on. This is the
    # frontend step id (1-9) sent verbatim by the wizard - NOT the backend's
    # derived current_step ordering - so it is stored and returned as-is. NULL
    # means the user never explicitly saved a step.
    onboarding_saved_step = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
    last_connected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Team-wide "last logged in" shown on the Select Company card: when this
    # entity was last opened, and by whom. Written on entity open (see
    # blueprints.entity.routes.modules.record_entity_access). Entity-level, not
    # per-user, so the card shows who last touched the company - including
    # superuser visits, which have no user_entity row.
    last_accessed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_accessed_by_user_id = db.Column(
        MintyUuid(),
        db.ForeignKey("pettycashv3.user.id", ondelete="SET NULL"),
        nullable=True,
    )
    xero_tenant_name = db.Column(db.String(255), nullable=True)
    financial_year_end_day = db.Column(db.SmallInteger, nullable=True)
    financial_year_end_month = db.Column(db.SmallInteger, nullable=True)
    # NOTE: no stripe_customer_id column - the customer belongs to the PAYER, not the
    # entity, so it resolves entity -> payer -> customer. Render paths read it from the
    # local tables via ``entity.services.modules._entity_customer_id``; the billing paths
    # use ``subscription.services.checkout._resolve_customer_id``, which adds a Stripe
    # search fallback that is deliberately wrong for a render.
    # The member who connected this company to Xero; their user_token row is the one a
    # publish uses (replaces the old user.xero_entity_id, C1).
    connected_by_user_id = db.Column(
        MintyUuid(),
        db.ForeignKey("pettycashv3.user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    xero_contact = db.relationship(
        "XeroContactSync", cascade="all, delete-orphan", backref="xero_contact", lazy=True
    )
    account_info = db.relationship(
        "AccountInfo", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    sale_info = db.relationship(
        "EntitySaleSetting", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    entity_cash_detail_v2 = db.relationship(
        "EntityCashDetailV2", cascade="all, delete-orphan", backref="entity", lazy=True
    )
