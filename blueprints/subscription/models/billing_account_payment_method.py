"""The cards on one billing account.

THE SHELF BEHIND THE DEFAULT. ``payer_billing_group.stripe_payment_method_id``
names the ONE card a billing account charges. This table is every card the payer
has put on that account, exactly one of which carries ``is_default`` and is the
same card that column names.

WHY THE DEFAULT IS RECORDED TWICE. Deliberately, and it is the only duplication in
this area. ``renewals`` and ``dunning`` read the account row and must not join to
discover which card to charge - the charge path stays a single row read. The cost
is a pair that can disagree, so:

  * ``store.set_group_default_card`` writes BOTH or neither;
  * ``uq_billing_account_payment_method_default`` (a partial unique index on
    ``billing_group_id WHERE is_default``) makes a second default impossible in
    the database rather than only in the service.

A divergence between the two means the account charges a card the payer is not
being shown. Nothing raises when that happens - it simply bills the wrong card -
which is why it is held down from both sides.

ONE ROW PER CARD PER ACCOUNT, not per payer. The same card may sit on two of a
payer's accounts: one company each, separate invoices, and that is an ordinary
arrangement rather than a mistake. It is also why
``uq_payer_billing_group_payer_card`` was dropped in ``v1a01_billing_account``.

ONLY THE ID IS HELD. The number is typed into Stripe Elements and confirmed
against a SetupIntent; no PAN reaches this process, this table or these logs. What
the card LOOKS like - brand, last four, expiry - is read from Stripe at display
time by ``payment_methods._view`` rather than copied here, so a card replaced or
updated at Stripe cannot be described in two different ways by two parts of the
app.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import TimestampMixin
from blueprints.subscription.models.column_types import uuid_column


class BillingAccountPaymentMethod(TimestampMixin, db.Model):
    __tablename__ = "billing_account_payment_method"
    __table_args__ = (
        # Re-adding a card the account already holds is an UPDATE of that row,
        # never a second one - otherwise "which of these two is it" has no answer.
        db.UniqueConstraint(
            "billing_group_id",
            "stripe_payment_method_id",
            name="uq_billing_account_payment_method_card",
        ),
        db.Index("ix_billing_account_payment_method_group", "billing_group_id"),
        {"schema": "pettycashv2"},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    # CASCADE, unlike the other foreign keys in this set. A row here is not a fact
    # about a payment in its own right, it is the account's list; deleting the
    # account and keeping the list leaves rows nothing can reach. Invoices, which
    # ARE facts in their own right, live elsewhere and carry no FK.
    billing_group_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv2.payer_billing_group.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ``pm_...``. Immutable on this row: replacing a card ADDS one and repoints the
    # default, so the card that was charged for a past period is still nameable.
    stripe_payment_method_id = db.Column(db.String(255), nullable=False)
    # The partial unique index that holds "at most one per account" is created by
    # the migration, not declared here: SQLAlchemy has no portable spelling for a
    # partial index, and declaring a plain unique one would allow only ONE card
    # per account - the opposite of the point.
    is_default = db.Column(db.Boolean(), nullable=False, server_default=db.false())

    def __repr__(self):
        return (
            f"<BillingAccountPaymentMethod account={self.billing_group_id} "
            f"card={self.stripe_payment_method_id} default={self.is_default}>"
        )
