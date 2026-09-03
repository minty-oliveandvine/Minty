"""Drop the one-cycle-per-payer columns from user_stripe_customer.

THE OTHER HALF OF y1a01. That revision created ``payer_billing_group`` and
``entity_billing_group`` and moved the billing cycle from the PAYER to the CARD:
a payer holding two cards has two paid-through dates and two dunning clocks, and
only the card's answer is true of the companies nominated onto it. It left the
account-level columns in place so both designs could be read while the data was
moved across. This removes the superseded half.

These three were never pre-subscription columns. They arrive with
``user_stripe_customer`` itself in ``a1b2c3d4e5f7_subscription_schema`` and are
mentioned by exactly two revisions in the tree — that one and y1a01. They are the
FIRST billing-state design of this feature, superseded by the second about eight
months later, not legacy from some earlier era of the product.

-----------------------------------------------------------------------------
RUN THE BACKFILL FIRST. THIS IS NOT OPTIONAL.

``scripts/backfill_billing_groups.py`` is what moves the data, and it moves it by
COPYING these three columns onto each payer's group — it does not derive them
from anything else, and Stripe cannot supply them (``paid_through`` is Minty's own
conclusion about what a payer has paid for, not a fact Stripe holds). Drop these
first and the backfill has nothing left to read.

The gate is one query, and it must return zero on every database this revision
will reach:

    SELECT u.user_id
    FROM pettycashv2.user_stripe_customer u
    LEFT JOIN pettycashv2.payer_billing_group g ON g.payer_user_id = u.user_id
    WHERE u.stripe_customer_id IS NOT NULL AND g.id IS NULL;

A database whose head is BELOW ``a1b2c3d4e5f7`` passes trivially: it has no
``user_stripe_customer`` table at all, so both sides are empty and the backfill is
ceremonial there. The gate matters for any database that already carries payers.

-----------------------------------------------------------------------------
WHY ``IF EXISTS``

Same reason as ``s5a05``: environments in this project have had columns dropped by
hand ahead of the revision that formalises it, and a revision that fails only on
the database you cannot easily retry is the worst shape of migration bug.

-----------------------------------------------------------------------------
WHAT THIS FIXED ON THE WAY

``store.payer_is_dunning`` read ``user_stripe_customer.dunning_started_at``, which
nothing has written since y1a01. It therefore answered False for a payer whose card
was genuinely mid-collection — and it is the check ``transfers.transfer_blockers``
uses to refuse a handover while a debt is outstanding. It now reads the groups, and
agrees with ``store.groups_in_dunning``. The two ``paid_through`` fallbacks in
``store`` went with it: they existed to answer for a payer the backfill had not
reached, which is a state this revision makes impossible.

-----------------------------------------------------------------------------
WHAT STAYS

``anchor_at`` and ``currency`` remain on the account and are NOT part of this. They
are genuinely per-payer: every group of a payer renews on the same period
boundaries, so the cycle anchor belongs to the account while the paid-through date
belongs to the card. ``stripe_customer_id`` stays too — Stripe is still the rail.

-----------------------------------------------------------------------------
NOTE ON THE GRAPH

The migration graph has several heads; this revision extends the one the
application databases are actually on (``s5a05_drop_legacy_sales``). Upgrade to
this revision by name rather than to "head", which is ambiguous here.

Revision ID: z1a01_drop_payer_cycle
Revises: s5a05_drop_legacy_sales
Create Date: 2026-09-02
"""
import sqlalchemy as sa
from alembic import op

revision = "z1a01_drop_payer_cycle"
down_revision = "s5a05_drop_legacy_sales"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"
TABLE = "user_stripe_customer"

# Each has an exact counterpart on payer_billing_group, same type and nullability,
# which is what makes the backfill a behavioural no-op.
SUPERSEDED_COLUMNS = [
    "paid_through",
    "dunning_started_at",
    "dunning_attempts",
]


def upgrade():
    for column in SUPERSEDED_COLUMNS:
        op.execute(
            f'ALTER TABLE {SCHEMA}.{TABLE} DROP COLUMN IF EXISTS "{column}"'
        )


def downgrade():
    # The columns come back EMPTY, and that is the honest outcome. The live values
    # are on payer_billing_group and a payer may hold several groups, so there is
    # no single account-level answer to restore them from — which is the whole
    # reason they moved. A downgrade restores the shape so an older build can boot;
    # it does not pretend to restore the data.
    op.add_column(
        TABLE,
        sa.Column("paid_through", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("dunning_started_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "dunning_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA,
    )
