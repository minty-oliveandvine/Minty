from models.db import db


class EntityPettycashSettings(db.Model):
    __tablename__ = "entity_pettycash_settings"
    __table_args__ = {"schema": "pettycashv2"}

    entity_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    pettycash_account_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    bank_account_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    cash_sale_account_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    discrepancy_bank_account_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    discrepancy_account_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )
    director_account_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.account_info.id", ondelete="SET NULL"),
        nullable=True,
    )

    cash_sale_contact_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.xero_contact_sync.id", ondelete="SET NULL"),
        nullable=True,
    )
    director_contact_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.xero_contact_sync.id", ondelete="SET NULL"),
        nullable=True,
    )
    discrepancy_contact_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.xero_contact_sync.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(
        db.TIMESTAMP, server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.TIMESTAMP,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
