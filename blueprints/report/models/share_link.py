from uuid import uuid4

from blueprints.shared.column_types import MintyUuid
from models.db import db
from blueprints.shared.schema import SCHEMA


class ShareLink(db.Model):
    __tablename__ = "share_link"
    __table_args__ = {"schema": SCHEMA}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    path_segment = db.Column(db.String(255), unique=True, nullable=False, index=True)
    token = db.Column(db.Text, nullable=False)
    entity_id = db.Column(MintyUuid(), db.ForeignKey(f"{SCHEMA}.entities.id", ondelete="CASCADE"), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<ShareLink {self.path_segment}>"
