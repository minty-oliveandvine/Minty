"""Step 5: drop the 11 legacy per-method *_sales columns from report.

THE STEP s4a04 NAMED AND NOBODY WROTE. Steps 1-4 built ``report_sale_detail``,
pointed it at the ``sales_method`` catalog, switched reads onto it and backfilled
every pre-existing report into it. This removes the columns those reads left
behind — the last step, and the only destructive one.

By the time this runs the columns are already invisible to the application: the
``Report`` model does not declare them, and ``Report.sales_by_method`` resolves
every per-method amount from detail rows. A grep for ``visa_sales`` in the app
finds dictionary keys and catalog codes, never a column read.

-----------------------------------------------------------------------------
WHY ``IF EXISTS``

The production database had these columns dropped BY HAND before this revision
was written, so it arrives here with the work already done. Without ``IF
EXISTS`` this revision would fail there and nowhere else — the worst shape of
migration bug, one that only breaks the environment you cannot easily retry.

-----------------------------------------------------------------------------
THE VERIFY QUERY IN s4a04 IS WRONG — read this before trusting it

That docstring tells you to confirm the column sums equal the detail sums
before dropping. It cannot return zero rows once ``s7a07`` seeded the cash
sales method: it excludes ``cash_sales`` from the column side (correct — cash
keeps its column) but not from the detail side, so every report with cash sales
shows a difference of exactly its cash amount.

The check that actually answers "is anything only in a column" is per-method,
not per-report-total:

    WITH m(colname, amt, rid) AS (
      SELECT 'visa_sales', visa_sales, id FROM pettycashv2.report
      UNION ALL ... one branch per column ...
    )
    SELECT m.rid, m.colname, m.amt FROM m
    WHERE m.amt IS NOT NULL AND m.amt > 0.01
      AND NOT EXISTS (
        SELECT 1 FROM pettycashv2.report_sale_detail d
        WHERE d.report_id = m.rid AND abs(d.amount - m.amt) < 0.01);

That returned zero rows on both databases before this revision was written.

-----------------------------------------------------------------------------
CASH AND THE AGGREGATES STAY

``cash_sales`` is a separate concept and keeps its column — ``s4a04`` excluded
it from the backfill for that reason and ``get_cash_sales_from_detail`` falls
back to it. ``shop_sales`` / ``delivery_sales`` / ``total_sales`` are sums
rather than methods and are recomputed, not stored per method.

Revision ID: s5a05_drop_legacy_sales
Revises: y1a01_billing_group_schema
Create Date: 2026-08-27

"""

import sqlalchemy as sa
from alembic import op

revision = "s5a05_drop_legacy_sales"
down_revision = "y1a01_billing_group_schema"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Exactly the eleven from s4a04's BACKFILL_COLUMNS. Cash and the three
# aggregates are intentionally absent — see the docstring.
LEGACY_SALES_COLUMNS = [
    "visa_sales",
    "alipay_sales",
    "wechat_sales",
    "master_sales",
    "unionpay_sales",
    "amex_sales",
    "octopus_sales",
    "foodpanda_sales",
    "keeta_sales",
    "openrice_sales",
    "deliveroo_sales",
]


def upgrade():
    for column in LEGACY_SALES_COLUMNS:
        op.execute(
            f'ALTER TABLE {SCHEMA}.report DROP COLUMN IF EXISTS "{column}"'
        )


def downgrade():
    # The columns come back EMPTY, and that is the honest outcome: the amounts
    # live in report_sale_detail now, and re-deriving them here would need the
    # catalog mapping s4a04 used, which a method deleted since would no longer
    # resolve. A downgrade restores the shape so an older build can boot; it
    # does not pretend to restore the data.
    for column in LEGACY_SALES_COLUMNS:
        op.add_column(
            "report",
            sa.Column(column, sa.Float(), nullable=True),
            schema=SCHEMA,
        )
