"""A billing account: its identity, its cards, and everything it pays for.

ONE ACCOUNT, SEVERAL SHELVES. ``user_stripe_customer`` used to be the whole billing
account: one card, one ``paid_through``, one dunning clock, and every company the payer
paid for sharing them. That is what made "choose a card" mean "change the account
default" everywhere in the app — see the module docstring in ``services.payment_methods``.

A billing group is the smaller unit that replaces it: **one payment method, plus
everything it pays for**. A payer may have several. ``entity_billing_group`` says which
companies are on which.

IT IS NOW THE BILLING ACCOUNT, AND IT HAS A NAME. ``v1a01_billing_account`` added
``billing_email`` and ``billing_company`` — what the payer wants their invoices to say,
which is not the same thing as who they are. The Stripe customer could not carry it:
``checkout._payer_identity`` rewrites its email from the ``user`` row on every write, and
its NAME is the payer's human name because an entity name there would be wrong the moment
a second entity is added. The identity therefore lives where the money already is, and
costs no new join on any billing query.

THE CARD COLUMN IS NOW THE DEFAULT AMONG SEVERAL. An account may hold more than one card;
``billing_account_payment_method`` is the shelf, and ``stripe_payment_method_id`` below is
the one this account CHARGES. The two are written together by
``store.set_group_default_card`` — see that model for why the default is deliberately
recorded in both places.

WHAT MOVED HERE, AND WHY EACH ONE HAD TO.

* ``stripe_payment_method_id`` — the card that will be charged for this group's entities.
* ``paid_through`` — what THIS ACCOUNT has paid for. One invoice is raised per group, so
  this is exactly the grain the money is collected at.
* ``dunning_started_at`` / ``dunning_attempts`` — collection is per account too. A payer
  with a good card on company A and a dead one on company B must keep A: the decline has
  to be contained, which it cannot be while the retry clock is a single per-payer value.

  These three were per CARD when a group WAS a card. Since ``v1a01_billing_account`` an
  account can hold several, so they are per ACCOUNT. The grain has not moved in practice —
  one invoice per group either way — but the reason has, and the old wording read as
  though a second card would bring a second cycle with it. It does not.

THIS IS NOT THE OLD PER-ROW ``current_period_end`` COMING BACK. That one was removed for
drifting between one payer's entities, and it drifted because it was refreshed only when
its own entity happened to be touched — three rows of one payer, three different answers,
all of them claiming to be the same fact. This value is written by exactly one thing, the
charge that collected it, and there is one of those per group per period.

WHAT STAYS ON THE PAYER. ``anchor_at`` and ``currency``, on ``user_stripe_customer``.
Every group of a payer renews on the SAME period boundaries — one cycle, several invoices
— so ``billing.period_containing`` and the month-end clamp are untouched, and a payer's
invoices still cannot mix currencies.

THE CARD IS AN ATTRIBUTE, NOT THE KEY. Entities point at the GROUP, and the group names
the card. If they pointed straight at a ``pm_...`` id, replacing an expiring card would
strand the cycle: a new id is a new key, its ``paid_through`` would start NULL, and
``renewals.due_renewals`` skips NULL outright — the entity would quietly stop renewing.
Here, replacing a card is an UPDATE of one column and the cycle survives it.

Only the id is held. The number is typed into Stripe Elements and confirmed against a
SetupIntent; no PAN reaches this process, this table or these logs.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import TimestampMixin
from blueprints.subscription.models.column_types import (
    tz_datetime,
    uuid_column,
)


class PayerBillingGroup(TimestampMixin, db.Model):
    __tablename__ = "payer_billing_group"
    __table_args__ = (
        # uq_payer_billing_group_payer_card IS GONE — dropped by
        # ``v1a01_billing_account``. It said a payer could not hold two groups on one
        # card, which was right when a group WAS a card and is wrong now: the same card
        # on two accounts, one company each, is an ordinary arrangement. What it was
        # protecting — two groups both claiming one entity's renewal — is held by
        # ``uq_entity_billing_group_entity_payer``, which is where the claim is recorded.
        db.Index("ix_payer_billing_group_payer", "payer_user_id"),
        db.Index("ix_payer_billing_group_dunning", "dunning_started_at"),
        {"schema": "pettycashv3"},
    )

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    # FK to ``user``, not to ``user_stripe_customer`` — the same choice the module rows
    # make. A group can be nominated before the payer has ever been charged.
    payer_user_id = db.Column(
        uuid_column(),
        db.ForeignKey("pettycashv3.user.id"),
        nullable=False,
    )
    # ``pm_...``, and the card this account CHARGES — the default among whatever
    # ``billing_account_payment_method`` holds. Mutable: this is how a card is REPLACED
    # without losing the cycle, and ``store.set_group_default_card`` is the only thing
    # that should write it, because the shelf row has to move with it.
    stripe_payment_method_id = db.Column(db.String(255), nullable=False)

    # --- the account's identity ----------------------------------------------------
    #
    # What the payer wants their invoices to say. NULLABLE FOR GOOD, and the reason has
    # nothing to do with legacy rows — that argument expires, and these three do not:
    #
    # 1. UNNAMED ACCOUNTS ARE STILL BEING CREATED, as normal behaviour rather than as a
    #    tail that drains. ``store.nominate_card_for_entity`` opens a group with neither
    #    field set whenever a payer puts a company on a card that is not yet on an
    #    account — the card picker's Confirm, entity transfers, and two checkout paths.
    #    NOT NULL would break all four unless each invented an identity.
    # 2. NULL IS READ AS A STATE, not as a gap. ``checkout._named_account`` deliberately
    #    SKIPS accounts whose two fields are both blank so that it returns the oldest
    #    NAMED one; storing an invented value would make every account look named and
    #    change which one gets to name the Stripe customer.
    # 3. An invented billing company is worse than none: it prints on an invoice as
    #    though the payer had chosen it. Absent means "not named", which the application
    #    renders as the payer's own details, per field.
    #
    # The onboarding "New billing account" form REQUIRES both. That is a rule about what
    # a payer may CREATE, not an invariant about what exists — everything reading these
    # columns must still handle NULL.
    billing_email = db.Column(db.String(255), nullable=True)
    billing_company = db.Column(db.String(255), nullable=True)

    # --- the cycle this card owns -------------------------------------------------
    #
    # NULL until this card has actually collected something. ``due_renewals`` skips a
    # NULL, which is what stops a freshly nominated card being billed for history.
    paid_through = db.Column(tz_datetime(), nullable=True)

    # Anchor for the whole retry schedule, and deliberately not "last attempt at" — see
    # ``services.dunning``. NULL = this card is not in collection.
    dunning_started_at = db.Column(tz_datetime(), nullable=True)
    dunning_attempts = db.Column(db.Integer, nullable=False, server_default="0")

    def __repr__(self):
        return (
            f"<PayerBillingGroup payer={self.payer_user_id} "
            f"card={self.stripe_payment_method_id}>"
        )
