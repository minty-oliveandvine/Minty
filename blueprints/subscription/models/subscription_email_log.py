"""One row per billing email the engine has decided to send.

This table exists for ONE reason: the jobs that trigger these emails are documented as
safe to run at any cadence. ``retry-dunning`` gates its attempts on the schedule rather
than on when it last ran (see ``dunning.collect_due``), and ``sweep-access`` re-derives
the whole access map every pass. Both properties hold because neither job's *effects*
depend on how often it runs — and attaching an email breaks exactly that, because a send
is not idempotent the way a state reconciliation is. Without this table an hourly cron
mails the customer hourly.

So the send is CLAIMED before it is attempted: insert (event, dedupe_key), commit, then
send. A second run finds the row and skips. A row left at ``failed`` is retried on the
next pass — a mail outage should not silently swallow a dunning notice — while a row at
``sent`` is never re-sent, which is the guarantee the whole table is for.

Deliberately not merged into ``subscription_audit_log``: that log is append-only and
freezes point-in-time facts about what the USER did. This is mutable delivery state about
what MINTY did, and its uniqueness constraint is load-bearing rather than incidental.
"""
import uuid

from models.db import db

STATUS_SENT = "sent"
STATUS_FAILED = "failed"


class SubscriptionEmailLog(db.Model):
    __tablename__ = "subscription_email_log"
    __table_args__ = (
        # The dedupe guarantee itself. Not just an index: two overlapping runs of the
        # same job must collide here rather than both deciding they are first.
        db.UniqueConstraint("event", "dedupe_key", name="uq_sub_email_event_key"),
        db.Index("ix_sub_email_user_created", "user_id", "created_at"),
        {"schema": "pettycashv2"},
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # The payer. Nullable FK is wrong here — an email with no recipient is not a row.
    user_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.user.id"), nullable=False
    )
    event = db.Column(db.String(40), nullable=False)
    # Whatever makes this send unique for this event: a renewal period key, a dunning
    # attempt number, an entity+module pair. Composed by the caller, because only the
    # caller knows what "the same notification" means for its event.
    dedupe_key = db.Column(db.String(200), nullable=False)
    # Kept for support: "what address did we actually use", which is not answerable
    # later if the user has since changed their email.
    recipient = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_FAILED)
    error = db.Column(db.String(500), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<SubscriptionEmailLog {self.event} {self.dedupe_key} {self.status}>"
