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
    # Why the customer said they were leaving, in their own words, from the cancellation
    # dialog. Optional on every path — nobody is made to justify cancelling — so NULL
    # means "didn't say" rather than "not a cancellation"; read ``action`` for that.
    #
    # It lives HERE and not on entity_module_subscription because it is history, not
    # state: nothing decides what to bill by reading it, and a module cancelled, renewed
    # and cancelled again has two reasons worth keeping. A column on the row would hold
    # only the latest and quietly erase the first.
    cancel_reason = db.Column(db.String(500), nullable=True)
    # Free text ABOUT the action, written by us. Distinct from cancel_reason, which is
    # written by the customer — keeping them apart is what makes "why do people leave?"
    # a query instead of a string search.
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )

    def __repr__(self):
        return (
            f"<SubscriptionAuditLog {self.action} "
            f"{self.entity_id}/{self.function_code}>"
        )
