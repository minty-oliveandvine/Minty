import uuid

from sqlalchemy.dialects.postgresql import UUID

from models.db import db


class Entity(db.Model):
    __tablename__ = "entities"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    country_code = db.Column(
        db.CHAR(2), db.ForeignKey("pettycashv2.country_info.country_code")
    )
    currency_id = db.Column(
        UUID(as_uuid=False), db.ForeignKey("pettycashv2.currency_info.id")
    )
    name = db.Column(db.String(100), nullable=False)
    minimum_qty = db.Column(db.Integer)
    deposit_frequency = db.Column(db.Integer)
    deposit_day = db.Column(db.Integer)
    # Onboarding Step 1 contact details for the company (not the signed-up
    # person -- user.email / user.user_phone are that, and one user can own
    # several entities). Both optional: the wizard marks them so, and every
    # entity created before c1a01 has NULL. The phone is stored digits-only.
    contact_phone = db.Column(db.String(20))
    business_email = db.Column(db.String(100))
    xero_org_id = db.Column(db.String(36))
    xero_short_code = db.Column(db.String(50))
    currency_format = db.Column(db.String(30))
    timezone = db.Column(db.String(30))
    note = db.Column(db.Text)
    status = db.Column(db.String(20), default="active")
    # Onboarding wizard step the user last "Saved and Exited" on. This is the
    # frontend step id (1-9) sent verbatim by the wizard — NOT the backend's
    # derived current_step ordering — so it is stored and returned as-is. NULL
    # means the user never explicitly saved a step.
    onboarding_saved_step = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    last_connected_at = db.Column(db.TIMESTAMP, nullable=True)
    # Team-wide "last logged in" shown on the Select Company card: when this
    # entity was last opened, and by whom. Written on entity open (see
    # blueprints.entity.routes.modules.record_entity_access). Entity-level, not
    # per-user, so the card shows who last touched the company — including
    # superuser visits, which have no user_entity row.
    last_accessed_at = db.Column(db.TIMESTAMP, nullable=True)
    last_accessed_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id", ondelete="SET NULL"),
        nullable=True,
    )
    period_lock_date = db.Column(db.Date, nullable=True)
    end_of_year_lock_date = db.Column(db.Date, nullable=True)
    xero_tenant_name = db.Column(db.String(255), nullable=True)
    # NOTE: no stripe_customer_id column — the entity's Stripe customer is resolved
    # live from Stripe via the customer's metadata.entity_id (see
    # subscription.services.stripe_state.customer_id_for_entity).
    connected_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    xero_contact = db.relationship(
        "XeroContactSync", cascade="all, delete-orphan", backref="xero_contact", lazy=True
    )
    account_info = db.relationship(
        "AccountInfo", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    # The ReportDetail relationship went with Step 3.5 — nothing writes that
    # table any more, so there are no children for the cascade to reach. The
    # model itself survives until the Step 4 drop.
    # The report_v2 relationship went with Step 4a-2, alongside report_detail.
    # ReportV2 has had no writers since r2a02; the model outlives this only
    # until the r10a10 drop.
    sale_info = db.relationship(
        "EntitySaleSetting", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    entity_cash_detail_v2 = db.relationship(
        "EntityCashDetailV2", cascade="all, delete-orphan", backref="entity", lazy=True
    )
