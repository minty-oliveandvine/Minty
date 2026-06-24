from uuid import uuid4

from models.db import db


class ShareLink(db.Model):
    __tablename__ = "share_link"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    path_segment = db.Column(db.String(255), unique=True, nullable=False, index=True)
    token = db.Column(db.Text, nullable=False)
    entity_id = db.Column(db.String(36), nullable=False)
    transaction_date = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    expires_at = db.Column(db.TIMESTAMP, nullable=False)

    def __repr__(self):
        return f"<ShareLink {self.path_segment}>"

