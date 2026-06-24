import uuid

from models.db import db


class TermsUserPrincipal(db.Model):
    """One consent principal per user (1:1 with ``user``).

    ``account_ref`` points at ``pettycashv2.user.id`` and is UNIQUE, which is
    what enforces the 1:1 relationship.
    """

    __tablename__ = "terms_user_principal"
    __table_args__ = {"schema": "pettycashv2"}

    principal_id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    account_ref = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.user.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    created_at = db.Column(
        db.TIMESTAMP(timezone=True),
        server_default=db.func.current_timestamp(),
        nullable=False,
    )

    user = db.relationship(
        "User",
        backref=db.backref("terms_principal", uselist=False, lazy="joined"),
    )
