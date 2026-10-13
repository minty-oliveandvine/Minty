from blueprints.shared.column_types import MintyUuid, Money
from models.db import db
from blueprints.shared.schema import SCHEMA


class EntityPettycashSettings(db.Model):
    __tablename__ = "entity_pettycash_settings"
    __table_args__ = {"schema": SCHEMA}

    entity_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Onboarding Step 5: the cash in the drawer on day one and the date reporting starts;
    # the first report opens from them (report/services/shared.first_report_defaults).
    opening_balance = db.Column(Money(), nullable=True)
    start_date = db.Column(db.Date, nullable=True)

    pettycash_account_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    bank_account_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    cash_sale_account_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    discrepancy_bank_account_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    discrepancy_account_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    director_account_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )

    cash_sale_contact_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.xero_contact_sync.id", ondelete="SET NULL"),
        nullable=True,
    )
    director_contact_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.xero_contact_sync.id", ondelete="SET NULL"),
        nullable=True,
    )
    discrepancy_contact_id = db.Column(
        MintyUuid(),
        db.ForeignKey(f"{SCHEMA}.xero_contact_sync.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
