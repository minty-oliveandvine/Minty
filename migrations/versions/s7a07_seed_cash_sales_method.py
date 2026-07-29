"""Seed Cash into the sales catalog.

s1a01 deliberately excluded Cash: cash_sales has its own column, its own
``type == "Cash"`` branch in get_cash_sales_from_detail, and its own Xero
account. All of that reasoning was about what happens DOWNSTREAM of a cash
sale, and all of it stays true after this migration.

But as a thing a customer paid with, cash is exactly like Visa or Octopus.
Excluding it from the catalog costs three things:

  1. The settings page lists every payment method except the one most shops
     take most often.
  2. get_cash_sales_from_detail's fallback to report_draft.cash_sales becomes
     permanent rather than transitional — an entity with no Cash row can never
     have a Cash detail row, so the fallback IS the path.
  3. report_sale_detail is "every payment method except one", which every
     future query has to remember.

The sales form already posts sales[shop_sales][cash] (sales.html) and sales.py
already reads it (lines 332, 557). Cash is already first-class in the UI —
this only makes the data match.

WHAT DELIBERATELY DOES NOT CHANGE. This migration is additive and
behaviour-preserving:

  * get_cash_sales_from_detail still finds cash by ``type == "Cash"``. The new
    rows carry type='Cash', so the existing branch matches them — the read
    path keeps working with no code change.
  * The closing-balance formula is untouched.
  * report.cash_sales / report_draft.cash_sales KEEP their columns. They are
    the Step-5 survivors and that does not change.
  * Xero still publishes cash against cash_sale_account_id.
  * The zero-fallback in get_cash_sales_from_detail is NOT touched — it still
    returns the column whenever the detail sum is 0, so a genuine zero-cash
    day still reads the column. Fixing that changes an input to the
    closing-balance formula and needs its own verification; see the note at
    the bottom of migrations/s7a07_seed_cash_sales_method.sql.

legacy_column='cash_sales' maps the catalog row to the physical column exactly
as the other 11 do. Unlike theirs, this column is NOT dropped at Step 5.

Idempotent: the catalog row upserts on (entity_id, code); the per-entity and
detail rows are guarded on NOT EXISTS.

Revision ID: s7a07_cash_method
Revises: c2a02_cash_count
Create Date: 2026-07-29 00:00:00.000000

"""

from alembic import op
from sqlalchemy import text

revision = "s7a07_cash_method"
down_revision = "c2a02_cash_count"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"


def upgrade():
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. The global catalog row.
    # ------------------------------------------------------------------
    # entity_id IS NULL = available to every entity, same as the other 11
    # globals. type='Cash' is a THIRD type alongside 'Electronic' and
    # 'Delivery' — it is what get_cash_sales_from_detail already looks for.
    #
    # display_order 0 puts Cash ahead of Visa (1) through Octopus (7). It is
    # the most-used method; it should lead.
    bind.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.sale_info
                (id, entity_id, code, name, type, legacy_column, is_active,
                 display_order, created_at, updated_at)
            VALUES
                (gen_random_uuid()::text, NULL, 'CASH', 'Cash', 'Cash',
                 'cash_sales', TRUE, 0, NOW(), NOW())
            ON CONFLICT (entity_id, code) DO UPDATE SET
                name          = EXCLUDED.name,
                type          = EXCLUDED.type,
                legacy_column = EXCLUDED.legacy_column,
                is_active     = EXCLUDED.is_active,
                display_order = EXCLUDED.display_order,
                updated_at    = NOW()
            """
        )
    )

    # ------------------------------------------------------------------
    # 2. Give every existing entity a Cash row.
    # ------------------------------------------------------------------
    # New entities get this automatically: create_default_entity_settings
    # (blueprints/entity/services/shared.py:184) already seeds from the
    # catalog when it is populated. This backfills the ones that exist now.
    #
    # Guarded on NOT EXISTS rather than ON CONFLICT because
    # entity_sale_setting has no unique constraint on (entity_id,
    # value_name) — production contains duplicate rows, which is why
    # payment_methods.py dedupes with max(sale_id).
    bind.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.entity_sale_setting
                (sale_id, entity_id, type, sale_name, value_name,
                 sale_info_id, create_date, updated_at, display_order, enabled)
            SELECT
                gen_random_uuid()::text, e.id, 'Cash', 'Cash', 'cash_sales',
                cat.id, NOW(), NOW(), 0, TRUE
            FROM {SCHEMA}.entities e
            CROSS JOIN (
                SELECT id FROM {SCHEMA}.sale_info
                WHERE entity_id IS NULL AND code = 'CASH'
            ) cat
            WHERE NOT EXISTS (
                SELECT 1 FROM {SCHEMA}.entity_sale_setting ess
                WHERE ess.entity_id = e.id
                  AND (ess.sale_info_id = cat.id
                       OR ess.value_name = 'cash_sales')
            )
            """
        )
    )

    # ------------------------------------------------------------------
    # 3. BACKFILL: cash_sales column -> report_sale_detail.
    #                                        ** MOVES REAL DATA **
    # ------------------------------------------------------------------
    # GUARD RULE — per (report, method), NOT per report. The s1a01 backfill
    # guarded per-report on having NO detail rows at all; here every report
    # already has rows for the other 11 methods, so that guard would skip
    # every single one.
    #
    # Zero and NULL are skipped. A report with no cash sales gets no row,
    # which reads as zero — and keeps get_cash_sales_from_detail's existing
    # zero-fallback behaving exactly as it does today.
    #
    # report and report_draft share an id (ending.py:437), so the NOT EXISTS
    # guard stops the second pass double-inserting.
    for source in ("report", "report_draft"):
        bind.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.report_sale_detail
                    (id, sale_id, report_id, type, amount, create_at)
                SELECT
                    gen_random_uuid()::text, ess.sale_id, r.id, 'Cash',
                    r.cash_sales, NOW()
                FROM {SCHEMA}.{source} r
                JOIN {SCHEMA}.entity_sale_setting ess
                  ON ess.entity_id = r.company
                 AND ess.value_name = 'cash_sales'
                WHERE r.cash_sales IS NOT NULL
                  AND r.cash_sales <> 0
                  AND NOT EXISTS (
                      SELECT 1 FROM {SCHEMA}.report_sale_detail d
                      WHERE d.report_id = r.id AND d.sale_id = ess.sale_id
                  )
                """
            )
        )

    written = bind.execute(
        text(
            f"""
            SELECT count(*) FROM {SCHEMA}.report_sale_detail d
            JOIN {SCHEMA}.entity_sale_setting ess ON ess.sale_id = d.sale_id
            WHERE ess.value_name = 'cash_sales'
            """
        )
    ).scalar()
    print(f"cash detail rows now present: {written}")


def downgrade():
    bind = op.get_bind()
    # The cash_sales columns were never cleared, so dropping these rows loses
    # nothing — get_cash_sales_from_detail falls straight back to them.
    bind.execute(
        text(
            f"""
            DELETE FROM {SCHEMA}.report_sale_detail d
            USING {SCHEMA}.entity_sale_setting ess
            WHERE ess.sale_id = d.sale_id
              AND ess.value_name = 'cash_sales'
            """
        )
    )
    bind.execute(
        text(
            f"DELETE FROM {SCHEMA}.entity_sale_setting "
            f"WHERE value_name = 'cash_sales'"
        )
    )
    bind.execute(
        text(
            f"DELETE FROM {SCHEMA}.sale_info "
            f"WHERE entity_id IS NULL AND code = 'CASH'"
        )
    )
