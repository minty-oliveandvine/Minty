"""Append-only log of user cancel / uncancel actions.

Distinct from the current-state mirror (``entity_module_subscription``): rows here
are immutable and freeze point-in-time facts — including ``extension_amount``, which
is deliberately NOT stored on the mirror. Never updated after insert.
"""
import uuid

from models.db import db


class SubscriptionAuditLog(db.Model):
    __tablename__ = "subscription_audit_log"
    __table_args__ = (
        db.Index("ix_sub_audit_entity_created", "entity_id", "created_at"),
        db.Index("ix_sub_audit_payer_created", "payer_user_id", "created_at"),
        {"schema": "pettycashv2"},
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.entities.id"), nullable=False
    )
    function_code = db.Column(db.String(100), nullable=False)
    payer_user_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.user.id"), nullable=False
    )
    actor_user_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.user.id"), nullable=True
    )

    action = db.Column(db.String(20), nullable=False)  # cancel / uncancel
    phase_before = db.Column(db.String(30), nullable=True)
    phase_after = db.Column(db.String(30), nullable=True)
    app_access_until = db.Column(db.DateTime(timezone=True), nullable=True)
    extension_amount = db.Column(db.Integer, nullable=True)
    extension_state = db.Column(db.String(20), nullable=True)
    outcome = db.Column(db.String(20), nullable=False)  # succeeded / aborted
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )

    def __repr__(self):
        return (
            f"<SubscriptionAuditLog {self.action} "
            f"{self.entity_id}/{self.function_code}>"
        )
