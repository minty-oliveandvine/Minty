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
    contact_option = db.Column(db.String(36))
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
    period_lock_date = db.Column(db.Date, nullable=True)
    end_of_year_lock_date = db.Column(db.Date, nullable=True)
    xero_tenant_name = db.Column(db.String(255), nullable=True)
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
    report_detail = db.relationship(
        "ReportDetail", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    report_v2 = db.relationship(
        "ReportV2", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    sale_info = db.relationship(
        "EntitySaleSetting", cascade="all, delete-orphan", backref="entity", lazy=True
    )
    entity_cash_detail_v2 = db.relationship(
        "EntityCashDetailV2", cascade="all, delete-orphan", backref="entity", lazy=True
    )
