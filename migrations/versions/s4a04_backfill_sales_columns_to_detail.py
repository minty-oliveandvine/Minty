"""Step 3.5: backfill the 11 *_sales columns into report_sale_detail rows.

THE DATA-MOVING MIGRATION. Steps 1-3 only added columns; this one creates rows
carrying financial amounts. Read the guard rules before changing anything.

Why it is needed: report_sale_detail was introduced part-way through the
product's life. Reports written before it have their per-method amounts ONLY in
the physical columns. Step 4 switches reads to detail rows, so without this
backfill every pre-existing report would render zero sales while its data sat
untouched in columns nothing reads any more.

GUARD RULE — per REPORT, not per method:
    Only reports with NO detail rows at all are backfilled.
A report that already has even one detail row is treated as already migrated
and skipped entirely. Mixing sources per-method is how you get half-doubled
totals: the current code dual-writes some methods to detail rows while the
columns still hold every method, so a per-method NOT EXISTS would insert the
missing ones and silently disagree with what the app already displays.

Cash is excluded. cash_sales stays a column (separate concept — see Step 1),
and get_cash_sales_from_detail already falls back to it.

Aggregates are excluded. shop_sales / delivery_sales / total_sales are sums,
not methods; they keep their columns and are recomputed in Step 4.

sale_id is nullable on the inserted rows. The detail row's authoritative method
pointer is sale_info_id (Step 3); sale_id is filled opportunistically where
a matching entity_sale_setting row exists, so legacy joins keep working. Reports
entities that have since deleted a method get a detail row with sale_info_id
set and sale_id NULL — which is precisely the historical-accuracy case Step 3
was added for.

Re-runnable: the NOT EXISTS guard means a second run inserts nothing.

VERIFY BEFORE STEP 5 (drop columns). This must return zero rows:

    WITH col AS (
      SELECT id, COALESCE(visa_sales,0)+COALESCE(alipay_sales,0)
                +COALESCE(wechat_sales,0)+COALESCE(master_sales,0)
                +COALESCE(unionpay_sales,0)+COALESCE(amex_sales,0)
                +COALESCE(octopus_sales,0)+COALESCE(foodpanda_sales,0)
                +COALESCE(keeta_sales,0)+COALESCE(openrice_sales,0)
                +COALESCE(deliveroo_sales,0) AS s
      FROM pettycashv2.report),
    det AS (
      SELECT report_id, SUM(amount) AS s
      FROM pettycashv2.report_sale_detail GROUP BY report_id)
    SELECT c.id, c.s, d.s FROM col c JOIN det d ON d.report_id = c.id
    WHERE abs(c.s - d.s) > 0.01;

Revision ID: s4a04_backfill_sales
Revises: s3a03_rsd_method_fk
Create Date: 2026-07-27 00:00:00.000000

"""

import uuid

from alembic import op
from sqlalchemy import text

revision = "s4a04_backfill_sales"
down_revision = "s3a03_rsd_method_fk"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# Physical column -> catalog legacy_column. Cash and the three aggregates are
# intentionally absent.
BACKFILL_COLUMNS = [
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

# report.company holds the entity id (String(150), no FK); report_draft uses
# the same column name for the same purpose.
SOURCE_TABLES = ["report", "report_draft"]


def upgrade():
    bind = op.get_bind()

    catalog = {
        row[0]: row[1]
        for row in bind.execute(
            text(
                f"""
                SELECT legacy_column, id
                FROM {SCHEMA}.sale_info
                WHERE entity_id IS NULL AND legacy_column IS NOT NULL
                """
            )
        ).fetchall()
    }

    missing = [c for c in BACKFILL_COLUMNS if c not in catalog]
    if missing:
        raise RuntimeError(
            f"sale_info catalog is missing legacy_column rows for {missing}. "
            "Run s1a01_sales_method first."
        )

    for table in SOURCE_TABLES:
        for column in BACKFILL_COLUMNS:
            method_id = catalog[column]

            # One row per (report, method) with a non-zero amount, restricted
            # to reports that have no detail rows whatsoever.
            #
            # sale_id resolution picks the LOWEST sale_id among matching
            # entity_sale_setting rows so duplicates (payment_methods.py:38-50) resolve
            # deterministically and cannot multiply the inserted rows.
            rows = bind.execute(
                text(
                    f"""
                    SELECT r.id AS report_id,
                           r.{column} AS amount,
                           (SELECT MIN(si.sale_id)
                              FROM {SCHEMA}.entity_sale_setting si
                             WHERE si.entity_id = r.company
                               AND si.sale_info_id = :method_id
                           ) AS sale_id,
                           sm.type AS method_type
                    FROM {SCHEMA}.{table} r
                    CROSS JOIN (
                        SELECT type FROM {SCHEMA}.sale_info WHERE id = :method_id
                    ) sm
                    WHERE r.{column} IS NOT NULL
                      AND r.{column} <> 0
                      AND NOT EXISTS (
                          SELECT 1 FROM {SCHEMA}.report_sale_detail d
                          WHERE d.report_id = r.id
                      )
                      -- At THIS point in the chain report_sale_detail.report_id
                      -- references report_v2(report_id) - not report(id), which is
                      -- where r10a10 repoints it much later. SOURCE_TABLES reads
                      -- report and report_draft, and neither id is guaranteed to
                      -- exist in report_v2, so the insert can violate the key:
                      --
                      --   ForeignKeyViolation: Key (report_id)=(...) is not
                      --   present in table "report_v2"
                      --
                      -- Guarding against report_v2 rather than report is the whole
                      -- point: the constraint that will actually be checked is the
                      -- one that exists now, not the one that exists at head.
                      -- Rows with no report_v2 parent are unreachable anyway.
                      AND EXISTS (
                          SELECT 1 FROM {SCHEMA}.report_v2 rr
                          WHERE rr.report_id = r.id
                      )
                    """
                ),
                {"method_id": method_id},
            ).fetchall()

            if not rows:
                continue

            insert_detail = text(
                f"""
                INSERT INTO {SCHEMA}.report_sale_detail
                    (id, sale_id, report_id, sale_info_id, type, amount, create_at)
                VALUES
                    (:id, :sale_id, :report_id, :sale_info_id, :type, :amount, NOW())
                """
            )
            for report_id, amount, sale_id, method_type in rows:
                bind.execute(
                    insert_detail,
                    {
                        "id": str(uuid.uuid4()),
                        "sale_id": sale_id,  # may be NULL — see module docstring
                        "report_id": report_id,
                        "sale_info_id": method_id,
                        "type": method_type,
                        "amount": float(amount),
                    },
                )


def downgrade():
    # Remove only rows this migration could have created: those carrying a
    # sale_info_id but no sale_id are unambiguously backfill artefacts.
    # Rows written by the application always resolve a sale_id first, so this
    # cannot delete live data.
    #
    # Backfilled rows that DID resolve a sale_id are indistinguishable from
    # application-written ones and are intentionally left in place — deleting
    # them risks removing real data, and leaving them is harmless because the
    # columns they came from still exist until Step 5.
    op.get_bind().execute(
        text(
            f"""
            DELETE FROM {SCHEMA}.report_sale_detail
            WHERE sale_info_id IS NOT NULL
              AND sale_id IS NULL
            """
        )
    )
