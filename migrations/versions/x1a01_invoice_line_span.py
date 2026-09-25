"""AN INVOICE LINE RECORDS WHAT IT PAID FOR

Revision ID: x1a01_invoice_line_span
Revises: w1a01_transfer_handover
Create Date: 2026-09-25

=============================================================================
WHAT THIS IS

Three nullable columns on ``subscription_invoice_line``:

  ``period_start``  - the first instant the line pays for (or credits back)
  ``period_end``    - the instant it stops; half-open, like the invoice's period
  ``unit_amount``   - the price per billing period it was charged at, in cents

Item 23 of ``docs/schema/01_schema_rebased.sql``, which declares all three - so
a FRESH build already has them, and this revision is, like ``w1a01``, the belt
to that file's braces: it exists for the databases that are already up.

-----------------------------------------------------------------------------
WHY

A line held its amount, its kind and ``at`` - enough to print, not enough to
explain. The payer portal's billing breakdown (08-B "Download csv": a row per
company per line, with the monthly rate and the days it covered) had to work
both back out of how each kind of line is priced. That holds for a renewal and
a mid-period change, whose inputs never move. It does not hold for an access
extension: its days end at the module's ``app_access_until``, and a module
resumed afterwards has that cleared - the breakdown of an invoice already paid
then prints a blank end and a catalogue price nobody was charged.

Written at issue, by the arithmetic that priced the line, they are simply true:

  renewal                 the invoice's period, at its plan's price
  start / upgrade         the change to the period's end, at the new plan's price
  credit for the old plan the same days, at the old plan's price (amount < 0)
  access extension        what the company was paid through to its access end,
                          at the rate the cancellation priced it at

-----------------------------------------------------------------------------
NULL IS AN ANSWER, TWICE

Every line issued before this revision is NULL in all three, and stays so: no
backfill. Those lines' figures can still be DERIVED (the breakdown does), but a
derived number written into a column that means "recorded at issue" would stop
being distinguishable from a recorded one.

``unit_amount`` is also NULL on an extension whose rate stepped part-way - a
bundle winding down with its modules ending on different days, priced piece by
piece (``checkout._segmented_extension``). It had no single rate, and a blended
figure would claim a price nobody set. Its days are still recorded.

-----------------------------------------------------------------------------
IT TOUCHES pettycashv3 AND NOTHING ELSE

As ``w1a01``: pettycashv2 is being retired, so nothing new is built on it, and
``pettycashv3`` carries no ``alembic_version`` of its own - the chain's bookmark
stays in pettycashv2's, and the DDL below goes nowhere near that schema.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE

Three nullable ADD COLUMNs: no rewrite, no default to fill, no index. Old code
does not know the columns exist and behaves exactly as it does today; new code
reads NULL on every historic row. Guarded and idempotent - a database that has
them already is a no-op.

The downgrade drops them. Nothing is lost that cannot be rebuilt: the lines
still carry their amounts, and the breakdown falls back to deriving what it
reads here.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op


revision = "x1a01_invoice_line_span"
down_revision = "w1a01_transfer_handover"
branch_labels = None
depends_on = None

# PETTYCASHV3 ONLY, as w1a01 - see the header.
SCHEMA = "pettycashv3"

LINE = "subscription_invoice_line"
COLUMNS = (
    ("period_start", sa.TIMESTAMP(timezone=True)),
    ("period_end", sa.TIMESTAMP(timezone=True)),
    ("unit_amount", sa.Integer()),
)


def _columns(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(LINE, schema=SCHEMA)}


def upgrade():
    bind = op.get_bind()

    if not sa.inspect(bind).has_table(LINE, schema=SCHEMA):
        print(f"{SCHEMA}.{LINE} does not exist - nothing to do.")
        return

    existing = _columns(bind)
    for name, type_ in COLUMNS:
        if name in existing:
            print(f"{SCHEMA}.{LINE}.{name} already exists - skipping.")
            continue
        op.add_column(LINE, sa.Column(name, type_, nullable=True), schema=SCHEMA)
        print(f"Added {SCHEMA}.{LINE}.{name} (NULL on every existing line - see the header).")


def downgrade():
    bind = op.get_bind()

    if not sa.inspect(bind).has_table(LINE, schema=SCHEMA):
        return

    existing = _columns(bind)
    for name, _type in reversed(COLUMNS):
        if name not in existing:
            print(f"{SCHEMA}.{LINE}.{name} is already gone - nothing to do.")
            continue
        op.drop_column(LINE, name, schema=SCHEMA)
        print(f"Dropped {SCHEMA}.{LINE}.{name}.")
