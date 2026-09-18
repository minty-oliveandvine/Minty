"""Append-only log of user cancel / uncancel actions.

Distinct from the current-state mirror (``entity_module_subscription``): rows here
are immutable and freeze point-in-time facts — including ``extension_amount``, which
is deliberately NOT stored on the mirror. Never updated after insert.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import CreatedAtMixin
from blueprints.shared.column_types import pg_enum
from blueprints.shared.enums import ModuleCode
from blueprints.subscription.models.column_types import (
    AUDIT_OUTCOME,
    EXTENSION_STATE,
    SUBSCRIPTION_PHASE,
    tz_datetime,
    uuid_column,
)
from blueprints.shared.schema import SCHEMA


class SubscriptionAuditLog(CreatedAtMixin, db.Model):
    __tablename__ = "subscription_audit_log"
    __table_args__ = (
        db.Index("ix_sub_audit_entity_created", "entity_id", "created_at"),
        db.Index("ix_sub_audit_payer_created", "payer_user_id", "created_at"),
        {"schema": SCHEMA},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(
        uuid_column(), db.ForeignKey(f"{SCHEMA}.entities.id"), nullable=False
    )
    function_code = db.Column(pg_enum(ModuleCode), nullable=False)
    payer_user_id = db.Column(
        uuid_column(), db.ForeignKey(f"{SCHEMA}.user.id"), nullable=False
    )
    actor_user_id = db.Column(
        uuid_column(), db.ForeignKey(f"{SCHEMA}.user.id"), nullable=True
    )

    action = db.Column(db.String(20), nullable=False)  # cancel / uncancel / transfer_*
    phase_before = db.Column(SUBSCRIPTION_PHASE, nullable=True)
    phase_after = db.Column(SUBSCRIPTION_PHASE, nullable=True)

    # WHO PAID, before and after. Null on every action that does not move the bill —
    # which is all of them except the transfer family, so null is "not a payer change"
    # rather than "unknown". ``payer_user_id`` above stays what it has always been: the
    # payer at the time of the action, i.e. the OUTGOING one on a transfer.
    #
    # They exist because a transfer is the first action here with two parties. Recording
    # it as a bare ``payer_user_id`` would answer "who was billed" and lose the only
    # question anyone asks afterwards — where did this company's bill go, and who agreed
    # to take it. No FK, matching ``actor_user_id``'s neighbours in spirit: this is
    # history and has to survive either person leaving.
    payer_before = db.Column(uuid_column(), nullable=True)
    payer_after = db.Column(uuid_column(), nullable=True)
    app_access_until = db.Column(tz_datetime(), nullable=True)
    extension_amount = db.Column(db.Integer, nullable=True)
    extension_state = db.Column(EXTENSION_STATE, nullable=True)
    outcome = db.Column(AUDIT_OUTCOME, nullable=False)  # succeeded / aborted
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

    def __repr__(self):
        return (
            f"<SubscriptionAuditLog {self.action} "
            f"{self.entity_id}/{self.function_code}>"
        )
