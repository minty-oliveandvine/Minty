"""The tunable subscription windows, as a single row.

See migration ``e1a3c5b7d9f2`` for why this is one typed row rather than a key/value
table, and why the past-due grace and the dunning give-up deadline are ONE column.

Nothing reads this model directly. ``subscription.services.policy`` is the only caller:
it validates the row against the rules the columns cannot express and falls back to the
in-code defaults if it does not hold together.
"""
from models.db import db
from blueprints.subscription.models.column_types import tz_datetime
from blueprints.shared.schema import SCHEMA


class BillingPolicy(db.Model):
    """Singleton (``id`` is always 1). Commercial policy, not arithmetic."""

    __tablename__ = "billing_policy"
    __table_args__ = {"schema": SCHEMA}

    id = db.Column(db.Integer, primary_key=True, autoincrement=False, default=1)

    # Card-free onboarding trial. Captured into ``trial_end`` when a trial starts, so a
    # change never shortens one already running.
    trial_days = db.Column(db.Integer, nullable=False, server_default="30")

    # Access after an in-app cancellation. Captured into ``app_access_until`` at
    # cancellation. Feeds ``billing.extension_charge``, so this one moves money.
    paid_cancel_access_days = db.Column(
        db.Integer, nullable=False, server_default="30"
    )

    # ONE window for both halves of going past due: how long access survives a failed
    # renewal, and when collection gives up. They must end together — see the migration.
    past_due_window_days = db.Column(db.Integer, nullable=False, server_default="15")

    # Offsets from the FIRST failure, not gaps: "1,2,3,..." fires daily from day 1. The
    # length is the attempt count, so adding an entry adds a charge attempt.
    #
    # The default stops at 13 against a 15-day window on purpose — ``policy._dunning_pair``
    # refuses a schedule whose last retry leaves under two days to settle, so a longer
    # list needs ``past_due_window_days`` widened with it or it is silently ignored.
    retry_offsets_days = db.Column(
        db.String(100), nullable=False,
        server_default="1,2,3,4,5,6,7,8,9,10,11,12,13",
    )

    updated_at = db.Column(
        tz_datetime(),
        server_default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )
    updated_by = db.Column(db.String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BillingPolicy trial={self.trial_days}d "
            f"cancel={self.paid_cancel_access_days}d "
            f"past_due={self.past_due_window_days}d "
            f"retries={self.retry_offsets_days}>"
        )
