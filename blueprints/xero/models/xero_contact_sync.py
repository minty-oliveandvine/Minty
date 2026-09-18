"""A Xero contact synced for one company (``xero_contact_sync``).

Insert/update only - the sync never removes a contact (see
``entity/services/settings.sync_contacts_if_changed``). ``ReportExpense.contact`` and the
``entity_pettycash_settings`` contact columns point here.
"""
from uuid import uuid4

from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class XeroContactSync(db.Model):
    __tablename__ = "xero_contact_sync"
    __table_args__ = {"schema": SCHEMA}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    entity_id = db.Column(MintyUuid(), db.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"))
    xero_contact_id = db.Column(db.String(36), nullable=False)
    xero_org_id = db.Column(db.String(36))
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )
